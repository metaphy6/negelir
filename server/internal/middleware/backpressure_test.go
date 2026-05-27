package middleware

import (
	"context"
	"errors"
	"go/ast"
	"go/parser"
	"go/token"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
)

// stubBackpressureReader implements BackpressureReader for unit tests.
type stubBackpressureReader struct {
	val string
	err error
}

func (s *stubBackpressureReader) Get(_ context.Context, _ string) (string, error) {
	return s.val, s.err
}

func newBPRouter(rdr BackpressureReader) *gin.Engine {
	r := gin.New()
	r.Use(BackpressureCheck(rdr))
	r.POST("/v1/qa", func(c *gin.Context) { c.Status(http.StatusAccepted) })
	r.GET("/v1/matches", func(c *gin.Context) { c.Status(http.StatusOK) })
	return r
}

// TestBackpressureCheck_FlagAbsent — redis.Nil (key not present) → POST passes through.
func TestBackpressureCheck_FlagAbsent(t *testing.T) {
	r := newBPRouter(&stubBackpressureReader{val: "", err: errors.New("redis: nil")})

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/v1/qa", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusAccepted {
		t.Fatalf("flag absent: POST expected 202, got %d", w.Code)
	}
}

// TestBackpressureCheck_FlagOn_GETPassesThrough — backpressure active + GET → 200.
func TestBackpressureCheck_FlagOn_GETPassesThrough(t *testing.T) {
	r := newBPRouter(&stubBackpressureReader{val: "1"})

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/v1/matches", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("backpressure GET: expected 200, got %d", w.Code)
	}
}

// TestBackpressureCheck_FlagOn_POST425 — backpressure active + POST → 425 + Retry-After: 10.
func TestBackpressureCheck_FlagOn_POST425(t *testing.T) {
	r := newBPRouter(&stubBackpressureReader{val: "1"})

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/v1/qa", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusTooEarly {
		t.Fatalf("backpressure POST: expected 425, got %d", w.Code)
	}
	if got := w.Header().Get("Retry-After"); got != "10" {
		t.Fatalf("backpressure POST: Retry-After expected \"10\", got %q", got)
	}
	if !strings.Contains(w.Body.String(), "too_early") {
		t.Fatalf("backpressure POST: body missing \"too_early\", got: %s", w.Body.String())
	}
}

// TestBackpressureCheck_RedisError_FailOpen — Redis fault → POST passes through (fail-open).
func TestBackpressureCheck_RedisError_FailOpen(t *testing.T) {
	r := newBPRouter(&stubBackpressureReader{err: errors.New("redis: connection refused")})

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/v1/qa", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusAccepted {
		t.Fatalf("redis fail-open: POST expected 202, got %d", w.Code)
	}
}

// TestBackpressureCheck_BoundaryNoMaintWrite — §9.9 boundary.
//
// Asserts that backpressure.go contains no Go string literals referencing
// maint.event.v1 or sec.alert.v1. The API must not publish to the maint
// plane; the §8.x scaler owns those topics exclusively.
// The check uses Go’s AST parser so comments do not trigger false positives.
func TestBackpressureCheck_BoundaryNoMaintWrite(t *testing.T) {
	root := repoRootFromBP(t)
	path := filepath.Join(root, "server", "internal", "middleware", "backpressure.go")
	src, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read %s: %v", path, err)
	}

	fset := token.NewFileSet()
	f, err := parser.ParseFile(fset, path, src, 0)
	if err != nil {
		t.Fatalf("parse %s: %v", path, err)
	}

	forbidden := []string{"maint.event.v1", "sec.alert.v1"}
	ast.Inspect(f, func(n ast.Node) bool {
		lit, ok := n.(*ast.BasicLit)
		if !ok || lit.Kind != token.STRING {
			return true
		}
		val := strings.Trim(lit.Value, "`\"")
		for _, fb := range forbidden {
			if strings.Contains(val, fb) {
				pos := fset.Position(lit.Pos())
				t.Errorf("§9.9 boundary violation at %s:%d — "+
					"backpressure.go contains string literal %q; "+
					"the API must not write to the maint plane",
					path, pos.Line, val)
			}
		}
		return true
	})
}

