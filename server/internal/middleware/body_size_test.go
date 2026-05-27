package middleware

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
)

// newBodySizeRouter builds a minimal Gin router with BodySizeCap(maxBytes)
// applied globally and registers a POST /test route that echoes the body.
func newBodySizeRouter(maxBytes int64) *gin.Engine {
	r := gin.New()
	r.Use(BodySizeCap(maxBytes))
	r.POST("/test", func(c *gin.Context) {
		body, err := io.ReadAll(c.Request.Body)
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}
		c.JSON(http.StatusOK, gin.H{"len": len(body)})
	})
	return r
}

// TestBodySizeCap_UnderLimit verifies that a body below the cap passes
// through to the handler and the handler can read it fully.
func TestBodySizeCap_UnderLimit(t *testing.T) {
	const limit = 100
	r := newBodySizeRouter(limit)

	body := strings.Repeat("x", limit-1) // 99 bytes — under the cap
	req := httptest.NewRequest(http.MethodPost, "/test", strings.NewReader(body))
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", w.Code, w.Body.String())
	}
	var resp struct{ Len int }
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if resp.Len != limit-1 {
		t.Fatalf("expected len=%d, got %d", limit-1, resp.Len)
	}
}

// TestBodySizeCap_AtLimit verifies that a body exactly at the cap is accepted.
func TestBodySizeCap_AtLimit(t *testing.T) {
	const limit = 100
	r := newBodySizeRouter(limit)

	body := strings.Repeat("x", limit) // exactly at the cap
	req := httptest.NewRequest(http.MethodPost, "/test", strings.NewReader(body))
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200 at limit, got %d: %s", w.Code, w.Body.String())
	}
}

// TestBodySizeCap_OverLimit verifies that a body exceeding the cap returns
// 413 application/problem+json with the correct error code.
func TestBodySizeCap_OverLimit(t *testing.T) {
	const limit = 100
	r := newBodySizeRouter(limit)

	body := strings.Repeat("x", limit+1) // one byte over
	req := httptest.NewRequest(http.MethodPost, "/test", strings.NewReader(body))
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("expected 413, got %d: %s", w.Code, w.Body.String())
	}
	ct := w.Header().Get("Content-Type")
	if !strings.HasPrefix(ct, "application/problem+json") {
		t.Fatalf("expected application/problem+json Content-Type, got %q", ct)
	}
	var prob struct {
		Type   string `json:"type"`
		Status int    `json:"status"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &prob); err != nil {
		t.Fatalf("unmarshal problem: %v", err)
	}
	if prob.Status != http.StatusRequestEntityTooLarge {
		t.Fatalf("expected problem.status=413, got %d", prob.Status)
	}
	if !strings.Contains(prob.Type, "payload_too_large") {
		t.Fatalf("expected type to contain 'payload_too_large', got %q", prob.Type)
	}
}

// TestBodySizeCap_WellOverLimit verifies rejection when the body is many
// times larger than the cap (adversarial large-body scenario).
func TestBodySizeCap_WellOverLimit(t *testing.T) {
	const limit = 64
	r := newBodySizeRouter(limit)

	// 1 MB — well above the 64-byte cap; simulates a bcrypt-bomb payload.
	body := strings.Repeat("a", 1<<20)
	req := httptest.NewRequest(http.MethodPost, "/test", strings.NewReader(body))
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("expected 413 for oversized body, got %d", w.Code)
	}
}

// TestBodySizeCap_NilBody verifies that requests without a body (nil Body)
// pass through without error.
func TestBodySizeCap_NilBody(t *testing.T) {
	r := newBodySizeRouter(100)

	req := httptest.NewRequest(http.MethodPost, "/test", nil)
	req.Body = nil
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200 for nil body, got %d: %s", w.Code, w.Body.String())
	}
}

// TestBodySizeCap_NoBodyRequest verifies http.NoBody passes through.
func TestBodySizeCap_NoBodyRequest(t *testing.T) {
	r := newBodySizeRouter(100)

	req := httptest.NewRequest(http.MethodPost, "/test", http.NoBody)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200 for http.NoBody, got %d: %s", w.Code, w.Body.String())
	}
}
