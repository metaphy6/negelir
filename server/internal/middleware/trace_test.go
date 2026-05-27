package middleware

import (
	"net/http"
	"net/http/httptest"
	"regexp"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
)

// traceparentRespRe matches a full W3C traceparent response header:
// version 00, 32-hex traceID, 16-hex spanID, flags 01 (sampled).
var traceparentRespRe = regexp.MustCompile(`^00-[0-9a-f]{32}-[0-9a-f]{16}-01$`)

// traceIDRe matches a bare 32 lower-case hex string.
var traceIDRe = regexp.MustCompile(`^[0-9a-f]{32}$`)

// newTPRouter builds a minimal Gin engine with TraceParent applied.
func newTPRouter(h gin.HandlerFunc) *gin.Engine {
	r := gin.New()
	r.Use(TraceParent())
	r.GET("/ping", h)
	return r
}

// TestTraceParent_MintsWhenAbsent -- (a) a request with no Traceparent or
// X-Request-ID gets a freshly-minted W3C traceparent on the response.
func TestTraceParent_MintsWhenAbsent(t *testing.T) {
	r := newTPRouter(func(c *gin.Context) { c.Status(http.StatusOK) })

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/ping", nil)
	r.ServeHTTP(w, req)

	tp := w.Header().Get("Traceparent")
	if tp == "" {
		t.Fatal("Traceparent response header is empty; want minted traceparent")
	}
	if !traceparentRespRe.MatchString(tp) {
		t.Fatalf("minted Traceparent %q does not match 00-<32hex>-<16hex>-01", tp)
	}
}

// TestTraceParent_ReusesIncomingTraceID -- (b) a request with a valid
// Traceparent reuses its trace_id component; only the span_id is replaced.
func TestTraceParent_ReusesIncomingTraceID(t *testing.T) {
	r := newTPRouter(func(c *gin.Context) { c.Status(http.StatusOK) })

	const (
		incomingTP      = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
		wantTraceID     = "4bf92f3577b34da6a3ce929d0e0e4736"
		incomingSpanID  = "00f067aa0ba902b7"
	)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/ping", nil)
	req.Header.Set("Traceparent", incomingTP)
	r.ServeHTTP(w, req)

	got := w.Header().Get("Traceparent")
	if got == "" {
		t.Fatal("Traceparent response header is empty")
	}
	if !traceparentRespRe.MatchString(got) {
		t.Fatalf("response Traceparent %q does not match expected format", got)
	}
	// The trace_id component (position 1 when split by "-") must equal the original.
	parts := strings.SplitN(got, "-", 4)
	if parts[1] != wantTraceID {
		t.Fatalf("trace_id: got %q; want %q", parts[1], wantTraceID)
	}
	// Span_id (position 2) must be REPLACED -- this hop gets its own span.
	if parts[2] == incomingSpanID {
		t.Errorf("span_id was not replaced; trace hop should have its own span_id")
	}
}

// TestTraceParent_XRequestIDAlias -- (c) the X-Request-ID response header
// echoes the trace_id (32 lower-case hex) as the client-side alias.
func TestTraceParent_XRequestIDAlias(t *testing.T) {
	r := newTPRouter(func(c *gin.Context) { c.Status(http.StatusOK) })

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/ping", nil)
	r.ServeHTTP(w, req)

	tp := w.Header().Get("Traceparent")
	xrid := w.Header().Get("X-Request-ID")
	if tp == "" || xrid == "" {
		t.Fatalf("one or both headers empty: Traceparent=%q X-Request-ID=%q", tp, xrid)
	}
	// X-Request-ID must equal the trace_id part of the Traceparent.
	parts := strings.SplitN(tp, "-", 4)
	if len(parts) < 4 {
		t.Fatalf("malformed Traceparent: %q", tp)
	}
	if xrid != parts[1] {
		t.Fatalf("X-Request-ID %q != trace_id from Traceparent %q", xrid, parts[1])
	}
}

// TestTraceParent_ContextKeySet -- the 32-hex trace_id is stored in the Gin
// context under ContextKeyTraceID and is accessible by downstream handlers.
func TestTraceParent_ContextKeySet(t *testing.T) {
	var contextTraceID string
	r := gin.New()
	r.Use(TraceParent())
	r.GET("/ping", func(c *gin.Context) {
		v, _ := c.Get(ContextKeyTraceID)
		contextTraceID, _ = v.(string)
		c.Status(http.StatusOK)
	})

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/ping", nil)
	r.ServeHTTP(w, req)

	if !traceIDRe.MatchString(contextTraceID) {
		t.Fatalf("context %q = %q; want 32 lower-case hex chars", ContextKeyTraceID, contextTraceID)
	}
}

// TestTraceParent_XRequestIDAliasInput -- when the client sends X-Request-ID
// (a valid UUIDv7), its hex form is adopted as the trace_id so correlation
// works across legacy clients that do not send Traceparent.
func TestTraceParent_XRequestIDAliasInput(t *testing.T) {
	r := newTPRouter(func(c *gin.Context) { c.Status(http.StatusOK) })

	// A valid UUIDv7; hex without dashes = 32 chars.
	const xrid = "0195f4a1-dead-7000-8000-000000000001"
	const wantTraceID = "0195f4a1dead70008000000000000001"

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/ping", nil)
	req.Header.Set("X-Request-ID", xrid)
	r.ServeHTTP(w, req)

	parts := strings.SplitN(w.Header().Get("Traceparent"), "-", 4)
	if len(parts) < 4 {
		t.Fatalf("Traceparent header missing or malformed")
	}
	if parts[1] != wantTraceID {
		t.Fatalf("trace_id from X-Request-ID: got %q; want %q", parts[1], wantTraceID)
	}
	// X-Request-ID response must also echo the trace_id.
	if got := w.Header().Get("X-Request-ID"); got != wantTraceID {
		t.Fatalf("X-Request-ID response: got %q; want %q", got, wantTraceID)
	}
}

// TestTraceParent_InvalidTraceparentFallsToMint -- a syntactically invalid
// Traceparent header is silently ignored; a fresh trace_id is minted.
func TestTraceParent_InvalidTraceparentFallsToMint(t *testing.T) {
	r := newTPRouter(func(c *gin.Context) { c.Status(http.StatusOK) })

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/ping", nil)
	req.Header.Set("Traceparent", "garbage-not-a-traceparent")
	r.ServeHTTP(w, req)

	tp := w.Header().Get("Traceparent")
	if !traceparentRespRe.MatchString(tp) {
		t.Fatalf("expected fresh minted traceparent, got %q", tp)
	}
}
