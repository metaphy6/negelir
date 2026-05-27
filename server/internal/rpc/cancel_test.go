package rpc_test

// §9.3 — Cancellation propagation tests.
//
// Tests:
//  1. TestWatchAndCancel_PublishesOnDisconnect   — client disconnect triggers publish.
//  2. TestWatchAndCancel_NoPublishWhenRPCDone    — RPC completed first: no publish.
//  3. TestWatchAndCancel_IdempotentRace          — rpcDone + clientCtx fire simultaneously:
//                                                  cancel is dropped without alerting.
//  4. TestBoundary_CancelTopicSolePublisher      — AST scan: "predict.cancel.v1" only
//                                                  appears in server/internal/rpc/.
//                                                  Enforces the §9.3 single-producer contract.

import (
	"context"
	"go/ast"
	"go/parser"
	"go/token"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/metaphy6/negelir/server/internal/rpc"
)

// ---------------------------------------------------------------------------
// Stub CancelPublisher
// ---------------------------------------------------------------------------

type stubCancelPublisher struct {
	mu         sync.Mutex
	calls      []rpc.CancelMessage
	publishErr error
}

func (s *stubCancelPublisher) PublishCancel(_ context.Context, msg rpc.CancelMessage) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.calls = append(s.calls, msg)
	return s.publishErr
}

func (s *stubCancelPublisher) CallCount() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return len(s.calls)
}

func (s *stubCancelPublisher) LastMessage() (rpc.CancelMessage, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if len(s.calls) == 0 {
		return rpc.CancelMessage{}, false
	}
	return s.calls[len(s.calls)-1], true
}

// ---------------------------------------------------------------------------
// Unit tests
// ---------------------------------------------------------------------------

// TestWatchAndCancel_PublishesOnDisconnect verifies that when the client context
// is cancelled BEFORE rpcDone closes, WatchAndCancel publishes exactly one
// predict.cancel.v1 message with the correct request_id.
func TestWatchAndCancel_PublishesOnDisconnect(t *testing.T) {
	pub := &stubCancelPublisher{}
	rpcDone := make(chan struct{}) // never closed during this test

	clientCtx, clientCancel := context.WithCancel(context.Background())

	done := make(chan struct{})
	go func() {
		defer close(done)
		rpc.WatchAndCancel(clientCtx, rpcDone, "req-abc-123", pub)
	}()

	// Simulate client disconnect.
	clientCancel()

	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("WatchAndCancel did not return within timeout")
	}

	if n := pub.CallCount(); n != 1 {
		t.Fatalf("PublishCancel called %d times; want 1", n)
	}
	msg, _ := pub.LastMessage()
	if msg.RequestID != "req-abc-123" {
		t.Errorf("CancelMessage.RequestID = %q; want %q", msg.RequestID, "req-abc-123")
	}
}

// TestWatchAndCancel_NoPublishWhenRPCDone verifies that when rpcDone closes
// BEFORE the client context is cancelled, WatchAndCancel returns without
// publishing any cancel message.
func TestWatchAndCancel_NoPublishWhenRPCDone(t *testing.T) {
	pub := &stubCancelPublisher{}
	rpcDone := make(chan struct{})

	clientCtx, clientCancel := context.WithCancel(context.Background())
	defer clientCancel()

	done := make(chan struct{})
	go func() {
		defer close(done)
		rpc.WatchAndCancel(clientCtx, rpcDone, "req-xyz-456", pub)
	}()

	// RPC completes first.
	close(rpcDone)

	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("WatchAndCancel did not return within timeout")
	}

	if n := pub.CallCount(); n != 0 {
		t.Errorf("PublishCancel called %d times; want 0 (RPC completed first)", n)
	}
}

