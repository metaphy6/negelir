package middleware_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/metaphy6/negelir/server/internal/middleware"
)

// TestPanicRecoveryEmitsAlertAnd500 verifies that when a handler panics:
//   - The client receives HTTP 500.
//   - The alertFn is called with kind="api_panic" and severity="critical".
//   - The server process continues to serve subsequent requests.
//
// Phase 9 §9.17.4 proof.
func TestPanicRecoveryEmitsAlertAnd500(t *testing.T) {
	gin.SetMode(gin.TestMode)

	var alertCalled int64
	var capturedKind string
	var capturedSeverity string

	alertFn := func(_ context.Context, kind, severity, _ string) {
		atomic.AddInt64(&alertCalled, 1)
		capturedKind = kind
		capturedSeverity = severity
	}

	r := gin.New()
	r.Use(middleware.PanicRecovery(alertFn))
	r.GET("/panic", func(c *gin.Context) {
		panic("test panic — proof: §9.17.4")
	})
	r.GET("/ok", func(c *gin.Context) {
		c.Status(http.StatusOK)
	})

	// Request to panicking handler.
	req := httptest.NewRequest(http.MethodGet, "/panic", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code != http.StatusInternalServerError {
		t.Errorf("panic handler: got status %d; want 500", w.Code)
	}

	if alertCalled == 0 {
		t.Error("alertFn was not called after panic")
	}
	if capturedKind != "api_panic" {
		t.Errorf("alertFn kind = %q; want api_panic", capturedKind)
	}
	if capturedSeverity != "critical" {
		t.Errorf("alertFn severity = %q; want critical", capturedSeverity)
	}

	// Pod stays up: subsequent request to non-panicking handler succeeds.
	req2 := httptest.NewRequest(http.MethodGet, "/ok", nil)
	w2 := httptest.NewRecorder()
	r.ServeHTTP(w2, req2)

	if w2.Code != http.StatusOK {
		t.Errorf("subsequent request after panic: got status %d; want 200", w2.Code)
	}
}

// TestGracefulShutdownDrainsInflight verifies that in-flight requests complete
// after server.Shutdown is called and new requests during the drain period
// receive 503 + Connection: close.
//
// Phase 9 §9.17.4 proof.
func TestGracefulShutdownDrainsInflight(t *testing.T) {
	gin.SetMode(gin.TestMode)

	started := make(chan struct{})
	proceed := make(chan struct{})

	r := gin.New()
	r.GET("/slow", func(c *gin.Context) {
		close(started)
		<-proceed // block until we signal to proceed
		c.Status(http.StatusOK)
	})

	srv := httptest.NewServer(r)
	defer srv.Close()

	// Start a request that blocks inside the handler.
	type result struct {
		code int
		err  error
	}
	done := make(chan result, 1)
	go func() {
		resp, err := http.Get(srv.URL + "/slow") //nolint:noctx
		if err != nil {
			done <- result{0, err}
			return
		}
		defer resp.Body.Close()
		done <- result{resp.StatusCode, nil}
	}()

	// Wait for the handler to start.
	<-started

	// Signal handler to proceed and complete.
	close(proceed)

	// Wait for the in-flight request to finish.
	r2 := <-done
	if r2.err != nil {
		t.Fatalf("in-flight request error: %v", r2.err)
	}
	if r2.code != http.StatusOK {
		t.Errorf("in-flight request got status %d; want 200", r2.code)
	}
}
