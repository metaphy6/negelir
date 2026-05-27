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

	"github.com/gin-gonic/gin"
)

// stubCacheGenStore is an in-memory CacheGenStore for unit tests.
type stubCacheGenStore struct {
	keys map[string]string
	err  error
}

var errCacheMiss = errors.New("redis: nil")

func (s *stubCacheGenStore) Get(_ context.Context, key string) (string, error) {
	if s.err != nil {
		return "", s.err
	}
	v, ok := s.keys[key]
	if !ok {
		return "", errCacheMiss
	}
	return v, nil
}

func newCacheGenRouter(store CacheGenStore) *gin.Engine {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(CacheGenCheck(store))
	r.GET("/v1/matches/:id", func(c *gin.Context) {
		c.String(http.StatusOK, "handler-response")
	})
	r.POST("/v1/qa", func(c *gin.Context) {
		c.Status(http.StatusAccepted)
	})
	return r
}

// TestCacheGenCheck_NonGET_Passthrough — POST bypasses cache (no X-Cache header).
func TestCacheGenCheck_NonGET_Passthrough(t *testing.T) {
	store := &stubCacheGenStore{keys: map[string]string{}}
	r := newCacheGenRouter(store)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/v1/qa", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusAccepted {
		t.Fatalf("POST: expected 202, got %d", w.Code)
	}
	if got := w.Header().Get("X-Cache"); got != "" {
		t.Fatalf("POST: X-Cache should be empty, got %q", got)
	}
}

// TestCacheGenCheck_NoGenKey_Bypass — GET with no gen counter -> X-Cache: bypass, handler runs.
func TestCacheGenCheck_NoGenKey_Bypass(t *testing.T) {
	store := &stubCacheGenStore{keys: map[string]string{}}
	r := newCacheGenRouter(store)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/v1/matches/123", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("no-gen bypass: expected 200 (handler), got %d", w.Code)
	}
	if got := w.Header().Get("X-Cache"); got != "bypass" {
		t.Fatalf("no-gen bypass: X-Cache expected bypass, got %q", got)
	}
	if !strings.Contains(w.Body.String(), "handler-response") {
		t.Fatalf("no-gen bypass: expected handler body, got %s", w.Body.String())
	}
}

// TestCacheGenCheck_StaleGen_Bypass — gen key present but entry missing for that gen -> bypass.
func TestCacheGenCheck_StaleGen_Bypass(t *testing.T) {
	k := "/v1/matches/456"
	genKey := CacheGenKeyFor(k)
	store := &stubCacheGenStore{keys: map[string]string{
		genKey: "7",
	}}
	r := newCacheGenRouter(store)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, k, nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("stale-gen bypass: expected 200 (handler), got %d", w.Code)
	}
	if got := w.Header().Get("X-Cache"); got != "bypass" {
		t.Fatalf("stale-gen bypass: X-Cache expected bypass, got %q", got)
	}
	if !strings.Contains(w.Body.String(), "handler-response") {
		t.Fatalf("stale-gen bypass: expected handler body, got %s", w.Body.String())
	}
}

// TestCacheGenCheck_Hit — gen key + matching entry -> X-Cache: hit, cached body returned, handler NOT called.
func TestCacheGenCheck_Hit(t *testing.T) {
	k := "/v1/matches/789"
	genKey := CacheGenKeyFor(k)
	entryKey := CacheEntryKeyFor(k, "3")
	store := &stubCacheGenStore{keys: map[string]string{
		genKey:   "3",
		entryKey: `{"cached":true}`,
	}}
	r := newCacheGenRouter(store)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, k, nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("cache hit: expected 200, got %d", w.Code)
	}
	if got := w.Header().Get("X-Cache"); got != "hit" {
		t.Fatalf("cache hit: X-Cache expected hit, got %q", got)
	}
	if !strings.Contains(w.Body.String(), `{"cached":true}`) {
		t.Fatalf("cache hit: expected cached body, got %s", w.Body.String())
	}
	if strings.Contains(w.Body.String(), "handler-response") {
		t.Fatal("cache hit: handler should NOT have been called")
	}
}

// TestCacheGenCheck_RedisError_FailOpen — Redis fault on gen read -> X-Cache: bypass, handler runs.
func TestCacheGenCheck_RedisError_FailOpen(t *testing.T) {
	store := &stubCacheGenStore{err: errors.New("redis: connection refused")}
	r := newCacheGenRouter(store)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/v1/matches/999", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("redis-fail-open: expected 200 (handler), got %d", w.Code)
	}
	if got := w.Header().Get("X-Cache"); got != "bypass" {
		t.Fatalf("redis-fail-open: X-Cache expected bypass, got %q", got)
	}
}

// TestCacheGenCheck_BoundaryNoMaintWrite — AST scan: cache_gen.go must not
// contain maint.event.v1 or sec.alert.v1 string literals.
func TestCacheGenCheck_BoundaryNoMaintWrite(t *testing.T) {
	root := repoRootFromCacheGen(t)
	path := filepath.Join(root, "server", "internal", "middleware", "cache_gen.go")
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
					"cache_gen.go contains %q; API must not write to maint plane",
					path, pos.Line, val)
			}
		}
		return true
	})
}

func repoRootFromCacheGen(t *testing.T) string {
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
