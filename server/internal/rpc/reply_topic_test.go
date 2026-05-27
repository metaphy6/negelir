package rpc_test

// §9.3 — Per-pod reply_to topic tests.
//
// Tests:
//  1. TestReplyTopic_Format — happy path: topic name matches expected format.
//  2. TestIsReplyTopic       — prefix detection: true for api.reply.*, false for others.
//  3. TestReaper_SweepsStale — reaper deletes streams whose idle exceeds staleAfter.
//  4. TestReaper_KeepsFresh  — reaper does NOT delete streams idle < staleAfter.
//  5. TestReaper_StopsOnCancel — Run exits cleanly when context is cancelled.
//  6. TestBoundary_ReplyTopicSoleConsumer — AST scan: no file outside
//     server/internal/rpc/ references "api.reply." as a string literal.
//     This enforces the §9.3 boundary contract that the API is the SOLE
//     writer/consumer of api.reply.* streams.

import (
	"context"
	"errors"
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
// Unit tests
// ---------------------------------------------------------------------------

func TestReplyTopic_Format(t *testing.T) {
	topic := rpc.ReplyTopic("pod-abc", "deadbeef")
	const want = "api.reply.pod-abc.deadbeef"
	if topic != want {
		t.Fatalf("ReplyTopic = %q; want %q", topic, want)
	}
	if !rpc.IsReplyTopic(topic) {
		t.Fatalf("IsReplyTopic(%q) = false; want true", topic)
	}
}

func TestIsReplyTopic(t *testing.T) {
	cases := []struct {
		key  string
		want bool
	}{
		{"api.reply.pod1.abc123", true},
		{"api.reply.", true},           // bare prefix
		{"predict.request.v1", false},
		{"api.request.v1", false},
		{"", false},
	}
	for _, c := range cases {
		got := rpc.IsReplyTopic(c.key)
		if got != c.want {
			t.Errorf("IsReplyTopic(%q) = %v; want %v", c.key, got, c.want)
		}
	}
}

// ---------------------------------------------------------------------------
// Reaper tests — fake Redis implementation
// ---------------------------------------------------------------------------

type fakeRedis struct {
	mu      sync.Mutex
	streams map[string]time.Duration // key -> idle duration
	deleted []string
}

func (f *fakeRedis) ScanReplyStreams(_ context.Context, fn func(string, time.Duration) error) error {
	f.mu.Lock()
	keys := make([]string, 0, len(f.streams))
	idles := make(map[string]time.Duration, len(f.streams))
	for k, v := range f.streams {
		keys = append(keys, k)
		idles[k] = v
	}
	f.mu.Unlock()
	for _, k := range keys {
		if err := fn(k, idles[k]); err != nil {
			return err
		}
	}
	return nil
}

func (f *fakeRedis) DelStream(_ context.Context, key string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	delete(f.streams, key)
	f.deleted = append(f.deleted, key)
	return nil
}

func TestReaper_SweepsStale(t *testing.T) {
	redis := &fakeRedis{
		streams: map[string]time.Duration{
			"api.reply.pod1.stale1": 10 * time.Second, // stale (> 5s)
			"api.reply.pod1.stale2": 6 * time.Second,  // stale
		},
	}
	reaper := rpc.NewReaper(redis, time.Hour, 5*time.Second)
	ctx := context.Background()
	// Directly trigger a sweep via the exported helper.
	if err := reaper.SweepOnce(ctx); err != nil {
		t.Fatalf("sweep error: %v", err)
	}
	if len(redis.deleted) != 2 {
		t.Fatalf("deleted %d streams; want 2 (got %v)", len(redis.deleted), redis.deleted)
	}
}

func TestReaper_KeepsFresh(t *testing.T) {
	redis := &fakeRedis{
		streams: map[string]time.Duration{
			"api.reply.pod1.fresh": 1 * time.Second, // fresh (< 5s)
		},
	}
	reaper := rpc.NewReaper(redis, time.Hour, 5*time.Second)
	ctx := context.Background()
	if err := reaper.SweepOnce(ctx); err != nil {
		t.Fatalf("sweep error: %v", err)
	}
	if len(redis.deleted) != 0 {
		t.Fatalf("deleted %d streams; want 0 (should keep fresh stream)", len(redis.deleted))
	}
}

func TestReaper_StopsOnCancel(t *testing.T) {
	redis := &fakeRedis{streams: map[string]time.Duration{}}
	reaper := rpc.NewReaper(redis, 10*time.Millisecond, time.Second)
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() {
		defer close(done)
		reaper.Run(ctx)
	}()
	cancel()
	select {
	case <-done:
		// ok — Run exited
	case <-time.After(2 * time.Second):
		t.Fatal("Reaper.Run did not exit within 2s after context cancel")
	}
}

// ---------------------------------------------------------------------------
// Adversarial: fake Redis DelStream returns error — sweep continues & reports.
// ---------------------------------------------------------------------------

type errorRedis struct{ fakeRedis }

func (e *errorRedis) DelStream(_ context.Context, key string) error {
	e.fakeRedis.mu.Lock()
	defer e.fakeRedis.mu.Unlock()
	delete(e.fakeRedis.streams, key)
	e.fakeRedis.deleted = append(e.fakeRedis.deleted, key)
	return errors.New("simulated del error")
}

func TestReaper_DelError_ReturnsFirstError(t *testing.T) {
	redis := &errorRedis{fakeRedis: fakeRedis{
		streams: map[string]time.Duration{
			"api.reply.pod1.s1": 10 * time.Second,
		},
	}}
	reaper := rpc.NewReaper(redis, time.Hour, 5*time.Second)
	err := reaper.SweepOnce(context.Background())
	if err == nil {
		t.Fatal("expected an error from SweepOnce; got nil")
	}
}

// ---------------------------------------------------------------------------
// Boundary test: §9.3 sole-consumer contract
// ---------------------------------------------------------------------------
//
// This AST scan walks every .go file under server/ OUTSIDE of
// server/internal/rpc/ and asserts that no file contains the string literal
// "api.reply." as a raw string constant or in a call expression.
// A violation means some other component is writing to or reading from the
// api.reply.* namespace, which breaks the §9.3 boundary.
//
// Files in server/internal/rpc/ itself are exempt (they own the namespace).
// Test files (*_test.go) OUTSIDE rpc/ that reference the prefix for
// assertion purposes are also exempt — they import the rpc package and
// reference the constant via rpc.ReplyTopicPrefix().

func TestBoundary_ReplyTopicSoleConsumer(t *testing.T) {
	// Locate server/ root relative to this test file.
	// go test runs with cwd = package dir, so we walk up.
	serverRoot := findServerRoot(t)
	rpcDir := filepath.Join(serverRoot, "internal", "rpc")

	fset := token.NewFileSet()
	var violations []string

	err := filepath.WalkDir(serverRoot, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() {
			return nil
		}
		if !strings.HasSuffix(path, ".go") {
			return nil
		}
		// Exempt the rpc package itself.
		if strings.HasPrefix(filepath.Clean(path), filepath.Clean(rpcDir)) {
			return nil
		}
		f, parseErr := parser.ParseFile(fset, path, nil, 0)
		if parseErr != nil {
			// Non-fatal: skip unparseable generated files.
			return nil
		}
		ast.Inspect(f, func(n ast.Node) bool {
			lit, ok := n.(*ast.BasicLit)
			if !ok || lit.Kind != token.STRING {
				return true
			}
			// Strip surrounding quotes.
			v := strings.Trim(lit.Value, "`\"")
			if strings.Contains(v, "api.reply.") {
				pos := fset.Position(lit.Pos())
				violations = append(violations,
					pos.String()+": string literal contains \"api.reply.\"")
			}
			return true
		})
		return nil
	})
	if err != nil {
		t.Fatalf("WalkDir error: %v", err)
	}
	if len(violations) > 0 {
		t.Errorf("§9.3 boundary violated — non-rpc files reference \"api.reply.*\":\n%s",
			strings.Join(violations, "\n"))
	}
}

func findServerRoot(t *testing.T) string {
	t.Helper()
	cwd, err := os.Getwd()
	if err != nil {
		t.Fatalf("getwd: %v", err)
	}
	// Walk up from current package dir until we find go.mod or "server/".
	for dir := cwd; dir != "/" && dir != "."; dir = filepath.Dir(dir) {
		if _, err := os.Stat(filepath.Join(dir, "go.mod")); err == nil {
			return dir
		}
	}
	t.Fatalf("could not locate server root (go.mod) from %s", cwd)
	return ""
}
