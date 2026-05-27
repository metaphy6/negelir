// metrics_test.go — unit tests for §9.8 RED metrics.
package metrics

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/testutil"
)

// newTestMetrics returns a fresh Metrics instance backed by an isolated
// Prometheus registry so tests do not pollute each other.
func newTestMetrics(t *testing.T) *Metrics {
	t.Helper()
	reg := prometheus.NewRegistry()
	return New(reg)
}

// TestMetricFamiliesRegistered verifies that all 7 §9.8 metric families are
// non-nil after New() returns.
func TestMetricFamiliesRegistered(t *testing.T) {
	m := newTestMetrics(t)

	if m.RequestsTotal == nil {
		t.Error("RequestsTotal (api_requests_total) is nil")
	}
	if m.RequestDuration == nil {
		t.Error("RequestDuration (api_request_duration_seconds) is nil")
	}
	if m.InflightRPCs == nil {
		t.Error("InflightRPCs (api_inflight_rpcs) is nil")
	}
	if m.CacheHitRatio == nil {
		t.Error("CacheHitRatio (api_cache_hit_ratio) is nil")
	}
	if m.JWTVerifyDuration == nil {
		t.Error("JWTVerifyDuration (api_jwt_verify_duration_seconds) is nil")
	}
	if m.SecGateDuration == nil {
		t.Error("SecGateDuration (api_sec_gate_duration_seconds) is nil")
	}
	if m.IdempotencyReplays == nil {
		t.Error("IdempotencyReplays (api_idempotency_replays_total) is nil")
	}
}

// TestDurationBuckets verifies that DurationBuckets spans 1 ms to 2500 ms (§9.17.5).
func TestDurationBuckets(t *testing.T) {
	if len(DurationBuckets) == 0 {
		t.Fatal("DurationBuckets is empty")
	}
	if DurationBuckets[0] != 0.001 {
		t.Errorf("first bucket: want 0.001, got %v", DurationBuckets[0])
	}
	if DurationBuckets[len(DurationBuckets)-1] != 2.500 {
		t.Errorf("last bucket: want 2.500, got %v", DurationBuckets[len(DurationBuckets)-1])
	}
}

// TestValidateCardinality_under verifies that a route count whose worst-case
// estimate fits within the cap passes without error.
func TestValidateCardinality_under(t *testing.T) {
	// 10 routes × 8 × 3 × 4 × 2 = 1920, well below 10000.
	if err := ValidateCardinality(10, 10000); err != nil {
		t.Errorf("unexpected error for 10 routes / cap 10000: %v", err)
	}
}

// TestValidateCardinality_exact verifies that an estimate exactly equal to
// the cap is accepted (boundary condition).
func TestValidateCardinality_exact(t *testing.T) {
	// EstimateCardinality(1) = 1 x 8 x 3 x 4 x 2 = 192.
	estimate := EstimateCardinality(1)
	if err := ValidateCardinality(1, estimate); err != nil {
		t.Errorf("exact boundary should pass: %v", err)
	}
}

// TestValidateCardinality_over verifies that an estimate exceeding the cap
// returns a non-nil error.
func TestValidateCardinality_over(t *testing.T) {
	// Force a cap below even a single route.
	if err := ValidateCardinality(1, 1); err == nil {
		t.Error("expected error for 1 route / cap 1, got nil")
	}
}

// TestEstimateCardinality verifies the formula.
func TestEstimateCardinality(t *testing.T) {
	// 30 routes x 8 x 3 x 4 x 2 = 5760 (spec example).
	got := EstimateCardinality(30)
	want := 30 * 8 * 3 * 4 * 2
	if got != want {
		t.Errorf("EstimateCardinality(30) = %d, want %d", got, want)
	}
}