// repoRootFromBP walks up from the test directory to find the repo root (AGENTS.md).
func repoRootFromBP(t *testing.T) string {
	t.Helper()
	dir, err := os.Getwd()
	if err != nil {
		t.Fatalf("getwd: %v", err)
	}
	for {
		if _, err := os.Stat(filepath.Join(dir, "AGENTS.md")); err == nil {
			return dir
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			t.Fatal("could not find repo root (AGENTS.md)")
		}
		dir = parent
	}
}

// ── SlowClientAbort tests ────────────────────────────────────────────────────

// TestSlowClientAbort_NormalRequest — handler finishes within timeout → 200, no error code.
func TestSlowClientAbort_NormalRequest(t *testing.T) {
	r := gin.New()
	r.Use(SlowClientAbort(5 * time.Second))
	r.GET("/test", func(c *gin.Context) { c.Status(http.StatusOK) })

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/test", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("normal request: expected 200, got %d", w.Code)
	}
}

// TestSlowClientAbort_WriteTimeoutExpires — handler takes longer than writeTimeout → 499.
func TestSlowClientAbort_WriteTimeoutExpires(t *testing.T) {
	// writeTimeout is 20 ms; handler sleeps 200 ms.
	r := gin.New()
	r.Use(SlowClientAbort(20 * time.Millisecond))
	r.GET("/test", func(c *gin.Context) { time.Sleep(200 * time.Millisecond) })

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/test", nil)
	r.ServeHTTP(w, req)

	if w.Code != StatusClientClosedRequest {
		t.Fatalf("timeout expiry: expected 499, got %d", w.Code)
	}
}

// TestSlowClientAbort_WriteTimeoutSets_ErrorCode — timeout expiry sets
// ContextKeyErrorCode to "client_disconnected" on the Gin context so the
// access log middleware can record error_code=client_disconnected.
func TestSlowClientAbort_WriteTimeoutSets_ErrorCode(t *testing.T) {
	var capturedCode string

	r := gin.New()
	// Outer observer middleware: reads the error code after the full chain returns.
	r.Use(func(c *gin.Context) {
		c.Next()
		capturedCode = c.GetString(ContextKeyErrorCode)
	})
	r.Use(SlowClientAbort(20 * time.Millisecond))
	// Handler sleeps longer than the write timeout to trigger the abort.
	r.GET("/test", func(c *gin.Context) { time.Sleep(200 * time.Millisecond) })

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/test", nil)
	r.ServeHTTP(w, req)

	if w.Code != StatusClientClosedRequest {
		t.Fatalf("error_code test: expected 499, got %d", w.Code)
	}
	if capturedCode != "client_disconnected" {
		t.Fatalf("error_code test: expected \"client_disconnected\", got %q", capturedCode)
	}
}

// TestSlowClientAbort_ClientDisconnect — request context cancelled → 499.
// The handler does NOT react to context cancellation (simulating a handler
// blocked on a write). The monitor goroutine detects the cancellation and
// calls c.AbortWithStatus(499) before the handler is unblocked, ensuring
// the first WriteHeader call sets 499.
func TestSlowClientAbort_ClientDisconnect(t *testing.T) {
	reqCtx, reqCancel := context.WithCancel(context.Background())
	defer reqCancel()

	unblockHandler := make(chan struct{})

	r := gin.New()
	r.Use(SlowClientAbort(5 * time.Second))

	handlerStarted := make(chan struct{})
	r.GET("/test", func(c *gin.Context) {
		close(handlerStarted)
		// Block without inspecting the request context — simulates a handler
		// stuck writing to a slow client.
		<-unblockHandler
	})

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/test", nil)
	req = req.WithContext(reqCtx)

	done := make(chan struct{})
	go func() {
		defer close(done)
		r.ServeHTTP(w, req)
	}()

	<-handlerStarted
	// Simulate client disconnect.
	reqCancel()
	// Let the monitor goroutine react and call AbortWithStatus(499) before
	// the handler is unblocked.
	time.Sleep(20 * time.Millisecond)
	close(unblockHandler)
	<-done

	if w.Code != StatusClientClosedRequest {
		t.Fatalf("client disconnect: expected 499, got %d", w.Code)
	}
}
