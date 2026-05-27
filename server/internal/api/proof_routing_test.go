package api_test

// §9.14 Proof tests — Routing & contract (Go, deterministic)
//
// Tests covered in this file:
//   TestRouteTableMatchesOpenAPI       — test_route_table_matches_openapi
//   TestEndpointCostsTotal             — test_endpoint_costs_total
//   TestResponseProblemJSONOnErrors    — test_response_problem_json_on_errors
//   TestPaginationCursorTampering      — test_pagination_cursor_tampering
//   TestPaginationCursorFilterDrift    — test_pagination_cursor_filter_drift
//   TestPaginationCursorPostRotation   — test_pagination_cursor_post_rotation

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"gopkg.in/yaml.v3"

	"github.com/metaphy6/negelir/server/internal/cursor"
	aperrors "github.com/metaphy6/negelir/server/internal/errors"
	"github.com/metaphy6/negelir/server/internal/sec"
)

// openAPIParam converts OpenAPI path template params to Gin-style params.
// "/v1/matches/{id}/predictions" → "/v1/matches/:id/predictions"
var reOpenAPIParam = regexp.MustCompile(`\{([^}]+)\}`)

func openAPIToGin(path string) string {
	return reOpenAPIParam.ReplaceAllString(path, `:$1`)
}

// buildProofRouter returns a gin.Engine with all routes registered exactly as
// cmd/api/main.go does. Any route added to main.go must also be added here,
// and vice-versa — that is precisely the contract TestRouteTableMatchesOpenAPI
// enforces.
func buildProofRouter() *gin.Engine {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	stub := func(c *gin.Context) { c.Status(http.StatusOK) }

	api := r.Group("/api/v1")
	api.GET("/health", stub)
	api.GET("/matches", stub)
	api.GET("/matches/:id", stub)
	api.GET("/teams", stub)
	api.GET("/teams/:id", stub)
	api.POST("/scrape/trigger", stub)
	api.GET("/features/:match_id", stub)

	v1 := r.Group("/v1")
	v1.GET("/healthz", stub)
	v1.GET("/readyz", stub)
	v1.POST("/qa", stub)
	v1.POST("/auth/login", stub)
	v1.POST("/auth/register", stub)
	v1.GET("/matches/:id/predictions", stub)
	// §9.14 stub routes (registered in main.go; deferred implementation):
	v1.GET("/matches/:id", stub)
	v1.GET("/leagues", stub)
	v1.GET("/leagues/:id/fixtures", stub)
	v1.GET("/me", stub)
	v1.POST("/auth/refresh", stub)

	return r
}

// rawOpenAPI is a minimal envelope for parsing openapi.yaml paths.
type rawOpenAPI struct {
	Paths map[string]map[string]interface{} `yaml:"paths"`
}

// loadOpenAPIPaths parses the server/api/openapi.yaml file and returns a map
// of (method+path) keys representing all declared operations.
// Key format: "GET /v1/matches/:id"
func loadOpenAPIPaths(t *testing.T) map[string]struct{} {
	t.Helper()
	root := repoRoot(t)
	data, err := os.ReadFile(filepath.Join(root, "server", "api", "openapi.yaml"))
	if err != nil {
		t.Fatalf("read openapi.yaml: %v", err)
	}
	var spec rawOpenAPI
	if err := yaml.Unmarshal(data, &spec); err != nil {
		t.Fatalf("parse openapi.yaml: %v", err)
	}

	httpMethods := map[string]bool{
		"get": true, "post": true, "put": true, "patch": true,
		"delete": true, "head": true, "options": true,
	}

	out := make(map[string]struct{})
	for rawPath, ops := range spec.Paths {
		ginPath := openAPIToGin(rawPath)
		for method := range ops {
			if !httpMethods[strings.ToLower(method)] {
				continue // skip x-* extensions, parameters, etc.
			}
			key := fmt.Sprintf("%s %s", strings.ToUpper(method), ginPath)
			out[key] = struct{}{}
		}
	}
	return out
}

// ─── §9.14 test_route_table_matches_openapi ──────────────────────────────────

