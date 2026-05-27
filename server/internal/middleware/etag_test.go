package middleware_test

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"

	"github.com/metaphy6/negelir/server/internal/middleware"
)

// §9.14 proof test: test_etag_if_none_match_304
//
// Second request with If-None-Match: <prediction_id> → 304.
// Exercises the ETagConditional middleware end-to-end.
func TestETagIfNoneMatch304(t *testing.T) {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(middleware.ETagConditional())
	r.GET("/v1/matches/:id/predictions", func(c *gin.Context) {
		c.Header("ETag", `"pred-v1"`)
		c.JSON(http.StatusOK, gin.H{"prediction_id": "pred-001"})
	})

	// First request — must return 200 with ETag header.
	req1 := httptest.NewRequest(http.MethodGet, "/v1/matches/42/predictions", nil)
	w1 := httptest.NewRecorder()
	r.ServeHTTP(w1, req1)

	if w1.Code != http.StatusOK {
		t.Fatalf("first request: want 200, got %d; body: %s", w1.Code, w1.Body.String())
	}
	etag := w1.Header().Get("ETag")
	if etag == "" {
		t.Fatal("first request: ETag header must be set")
	}

	// Second request with matching If-None-Match → 304, no body.
	req2 := httptest.NewRequest(http.MethodGet, "/v1/matches/42/predictions", nil)
	req2.Header.Set("If-None-Match", etag)
	w2 := httptest.NewRecorder()
	r.ServeHTTP(w2, req2)

	if w2.Code != http.StatusNotModified {
		t.Fatalf("second request with matching ETag: want 304, got %d; body: %s",
			w2.Code, w2.Body.String())
	}
	if w2.Body.Len() > 0 {
		t.Errorf("304 response must have no body, got %d bytes", w2.Body.Len())
	}
}

// TestETagConditional_NoIfNoneMatch — fast path: request without If-None-Match
// passes through unchanged (200 with body).
func TestETagConditional_NoIfNoneMatch(t *testing.T) {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(middleware.ETagConditional())
	r.GET("/resource", func(c *gin.Context) {
		c.Header("ETag", `"v1"`)
		c.JSON(http.StatusOK, gin.H{"ok": true})
	})

	req := httptest.NewRequest(http.MethodGet, "/resource", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("want 200, got %d", w.Code)
	}
	if w.Body.Len() == 0 {
		t.Error("want non-empty body when no If-None-Match sent")
	}
}

// TestETagConditional_MismatchedETag — If-None-Match with a stale value
// must return the full 200 response (cache has changed).
func TestETagConditional_MismatchedETag(t *testing.T) {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(middleware.ETagConditional())
	r.GET("/resource", func(c *gin.Context) {
		c.Header("ETag", `"v2"`)
		c.JSON(http.StatusOK, gin.H{"ok": true})
	})

	req := httptest.NewRequest(http.MethodGet, "/resource", nil)
	req.Header.Set("If-None-Match", `"v1"`) // stale
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("stale ETag: want 200, got %d", w.Code)
	}
	if w.Body.Len() == 0 {
		t.Error("stale ETag: want non-empty body")
	}
}

// TestETagConditional_NonGetPassthrough — POST requests are not examined.
func TestETagConditional_NonGetPassthrough(t *testing.T) {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(middleware.ETagConditional())
	r.POST("/resource", func(c *gin.Context) {
		c.Header("ETag", `"v1"`)
		c.JSON(http.StatusCreated, gin.H{"ok": true})
	})

	req := httptest.NewRequest(http.MethodPost, "/resource", nil)
	req.Header.Set("If-None-Match", `"v1"`)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code != http.StatusCreated {
		t.Fatalf("POST: want 201, got %d", w.Code)
	}
}

