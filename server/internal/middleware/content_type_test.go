package middleware

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
)

func init() {
	gin.SetMode(gin.TestMode)
}

// newTestRouter builds a minimal Gin router with EnforceContentType applied
// and registers a single GET /test route using the provided handler.
func newTestRouter(handler gin.HandlerFunc) *gin.Engine {
	r := gin.New()
	r.Use(EnforceContentType())
	r.GET("/test", handler)
	return r
}

// TestEnforceContentType_JSONAllowed verifies that application/json responses
// pass through unmodified.
func TestEnforceContentType_JSONAllowed(t *testing.T) {
	r := newTestRouter(func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"ok": true})
	})

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/test", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("status = %d; want 200", w.Code)
	}
	ct := w.Header().Get("Content-Type")
	if !strings.HasPrefix(ct, "application/json") {
		t.Fatalf("Content-Type = %q; want application/json prefix", ct)
	}
	if !strings.Contains(w.Body.String(), `"ok":true`) {
		t.Fatalf("body = %q; want ok:true", w.Body.String())
	}
}

// TestEnforceContentType_ProblemJSONAllowed verifies that
// application/problem+json (RFC 7807) responses pass through unmodified.
func TestEnforceContentType_ProblemJSONAllowed(t *testing.T) {
	r := newTestRouter(func(c *gin.Context) {
		c.Header("Content-Type", "application/problem+json")
		c.Status(http.StatusNotFound)
		body, _ := json.Marshal(problemEnvelope{
			Type:   "https://negelir.io/problems/not_found",
			Title:  "Not found",
			Status: http.StatusNotFound,
		})
		c.Writer.Write(body) //nolint:errcheck
	})

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/test", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusNotFound {
		t.Fatalf("status = %d; want 404", w.Code)
	}
	ct := w.Header().Get("Content-Type")
	if !strings.HasPrefix(ct, "application/problem+json") {
		t.Fatalf("Content-Type = %q; want application/problem+json prefix", ct)
	}
}

// TestEnforceContentType_HTMLRejected is the boundary test: a handler that
// tries to return text/html must be intercepted; the response must become
// 500 application/problem+json.
func TestEnforceContentType_HTMLRejected(t *testing.T) {
	r := newTestRouter(func(c *gin.Context) {
		c.Data(http.StatusOK, "text/html; charset=utf-8", []byte("<html>bad</html>"))
	})

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/test", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusInternalServerError {
		t.Fatalf("status = %d; want 500 (HTML must be rejected)", w.Code)
	}
	ct := w.Header().Get("Content-Type")
	if !strings.HasPrefix(ct, "application/problem+json") {
		t.Fatalf("Content-Type = %q; want application/problem+json", ct)
	}
	// Original HTML body must not appear in the response.
	if strings.Contains(w.Body.String(), "<html>") {
		t.Fatal("HTML body must not be forwarded to the client")
	}
	// Body must be valid RFC 7807 JSON.
	var env problemEnvelope
	if err := json.Unmarshal(w.Body.Bytes(), &env); err != nil {
		t.Fatalf("body is not valid JSON: %v — body: %s", err, w.Body.String())
	}
	if env.Status != http.StatusInternalServerError {
		t.Fatalf("problem status = %d; want 500", env.Status)
	}
}

// TestEnforceContentType_PlainTextRejected mirrors the HTML test for
// text/plain.
func TestEnforceContentType_PlainTextRejected(t *testing.T) {
	r := newTestRouter(func(c *gin.Context) {
		c.String(http.StatusOK, "forbidden plain text")
	})

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/test", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusInternalServerError {
		t.Fatalf("status = %d; want 500 (text/plain must be rejected)", w.Code)
	}
	ct := w.Header().Get("Content-Type")
	if !strings.HasPrefix(ct, "application/problem+json") {
		t.Fatalf("Content-Type = %q; want application/problem+json", ct)
	}
	if strings.Contains(w.Body.String(), "forbidden plain text") {
		t.Fatal("plain-text body must not be forwarded to the client")
	}
}

// TestEnforceContentType_RequestIDPropagated checks that the X-Request-ID
// from the request is echoed into the problem body's instance field when the
// interceptor fires.
func TestEnforceContentType_RequestIDPropagated(t *testing.T) {
	const reqID = "test-request-id-abc123"

	r := newTestRouter(func(c *gin.Context) {
		c.Data(http.StatusOK, "text/html", []byte("<p>bad</p>"))
	})

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/test", nil)
	req.Header.Set("X-Request-ID", reqID)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusInternalServerError {
		t.Fatalf("status = %d; want 500", w.Code)
	}
	var env problemEnvelope
	if err := json.Unmarshal(w.Body.Bytes(), &env); err != nil {
		t.Fatalf("body is not valid JSON: %v", err)
	}
	if env.Instance != reqID {
		t.Fatalf("instance = %q; want %q", env.Instance, reqID)
	}
}

// TestEnforceContentType_NoBodyUnaffected verifies that handlers that write
// no body (e.g. 204 No Content) are not affected by the middleware.
func TestEnforceContentType_NoBodyUnaffected(t *testing.T) {
	r := newTestRouter(func(c *gin.Context) {
		c.Status(http.StatusNoContent)
	})

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/test", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusNoContent {
		t.Fatalf("status = %d; want 204", w.Code)
	}
	if w.Body.Len() != 0 {
		t.Fatalf("body must be empty for 204; got %q", w.Body.String())
	}
}