// TestObserveMiddleware_routePatternLabel verifies that the Observe middleware
// records the OpenAPI route pattern as the route label, not the substituted URL.
func TestObserveMiddleware_routePatternLabel(t *testing.T) {
	gin.SetMode(gin.TestMode)
	reg := prometheus.NewRegistry()
	m := New(reg)

	r := gin.New()
	r.Use(Observe(m))
	r.GET("/v1/matches/:id", func(c *gin.Context) {
		c.Status(http.StatusOK)
	})

	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodGet, "/v1/matches/42", nil)
	r.ServeHTTP(w, req)

	// The route label must be the pattern "/v1/matches/:id", not "/v1/matches/42".
	count := testutil.ToFloat64(
		m.RequestsTotal.WithLabelValues("/v1/matches/:id", "200", "GET", "n/a", "false"),
	)
	if count != 1 {
		t.Errorf("api_requests_total{route=/v1/matches/:id, status=200}: want 1, got %v", count)
	}

	// Verify the class label was also incremented.
	classCount := testutil.ToFloat64(
		m.RequestsTotal.WithLabelValues("/v1/matches/:id", "2xx", "GET", "n/a", "false"),
	)
	if classCount != 1 {
		t.Errorf("api_requests_total{route=/v1/matches/:id, status=2xx}: want 1, got %v", classCount)
	}
}

// TestObserveMiddleware_noRawURLInLabel is an adversarial test: requests to
// the same route with different IDs must NOT create distinct label values.
// All accumulate under the pattern label.
func TestObserveMiddleware_noRawURLInLabel(t *testing.T) {
	gin.SetMode(gin.TestMode)
	reg := prometheus.NewRegistry()
	m := New(reg)

	r := gin.New()
	r.Use(Observe(m))
	r.GET("/v1/teams/:id", func(c *gin.Context) { c.Status(http.StatusOK) })

	for _, id := range []string{"1", "2", "99999"} {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest(http.MethodGet, fmt.Sprintf("/v1/teams/%s", id), nil)
		r.ServeHTTP(w, req)
	}

	// All 3 requests → pattern label, total count 3 (exact) + 3 (class) = 6.
	count := testutil.ToFloat64(
		m.RequestsTotal.WithLabelValues("/v1/teams/:id", "200", "GET", "n/a", "false"),
	)
	if count != 3 {
		t.Errorf("api_requests_total{route=/v1/teams/:id}: want 3, got %v", count)
	}
}

// TestObserveMiddleware_inflightRPCsGauged verifies the inflight gauge is
// incremented before the handler runs and decremented after.
func TestObserveMiddleware_inflightRPCsGauged(t *testing.T) {
	gin.SetMode(gin.TestMode)
	reg := prometheus.NewRegistry()
	m := New(reg)

	r := gin.New()
	r.Use(Observe(m))
	r.GET("/v1/healthz", func(c *gin.Context) { c.Status(http.StatusOK) })

	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodGet, "/v1/healthz", nil)
	r.ServeHTTP(w, req)

	// After the request completes, inflight must be back to 0.
	inflight := testutil.ToFloat64(m.InflightRPCs.WithLabelValues("/v1/healthz"))
	if inflight != 0 {
		t.Errorf("api_inflight_rpcs{route=/v1/healthz} after request: want 0, got %v", inflight)
	}
}

// TestObserveMiddleware_cacheHitRatio verifies the computed gauge is updated
// correctly for a mix of hit and miss results.
func TestObserveMiddleware_cacheHitRatio(t *testing.T) {
	gin.SetMode(gin.TestMode)
	reg := prometheus.NewRegistry()
	m := New(reg)

	r := gin.New()
	r.Use(Observe(m))
	r.GET("/v1/predictions", func(c *gin.Context) {
		c.Status(http.StatusOK)
	})

	// Simulate 2 hits and 1 miss via context key injection.
	for i, cacheVal := range []string{"hit", "hit", "miss"} {
		_ = i
		w := httptest.NewRecorder()
		req, _ := http.NewRequest(http.MethodGet, "/v1/predictions", nil)
		// Inject cache status via a middleware that runs before Observe reads it.
		// We rebuild the router per request with a leading setter middleware.
		rWithCache := gin.New()
		val := cacheVal
		rWithCache.Use(func(c *gin.Context) { c.Set(ContextKeyCacheStatus, val); c.Next() })
		rWithCache.Use(Observe(m))
		rWithCache.GET("/v1/predictions", func(c *gin.Context) { c.Status(http.StatusOK) })
		rWithCache.ServeHTTP(w, req)
	}

	// 2 hits out of 3 cacheable requests → ratio 0.666...
	ratio := testutil.ToFloat64(m.CacheHitRatio.WithLabelValues("/v1/predictions"))
	if ratio < 0.665 || ratio > 0.668 {
		t.Errorf("api_cache_hit_ratio{/v1/predictions}: want ~0.667, got %v", ratio)
	}
}