// TestRouteTableMatchesOpenAPI asserts that every gin route registered in the
// server appears in openapi.yaml and vice-versa (cardinality match).
//
// If a route is missing from main.go stub router → test fails; if a route is
// missing from openapi.yaml → test fails.
func TestRouteTableMatchesOpenAPI(t *testing.T) {
	r := buildProofRouter()

	// Build gin route key set: "METHOD /path"
	ginRoutes := make(map[string]struct{})
	for _, ri := range r.Routes() {
		ginRoutes[ri.Method+" "+ri.Path] = struct{}{}
	}

	openAPIRoutes := loadOpenAPIPaths(t)

	// Every gin route must be in openapi.yaml.
	var notInOpenAPI []string
	for k := range ginRoutes {
		if _, ok := openAPIRoutes[k]; !ok {
			notInOpenAPI = append(notInOpenAPI, k)
		}
	}
	if len(notInOpenAPI) > 0 {
		t.Errorf("gin routes missing from openapi.yaml:\n  %s", strings.Join(notInOpenAPI, "\n  "))
	}

	// Every openapi.yaml operation must be in gin router.
	var notInGin []string
	for k := range openAPIRoutes {
		if _, ok := ginRoutes[k]; !ok {
			notInGin = append(notInGin, k)
		}
	}
	if len(notInGin) > 0 {
		t.Errorf("openapi.yaml operations missing from gin router:\n  %s", strings.Join(notInGin, "\n  "))
	}

	// Cardinality check: both sets must be the same size.
	if len(ginRoutes) != len(openAPIRoutes) {
		t.Errorf("cardinality mismatch: gin=%d openapi=%d", len(ginRoutes), len(openAPIRoutes))
	}
}

// ─── §9.14 test_endpoint_costs_total ─────────────────────────────────────────

// TestEndpointCostsTotal asserts that every gin route has an explicit cost
// entry in endpoint_costs.yaml (allowFallback=nil → empty result required).
func TestEndpointCostsTotal(t *testing.T) {
	r := buildProofRouter()

	patterns := make([]string, 0, len(r.Routes()))
	for _, ri := range r.Routes() {
		patterns = append(patterns, ri.Path)
	}

	costMap, err := sec.LoadEndpointCosts(sec.EmbeddedEndpointCostsYAML)
	if err != nil {
		t.Fatalf("LoadEndpointCosts: %v", err)
	}

	missing := costMap.CheckTotality(patterns, nil)
	if len(missing) > 0 {
		t.Errorf("routes with no explicit cost entry (allowFallback=nil):\n  %s",
			strings.Join(missing, "\n  "))
	}
}

// ─── §9.14 test_response_problem_json_on_errors ───────────────────────────────

// TestResponseProblemJSONOnErrors asserts that every 4xx/5xx error response
// carries Content-Type: application/problem+json with the required RFC 7807
// fields {type, title, status, detail, request_id (instance)}.
func TestResponseProblemJSONOnErrors(t *testing.T) {
	gin.SetMode(gin.TestMode)

	// Build a router where each path fires one specific error code.
	errorCodes := []aperrors.Code{
		aperrors.CodeInvalidRequest,
		aperrors.CodeInvalidCursor,
		aperrors.CodeUnauthenticated,
		aperrors.CodeForbidden,
		aperrors.CodeNotFound,
		aperrors.CodeRateLimited,
		aperrors.CodePayloadTooLarge,
		aperrors.CodeUnprocessable,
		aperrors.CodeQAQuarantined,
		aperrors.CodeInternal,
		aperrors.CodeServiceUnavailable,
	}

	r := gin.New()
	// RequestID middleware so `instance` is populated.
	r.Use(func(c *gin.Context) {
		c.Set("request_id", "test-req-id")
		c.Next()
	})
	for i, code := range errorCodes {
		code := code // capture
		r.GET(fmt.Sprintf("/probe/%d", i), func(c *gin.Context) {
			aperrors.Respond(c, code, "proof test detail")
		})
	}

	for i, code := range errorCodes {
		t.Run(string(code), func(t *testing.T) {
			req := httptest.NewRequest(http.MethodGet, fmt.Sprintf("/probe/%d", i), nil)
			w := httptest.NewRecorder()
			r.ServeHTTP(w, req)

			ct := w.Header().Get("Content-Type")
			if !strings.HasPrefix(ct, "application/problem+json") {
				t.Errorf("Content-Type: want application/problem+json, got %q", ct)
			}

			status := w.Code
			if status < 400 {
				t.Errorf("want 4xx/5xx, got %d", status)
			}

			var p struct {
				Type     string `json:"type"`
				Title    string `json:"title"`
				Status   int    `json:"status"`
				Detail   string `json:"detail"`
				Instance string `json:"instance"`
			}
			if err := json.NewDecoder(w.Body).Decode(&p); err != nil {
				t.Fatalf("decode problem body: %v", err)
			}
			if p.Type == "" {
				t.Error("problem.type must be non-empty")
			}
			if p.Title == "" {
				t.Error("problem.title must be non-empty")
			}
			if p.Status != status {
				t.Errorf("problem.status=%d, want %d", p.Status, status)
			}
			if p.Detail == "" {
				t.Error("problem.detail must be non-empty")
			}
			if p.Instance == "" {
				t.Error("problem.instance (request_id) must be non-empty")
			}
		})
	}
}

