package middleware

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
)

// buildDeprecationSpec produces a minimal OpenAPI YAML with the supplied
// extension values inserted into the GET /v1/old-route operation.
func buildDeprecationSpec(deprecatedOn, sunsetOn string) []byte {
	xDeprecated := ""
	if deprecatedOn != "" {
		xDeprecated = "\n      x-deprecated-on: " + deprecatedOn
	}
	xSunset := ""
	if sunsetOn != "" {
		xSunset = "\n      x-sunset-on: " + sunsetOn
	}
	return []byte(`openapi: "3.0.3"
info:
  title: Test
  version: "1.0.0"
paths:
  /v1/old-route:
    get:
      operationId: oldRoute
      x-rate-cost: 1
      x-tier-required: free
      x-idempotent-mutation: false` + xDeprecated + xSunset + `
      responses:
        "200":
          description: ok
  /v1/active-route:
    get:
      operationId: activeRoute
      x-rate-cost: 1
      x-tier-required: free
      x-idempotent-mutation: false
      responses:
        "200":
          description: ok
`)
}

func newDeprecationRouter(specYAML []byte, path string) *gin.Engine {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(DeprecationHeaders(specYAML, 90))
	r.GET(path, func(c *gin.Context) { c.Status(http.StatusOK) })
	return r
}

// TestDeprecationHeaders_NonDeprecatedRoute verifies that a route with no
// x-deprecated-on extension produces no Sunset or Link headers.
func TestDeprecationHeaders_NonDeprecatedRoute(t *testing.T) {
	spec := buildDeprecationSpec("", "") // no deprecation extensions
	r := newDeprecationRouter(spec, "/v1/active-route")
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/v1/active-route", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("want 200, got %d", w.Code)
	}
	if h := w.Header().Get("Sunset"); h != "" {
		t.Errorf("unexpected Sunset header on non-deprecated route: %q", h)
	}
	if h := w.Header().Get("Link"); h != "" {
		t.Errorf("unexpected Link header on non-deprecated route: %q", h)
	}
}

// TestDeprecationHeaders_DeprecatedBeforeSunset verifies that a deprecated
// route before its sunset date returns 200 with Sunset + Link headers.
func TestDeprecationHeaders_DeprecatedBeforeSunset(t *testing.T) {
	yesterday := time.Now().UTC().AddDate(0, 0, -1).Format("2006-01-02")
	future := time.Now().UTC().AddDate(0, 0, 180).Format("2006-01-02")
	spec := buildDeprecationSpec(yesterday, future)
	r := newDeprecationRouter(spec, "/v1/old-route")
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/v1/old-route", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("want 200, got %d", w.Code)
	}
	if h := w.Header().Get("Sunset"); h == "" {
		t.Error("expected Sunset header on deprecated route before sunset")
	}
	link := w.Header().Get("Link")
	if link == "" {
		t.Error("expected Link header on deprecated route before sunset")
	}
	if !strings.Contains(link, `rel="successor-version"`) {
		t.Errorf("Link header missing rel=successor-version: %q", link)
	}
	if !strings.Contains(link, "/v2/old-route") {
		t.Errorf("Link header should point to /v2/old-route, got: %q", link)
	}
}

// TestDeprecationHeaders_DeprecatedAfterSunset verifies that a deprecated
// route past its sunset date returns 410 Gone with a Link header.
func TestDeprecationHeaders_DeprecatedAfterSunset(t *testing.T) {
	longAgo := time.Now().UTC().AddDate(-1, 0, 0).Format("2006-01-02")
	pastSunset := time.Now().UTC().AddDate(0, 0, -1).Format("2006-01-02")
	spec := buildDeprecationSpec(longAgo, pastSunset)
	r := newDeprecationRouter(spec, "/v1/old-route")
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/v1/old-route", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusGone {
		t.Fatalf("want 410 Gone, got %d", w.Code)
	}
	link := w.Header().Get("Link")
	if link == "" {
		t.Error("expected Link header on past-sunset route")
	}
	if !strings.Contains(link, `rel="successor-version"`) {
		t.Errorf("Link header missing rel=successor-version: %q", link)
	}
}

// TestDeprecationHeaders_NoSpecDeprecation_PassThrough verifies that a spec
// with no x-deprecated-on annotations is a pure no-op on all routes.
func TestDeprecationHeaders_NoSpecDeprecation_PassThrough(t *testing.T) {
	spec := buildDeprecationSpec("", "")
	r := newDeprecationRouter(spec, "/v1/old-route")
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/v1/old-route", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("want 200, got %d", w.Code)
	}
}

// TestDeprecationHeaders_WindowFallback verifies that when x-sunset-on is
// absent, the sunset is computed as deprecatedOn + windowDays. Deprecating 10
// days ago with a 90-day window means sunset is 80 days from now, so the route
// should still return 200 with a Sunset header.
func TestDeprecationHeaders_WindowFallback(t *testing.T) {
	tenDaysAgo := time.Now().UTC().AddDate(0, 0, -10).Format("2006-01-02")
	spec := buildDeprecationSpec(tenDaysAgo, "") // no x-sunset-on
	r := newDeprecationRouter(spec, "/v1/old-route")
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/v1/old-route", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("want 200, got %d", w.Code)
	}
	if h := w.Header().Get("Sunset"); h == "" {
		t.Error("expected Sunset header when within deprecation window")
	}
}
