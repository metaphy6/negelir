package middleware

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	aperrors "github.com/metaphy6/negelir/server/internal/errors"
)

func newSchemaVersionRouter(version int) *gin.Engine {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(SchemaVersionMiddleware(version))
	return r
}

// TestSchemaVersionMiddleware_JSONResponseGetsStamp verifies that a normal
// JSON response carries meta.schema_version.
func TestSchemaVersionMiddleware_JSONResponseGetsStamp(t *testing.T) {
	r := newSchemaVersionRouter(3)
	r.GET("/test", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"result": "ok"})
	})

	w := httptest.NewRecorder()
	r.ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/test", nil))

	if w.Code != http.StatusOK {
		t.Fatalf("want 200, got %d", w.Code)
	}
	var body map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
		t.Fatalf("invalid JSON: %v", err)
	}
	meta, ok := body["meta"].(map[string]any)
	if !ok {
		t.Fatalf("meta field absent or wrong type; body=%s", w.Body.String())
	}
	sv, ok := meta["schema_version"]
	if !ok {
		t.Fatalf("meta.schema_version absent; meta=%v", meta)
	}
	// json.Unmarshal decodes JSON numbers as float64 in map[string]any.
	if sv != float64(3) {
		t.Errorf("want schema_version=3, got %v", sv)
	}
}

// TestSchemaVersionMiddleware_ErrorResponseGetsStamp verifies that an
// application/problem+json error response also carries meta.schema_version.
func TestSchemaVersionMiddleware_ErrorResponseGetsStamp(t *testing.T) {
	r := newSchemaVersionRouter(1)
	r.GET("/error", func(c *gin.Context) {
		aperrors.Respond(c, aperrors.CodeNotFound, "not found")
	})

	w := httptest.NewRecorder()
	r.ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/error", nil))

	if w.Code != http.StatusNotFound {
		t.Fatalf("want 404, got %d", w.Code)
	}
	var body map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
		t.Fatalf("invalid JSON: %v", err)
	}
	meta, ok := body["meta"].(map[string]any)
	if !ok {
		t.Fatalf("meta absent in error body; body=%s", w.Body.String())
	}
	if meta["schema_version"] != float64(1) {
		t.Errorf("want schema_version=1, got %v", meta["schema_version"])
	}
}

// TestSchemaVersionMiddleware_ExistingMetaPreserved verifies that when the
// response already contains a meta object, schema_version is merged in and
// the existing meta fields are preserved.
func TestSchemaVersionMiddleware_ExistingMetaPreserved(t *testing.T) {
	r := newSchemaVersionRouter(2)
	r.GET("/with-meta", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{
			"result": "ok",
			"meta":   gin.H{"cursor": "abc123"},
		})
	})

	w := httptest.NewRecorder()
	r.ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/with-meta", nil))

	var body map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
		t.Fatalf("invalid JSON: %v", err)
	}
	meta, ok := body["meta"].(map[string]any)
	if !ok {
		t.Fatalf("meta absent; body=%s", w.Body.String())
	}
	if meta["cursor"] != "abc123" {
		t.Errorf("existing meta field 'cursor' lost; meta=%v", meta)
	}
	if meta["schema_version"] != float64(2) {
		t.Errorf("want schema_version=2, got %v", meta["schema_version"])
	}
}

// TestSchemaVersionMiddleware_NonJSONPassthrough verifies that non-JSON
// responses are written unchanged.
func TestSchemaVersionMiddleware_NonJSONPassthrough(t *testing.T) {
	r := newSchemaVersionRouter(1)
	r.GET("/text", func(c *gin.Context) {
		c.String(http.StatusOK, "hello")
	})

	w := httptest.NewRecorder()
	r.ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/text", nil))

	if w.Body.String() != "hello" {
		t.Errorf("non-JSON body modified; got %q", w.Body.String())
	}
}

// TestSchemaVersionMiddleware_StatusCodePreserved verifies that the HTTP
// status from the handler is preserved after body injection.
func TestSchemaVersionMiddleware_StatusCodePreserved(t *testing.T) {
	r := newSchemaVersionRouter(1)
	r.POST("/created", func(c *gin.Context) {
		c.JSON(http.StatusCreated, gin.H{"id": "xyz"})
	})

	w := httptest.NewRecorder()
	r.ServeHTTP(w, httptest.NewRequest(http.MethodPost, "/created", nil))

	if w.Code != http.StatusCreated {
		t.Errorf("want 201, got %d", w.Code)
	}
}

// TestSchemaVersionMiddleware_ExistingSchemaVersionUnchanged verifies that
// when meta.schema_version is already present, it is not overwritten.
func TestSchemaVersionMiddleware_ExistingSchemaVersionUnchanged(t *testing.T) {
	r := newSchemaVersionRouter(5)
	r.GET("/stamped", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{
			"x":    1,
			"meta": gin.H{"schema_version": 99},
		})
	})

	w := httptest.NewRecorder()
	r.ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/stamped", nil))

	var body map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
		t.Fatalf("invalid JSON: %v", err)
	}
	meta := body["meta"].(map[string]any)
	if meta["schema_version"] != float64(99) {
		t.Errorf("pre-existing schema_version was overwritten; got %v", meta["schema_version"])
	}
}

// TestInjectSchemaVersion_ArrayPassthrough verifies that JSON arrays return
// (nil, false) without error.
func TestInjectSchemaVersion_ArrayPassthrough(t *testing.T) {
	_, ok := injectSchemaVersion([]byte(`[1,2,3]`), 1)
	if ok {
		t.Error("expected false for JSON array input")
	}
}

// TestInjectSchemaVersion_InvalidJSONPassthrough verifies that invalid JSON
// returns (nil, false) without panic.
func TestInjectSchemaVersion_InvalidJSONPassthrough(t *testing.T) {
	_, ok := injectSchemaVersion([]byte(`not json`), 1)
	if ok {
		t.Error("expected false for invalid JSON input")
	}
}