// ─── §9.14 cursor proof tests (HTTP-level) ───────────────────────────────────

var proofCursorKey = []byte("proof-cursor-seal-test-key32byte")

// cursorUnsealRouter builds a minimal gin handler that unseal the cursor from
// X-Cursor, uses X-Filter as the filter hash, and maps errors to HTTP codes:
//
//	ErrInvalidCursor → 400
//	ErrFilterDrift   → 409
//	success          → 200
func cursorUnsealRouter() *gin.Engine {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.GET("/page", func(c *gin.Context) {
		encoded := c.GetHeader("X-Cursor")
		filter := c.GetHeader("X-Filter")
		_, err := cursor.Unseal(proofCursorKey, encoded, time.Now().Unix(), filter)
		if err != nil {
			switch {
			case isFilterDrift(err):
				aperrors.Respond(c, aperrors.CodeCursorFilterDrift, err.Error())
			default:
				aperrors.Respond(c, aperrors.CodeInvalidCursor, err.Error())
			}
			return
		}
		c.Status(http.StatusOK)
	})
	return r
}

// isFilterDrift checks the error chain for ErrFilterDrift without using
// errors.Is directly on cursor's unexported sentinel.
func isFilterDrift(err error) bool {
	return err != nil && strings.Contains(err.Error(), "filter") &&
		!strings.Contains(err.Error(), "tampered") &&
		!strings.Contains(err.Error(), "expired")
}

// TestPaginationCursorTampering — §9.14: flip every byte position; assert 400 (no panic).
func TestPaginationCursorTampering(t *testing.T) {
	r := cursorUnsealRouter()
	payload := cursor.Payload{
		Table:           "matches",
		LastPK:          "10",
		QueryFilterHash: "abc",
		ExpiresAtUnix:   time.Now().Add(time.Hour).Unix(),
	}
	encoded, err := cursor.Seal(proofCursorKey, payload)
	if err != nil {
		t.Fatalf("Seal: %v", err)
	}

	raw, _ := base64.RawURLEncoding.DecodeString(encoded)
	for i := 0; i < len(raw); i++ {
		mangled := make([]byte, len(raw))
		copy(mangled, raw)
		mangled[i] ^= 0xFF
		bad := base64.RawURLEncoding.EncodeToString(mangled)

		req := httptest.NewRequest(http.MethodGet, "/page", nil)
		req.Header.Set("X-Cursor", bad)
		req.Header.Set("X-Filter", payload.QueryFilterHash)
		w := httptest.NewRecorder()

		// Must not panic; use a deferred recover to catch panics explicitly.
		func() {
			defer func() {
				if rec := recover(); rec != nil {
					t.Errorf("byte[%d]: handler panicked: %v", i, rec)
				}
			}()
			r.ServeHTTP(w, req)
		}()

		if w.Code != http.StatusBadRequest {
			t.Errorf("byte[%d] tampered: want 400, got %d", i, w.Code)
		}
	}
}

// TestPaginationCursorFilterDrift — §9.14: mint with filter=A, request with filter=B; assert 409.
func TestPaginationCursorFilterDrift(t *testing.T) {
	r := cursorUnsealRouter()
	payload := cursor.Payload{
		Table:           "matches",
		LastPK:          "10",
		QueryFilterHash: "filter-A",
		ExpiresAtUnix:   time.Now().Add(time.Hour).Unix(),
	}
	encoded, err := cursor.Seal(proofCursorKey, payload)
	if err != nil {
		t.Fatalf("Seal: %v", err)
	}

	req := httptest.NewRequest(http.MethodGet, "/page", nil)
	req.Header.Set("X-Cursor", encoded)
	req.Header.Set("X-Filter", "filter-B") // different filter
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code != http.StatusConflict {
		t.Fatalf("filter drift: want 409, got %d; body: %s", w.Code, w.Body.String())
	}
}

// TestPaginationCursorPostRotation — §9.14: cursor sealed with old key → 400 graceful.
func TestPaginationCursorPostRotation(t *testing.T) {
	r := cursorUnsealRouter()
	oldKey := []byte("old-proof-cursor-seal-key32bytes")
	payload := cursor.Payload{
		Table:           "matches",
		LastPK:          "20",
		QueryFilterHash: "abc",
		ExpiresAtUnix:   time.Now().Add(time.Hour).Unix(),
	}
	encoded, err := cursor.Seal(oldKey, payload)
	if err != nil {
		t.Fatalf("Seal with old key: %v", err)
	}

	req := httptest.NewRequest(http.MethodGet, "/page", nil)
	req.Header.Set("X-Cursor", encoded)
	req.Header.Set("X-Filter", payload.QueryFilterHash)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("post-rotation cursor: want 400, got %d; body: %s", w.Code, w.Body.String())
	}
}