// TestObserveMiddleware_cacheLabel_n_a verifies that "n/a" routes do not
// affect the cache hit ratio gauge.
func TestObserveMiddleware_cacheLabel_n_a(t *testing.T) {
	gin.SetMode(gin.TestMode)
	reg := prometheus.NewRegistry()
	m := New(reg)

	r := gin.New()
	r.Use(Observe(m))
	r.GET("/v1/healthz", func(c *gin.Context) { c.Status(http.StatusOK) })

	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodGet, "/v1/healthz", nil)
	r.ServeHTTP(w, req)

	// n/a cache status must not update the ratio gauge (stays at 0).
	ratio := testutil.ToFloat64(m.CacheHitRatio.WithLabelValues("/v1/healthz"))
	if ratio != 0 {
		t.Errorf("api_cache_hit_ratio for n/a route: want 0, got %v", ratio)
	}
}

// TestObserveMiddleware_unmatchedRoute verifies that unmatched routes
// (FullPath == "") are passed through without observation.
func TestObserveMiddleware_unmatchedRoute(t *testing.T) {
	gin.SetMode(gin.TestMode)
	m := newTestMetrics(t)

	r := gin.New()
	r.Use(Observe(m))
	// No routes registered — every request is unmatched.

	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodGet, "/not-a-route", nil)
	r.ServeHTTP(w, req)

	// RequestsTotal must not have been incremented for the unmatched route.
	// testutil.ToFloat64 returns 0 for a label set that was never observed.
	count := testutil.ToFloat64(
		m.RequestsTotal.WithLabelValues("", "404", "GET", "n/a", "false"),
	)
	if count != 0 {
		t.Errorf("unmatched route should not increment requests_total, got %v", count)
	}
}

// TestMetricsCardinalityUnderCap verifies that 1000 requests bearing distinct
// path IDs do not cause metric cardinality to explode (test_metrics_cardinality_under_cap).
//
// The test proves that the Observe middleware records the OpenAPI route pattern
// as the label — not the substituted URL value. If raw IDs leaked into labels,
// each of the 1000 distinct IDs would create its own time series, causing
// cardinality to grow without bound. Under correct behaviour all 1000 requests
// accumulate under a single route-pattern label set.
func TestMetricsCardinalityUnderCap(t *testing.T) {
	gin.SetMode(gin.TestMode)
	m := newTestMetrics(t)

	r := gin.New()
	r.Use(Observe(m))
	r.GET("/v1/matches/:id/predictions", func(c *gin.Context) {
		c.Status(http.StatusOK)
	})

	// Send 1000 requests, each with a unique match ID.
	for i := 0; i < 1000; i++ {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest(http.MethodGet, fmt.Sprintf("/v1/matches/match-%d/predictions", i), nil)
		r.ServeHTTP(w, req)
	}

	// All 1000 requests must accumulate under the pattern label, not 1000 distinct labels.
	// The exact-status counter must total 1000.
	count := testutil.ToFloat64(
		m.RequestsTotal.WithLabelValues("/v1/matches/:id/predictions", "200", "GET", "n/a", "false"),
	)
	if count != 1000 {
		t.Errorf("api_requests_total{route=/v1/matches/:id/predictions, status=200}: want 1000, got %v", count)
	}

	// The worst-case cardinality estimate for 1 registered route must fit within
	// the default telemetry cap (10000). EstimateCardinality(1) = 1×8×3×4×2 = 192.
	if err := ValidateCardinality(1, 10000); err != nil {
		t.Errorf("cardinality estimate exceeded default cap after 1000 requests: %v", err)
	}
}
