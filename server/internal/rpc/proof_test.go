package rpc_test

// proof_test.go — §9.14 Request flow & RPC proof tests (tests 6–9).
//
//   TestCancellationPublishesPredictCancel   (§9.14 test 6)
//   TestCancellationPostFinalDroppedSilently (§9.14 test 7)
//   TestReplyToTopicPerPodIsolated           (§9.14 test 8)
//   TestPredictApprovedOnlyNeverPredictFinal (§9.14 test 9)
//
// Stubs stubCancelPublisher, fakeRedis, and helper findCancelServerRoot are
// defined in cancel_test.go / reply_topic_test.go (same package).

import (
	"context"
	"go/ast"
	"go/parser"
	"go/token"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/metaphy6/negelir/server/internal/rpc"
)

// ---------------------------------------------------------------------------
// §9.14 Test 6: TestCancellationPublishesPredictCancel
// ---------------------------------------------------------------------------

// TestCancellationPublishesPredictCancel — client disconnect mid-RPC triggers
// exactly one predict.cancel.v1 publish via CancelPublisher.
func TestCancellationPublishesPredictCancel(t *testing.T) {
	pub := &stubCancelPublisher{}
	rpcDone := make(chan struct{})
	clientCtx, clientCancel := context.WithCancel(context.Background())

	done := make(chan struct{})
	go func() {
		defer close(done)
		rpc.WatchAndCancel(clientCtx, rpcDone, "req-cancel-proof", pub)
	}()

	clientCancel() // simulate client disconnect

	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("WatchAndCancel did not return within 2s after client cancel")
	}

	if n := pub.CallCount(); n != 1 {
		t.Fatalf("PublishCancel called %d times; want 1", n)
	}
	msg, ok := pub.LastMessage()
	if !ok {
		t.Fatal("LastMessage: no message recorded")
	}
	if msg.RequestID != "req-cancel-proof" {
		t.Errorf("RequestID = %q; want %q", msg.RequestID, "req-cancel-proof")
	}
}

// ---------------------------------------------------------------------------
// §9.14 Test 7: TestCancellationPostFinalDroppedSilently
// ---------------------------------------------------------------------------

// TestCancellationPostFinalDroppedSilently — cancel arriving AFTER the RPC
// has completed (rpcDone closed) must be dropped silently (no publish, no alert).
func TestCancellationPostFinalDroppedSilently(t *testing.T) {
	pub := &stubCancelPublisher{}
	rpcDone := make(chan struct{})
	clientCtx, clientCancel := context.WithCancel(context.Background())
	defer clientCancel()

	done := make(chan struct{})
	go func() {
		defer close(done)
		rpc.WatchAndCancel(clientCtx, rpcDone, "req-post-final", pub)
	}()

	close(rpcDone) // RPC completes first

	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("WatchAndCancel did not return within 2s after rpcDone")
	}

	if n := pub.CallCount(); n != 0 {
		t.Errorf("PublishCancel called %d times after RPC done; want 0", n)
	}
}

// ---------------------------------------------------------------------------
// §9.14 Test 8: TestReplyToTopicPerPodIsolated
// ---------------------------------------------------------------------------

// TestReplyToTopicPerPodIsolated — two API pods produce non-overlapping
// api.reply.* streams; the reaper sweeps the orphan stream from the dead pod.
func TestReplyToTopicPerPodIsolated(t *testing.T) {
	pod1Topic := rpc.ReplyTopic("pod1", "req-abc")
	pod2Topic := rpc.ReplyTopic("pod2", "req-abc")

	if pod1Topic == pod2Topic {
		t.Errorf("topics must differ across pods: pod1=%q pod2=%q", pod1Topic, pod2Topic)
	}
	if !strings.HasPrefix(pod1Topic, "api.reply.pod1.") {
		t.Errorf("pod1 topic %q has wrong prefix; want api.reply.pod1.*", pod1Topic)
	}
	if !strings.HasPrefix(pod2Topic, "api.reply.pod2.") {
		t.Errorf("pod2 topic %q has wrong prefix; want api.reply.pod2.*", pod2Topic)
	}

	// Construct fakeRedis with pod1's stream stale (orphan) and pod2's fresh.
	fr := &fakeRedis{
		streams: map[string]time.Duration{
			pod1Topic: 10 * time.Second, // idle longer than staleAfter=5s → orphan
			pod2Topic: 1 * time.Second,  // fresh → must survive
		},
	}
	reaper := rpc.NewReaper(fr, time.Hour, 5*time.Second)
	if err := reaper.SweepOnce(context.Background()); err != nil {
		t.Fatalf("SweepOnce: %v", err)
	}
	if len(fr.deleted) != 1 || fr.deleted[0] != pod1Topic {
		t.Errorf("reaper deleted %v; want [%q]", fr.deleted, pod1Topic)
	}
}

// ---------------------------------------------------------------------------
// §9.14 Test 9: TestPredictApprovedOnlyNeverPredictFinal
// ---------------------------------------------------------------------------

// TestPredictApprovedOnlyNeverPredictFinal — AST scan: the literal string
// "predict.final" must not appear in any non-test, non-swarmctl server source.
// The API gateway must only consume predict.approved.v1 (§9.3 boundary).
func TestPredictApprovedOnlyNeverPredictFinal(t *testing.T) {
	serverRoot, err := findCancelServerRoot()
	if err != nil {
		t.Fatalf("findCancelServerRoot: %v", err)
	}
	const literal = "predict.final"
	// swarmctl is explicitly permitted: it may document or reference the topic.
	allowedSwarmctl := filepath.Join("cmd", "swarmctl") + string(os.PathSeparator)

	var violations []string
	walkErr := filepath.WalkDir(serverRoot, func(path string, d fs.DirEntry, e error) error {
		if e != nil || d.IsDir() {
			return e
		}
		if filepath.Ext(path) != ".go" {
			return nil
		}
		// Skip test files and swarmctl (permitted to reference the topic).
		if strings.HasSuffix(path, "_test.go") {
			return nil
		}
		rel, _ := filepath.Rel(serverRoot, path)
		if strings.HasPrefix(rel, allowedSwarmctl) {
			return nil
		}
		fset := token.NewFileSet()
		f, parseErr := parser.ParseFile(fset, path, nil, 0)
		if parseErr != nil {
			return nil // skip unparseable files
		}
		ast.Inspect(f, func(n ast.Node) bool {
			lit, ok := n.(*ast.BasicLit)
			if !ok {
				return true
			}
			if strings.Contains(lit.Value, literal) {
				violations = append(violations, rel)
			}
			return true
		})
		return nil
	})
	if walkErr != nil {
		t.Fatalf("WalkDir(%s): %v", serverRoot, walkErr)
	}
	if len(violations) > 0 {
		t.Errorf("§9.14 boundary: %q found in non-test server source:\n  %s",
			literal, strings.Join(violations, "\n  "))
	}
}