// TestWatchAndCancel_IdempotentRace verifies the idempotency / race contract
// from §9.3: when rpcDone and clientCtx.Done() fire at approximately the same
// time, WatchAndCancel must not panic, must not alert, and must publish at most
// one cancel message (0 or 1 — the race winner is non-deterministic).
//
// The test runs the race 100 times and asserts: no panic, ≤ 1 publish per run.
func TestWatchAndCancel_IdempotentRace(t *testing.T) {
	for i := 0; i < 100; i++ {
		pub := &stubCancelPublisher{}
		rpcDone := make(chan struct{})

		clientCtx, clientCancel := context.WithCancel(context.Background())

		done := make(chan struct{})
		go func() {
			defer close(done)
			rpc.WatchAndCancel(clientCtx, rpcDone, "req-race", pub)
		}()

		// Fire both simultaneously from separate goroutines.
		var wg sync.WaitGroup
		wg.Add(2)
		go func() { defer wg.Done(); close(rpcDone) }()
		go func() { defer wg.Done(); clientCancel() }()
		wg.Wait()

		select {
		case <-done:
		case <-time.After(2 * time.Second):
			t.Fatalf("iter %d: WatchAndCancel did not return within timeout", i)
		}

		if n := pub.CallCount(); n > 1 {
			t.Errorf("iter %d: PublishCancel called %d times; want <= 1", i, n)
		}
	}
}

// ---------------------------------------------------------------------------
// Boundary test — §9.3 single-producer contract
// ---------------------------------------------------------------------------

// TestBoundary_CancelTopicSolePublisher scans all .go files under server/ and
// asserts that the string literal "predict.cancel.v1" only appears inside
// server/internal/rpc/ (the sole publisher) or server/cmd/swarmctl/ (the
// read-only wire-authority reporter and ops CLI — references the literal as
// a declaration in wireAuthorityProducers + staticAgentManifest, never
// publishes). Any other package referencing this literal violates the §9.3
// single-producer contract.
func TestBoundary_CancelTopicSolePublisher(t *testing.T) {
	serverRoot, err := findCancelServerRoot()
	if err != nil {
		t.Fatalf("findCancelServerRoot: %v", err)
	}

	const literal = "predict.cancel.v1"
	// Allowed: any file whose path contains /internal/rpc/ (sole publisher)
	// or /cmd/swarmctl/ (read-only wire-authority reporter).
	const allowedRPC      = "internal" + string(os.PathSeparator) + "rpc" + string(os.PathSeparator)
	const allowedSwarmctl = "cmd" + string(os.PathSeparator) + "swarmctl" + string(os.PathSeparator)

	var violations []string

	err = filepath.WalkDir(serverRoot, func(path string, d fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if d.IsDir() {
			return nil
		}
		if filepath.Ext(path) != ".go" {
			return nil
		}
		// Skip allowed paths — they reference the literal by design.
		if strings.Contains(path, allowedRPC) || strings.Contains(path, allowedSwarmctl) {
			return nil
		}
		fset := token.NewFileSet()
		f, parseErr := parser.ParseFile(fset, path, nil, 0)
		if parseErr != nil {
			return nil // ignore unparseable files
		}
		ast.Inspect(f, func(n ast.Node) bool {
			lit, ok := n.(*ast.BasicLit)
			if !ok {
				return true
			}
			// BasicLit.Value includes surrounding quotes.
			if strings.Contains(lit.Value, literal) {
				violations = append(violations, path)
			}
			return true
		})
		return nil
	})
	if err != nil {
		t.Fatalf("WalkDir: %v", err)
	}
	if len(violations) > 0 {
		t.Errorf("§9.3 boundary violation: %q referenced outside server/internal/rpc/ in:\n  %s",
			literal, strings.Join(violations, "\n  "))
	}
}

// findCancelServerRoot walks up from the current directory to find the server/ directory.
func findCancelServerRoot() (string, error) {
	cwd, err := os.Getwd()
	if err != nil {
		return "", err
	}
	dir := cwd
	for {
		base := filepath.Base(dir)
		if base == "server" {
			return dir, nil
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			break
		}
		dir = parent
	}
	// Fallback: try relative path from cwd.
	candidate := filepath.Join(cwd, "server")
	if _, statErr := os.Stat(candidate); statErr == nil {
		return candidate, nil
	}
	return "", os.ErrNotExist
}
