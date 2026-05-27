package middleware

import (
	"context"
	"net/http"
	"net/http/httptest"
	"runtime"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
)

// stubMaintEventReader is a test double for MaintEventReader.
type stubMaintEventReader struct {
	msgs []MaintEventMessage
	called int
}

func (s *stubMaintEventReader) ReadEvents(_ context.Context, afterID string, _ int) ([]MaintEventMessage, string, error) {
	s.called++
	if len(s.msgs) == 0 {
		return nil, afterID, nil
	}
	msgs := s.msgs
	s.msgs = nil // deliver once then drain
	return msgs, "1-1", nil
}

// TestClusterDegradedWatcher_InitiallyNotDegraded verifies the zero-value
// watcher reports IsDegraded() == false.
func TestClusterDegradedWatcher_InitiallyNotDegraded(t *testing.T) {
	t.Parallel()
	w := &ClusterDegradedWatcher{}
	if w.IsDegraded() {
		t.Fatal("watcher must be non-degraded initially")
	}
}

// TestClusterDegradedWatcher_MarkDegraded_Idempotent verifies MarkDegraded sets
// the flag and repeated calls are safe.
func TestClusterDegradedWatcher_MarkDegraded_Idempotent(t *testing.T) {
	t.Parallel()
	w := &ClusterDegradedWatcher{}
	w.MarkDegraded()
	w.MarkDegraded() // idempotent
	if !w.IsDegraded() {
		t.Fatal("watcher must be degraded after MarkDegraded")
	}
}

// TestDegradedClusterHeader_NotSetWhenHealthy verifies no X-Degraded-Cluster
// header is present when the watcher flag is clear.
func TestDegradedClusterHeader_NotSetWhenHealthy(t *testing.T) {
	t.Parallel()
	gin.SetMode(gin.TestMode)

	w := &ClusterDegradedWatcher{} // not degraded
	mw := DegradedClusterHeader(w)

	rec := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(rec)
	c.Request, _ = http.NewRequest(http.MethodGet, "/", nil)
	mw(c)

	if v := rec.Header().Get("X-Degraded-Cluster"); v != "" {
		t.Fatalf("X-Degraded-Cluster must not be set when healthy; got %q", v)
	}
}

// TestDegradedClusterHeader_SetWhenDegraded verifies the header is added after
// MarkDegraded is called.
func TestDegradedClusterHeader_SetWhenDegraded(t *testing.T) {
	t.Parallel()
	gin.SetMode(gin.TestMode)

	watcher := &ClusterDegradedWatcher{}
	watcher.MarkDegraded()
	mw := DegradedClusterHeader(watcher)

	rec := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(rec)
	c.Request, _ = http.NewRequest(http.MethodGet, "/", nil)
	mw(c)

	if got := rec.Header().Get("X-Degraded-Cluster"); got != "true" {
		t.Fatalf("X-Degraded-Cluster: want \"true\", got %q", got)
	}
}

// TestStartMaintEventWatcher_SetsFlag verifies that StartMaintEventWatcher
// delivers a scaler_replicas_pinned event to the watcher.
func TestStartMaintEventWatcher_SetsFlag(t *testing.T) {
	t.Parallel()

	reader := &stubMaintEventReader{
		msgs: []MaintEventMessage{{Kind: "scaler_replicas_pinned"}},
	}
	watcher := &ClusterDegradedWatcher{}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	StartMaintEventWatcher(ctx, reader, watcher)

	// Yield to the scheduler repeatedly until the flag is set or we time out.
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		if watcher.IsDegraded() {
			return // success
		}
		runtime.Gosched()
		time.Sleep(time.Millisecond)
	}
	t.Fatal("watcher must be degraded after scaler_replicas_pinned event")
}

// TestStartMaintEventWatcher_IgnoresOtherEvents verifies that non-pinned
// events do not set the flag.
func TestStartMaintEventWatcher_IgnoresOtherEvents(t *testing.T) {
	t.Parallel()

	reader := &stubMaintEventReader{
		msgs: []MaintEventMessage{
			{Kind: "scaler_scale_up"},
			{Kind: "backup_completed"},
		},
	}
	watcher := &ClusterDegradedWatcher{}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	StartMaintEventWatcher(ctx, reader, watcher)

	// Wait until the reader has been called at least once (messages consumed).
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		if reader.called > 0 {
			break
		}
		runtime.Gosched()
		time.Sleep(time.Millisecond)
	}

	cancel()
	if watcher.IsDegraded() {
		t.Fatal("watcher must NOT be degraded for non-pinned events")
	}
}
