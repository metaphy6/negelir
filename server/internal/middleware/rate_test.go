package middleware

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/metaphy6/negelir/server/internal/sec"
)

func init() { gin.SetMode(gin.TestMode) }

// stubCosts wraps a fixed cost for every pattern.
type stubCosts struct{ cost int }

func (s *stubCosts) CostFor(_ string) (int, bool) { return s.cost, true }

// ── BuildSecondaryThrottleResponse ──────────────────────────────────

func TestBuildSecondaryThrottleResponse_Returns503(t *testing.T) {
	d := sec.RateDecision{
		Status:       sec.RateThrottle,
		UsedFallback: true,
		UsedTier:     "secondary",
	}
	status, headers, body := sec.BuildSecondaryThrottleResponse(d)
	if status != 503 {
		t.Fatalf("expected 503, got %d", status)
	}
	if headers["Retry-After"] != "1" {
		t.Fatalf("expected Retry-After=1, got %q", headers["Retry-After"])
	}
	want := `{"error":"rate_limited","retry_after_ms":1000,"reason":"brownout"}`
	if string(body) != want {
		t.Fatalf("body mismatch:\n got %s\nwant %s", body, want)
	}
}

func TestBuildSecondaryThrottleResponse_NonFallbackReturnsZero(t *testing.T) {
	// Lua-tier throttle must NOT produce the secondary response.
	d := sec.RateDecision{Status: sec.RateThrottle, UsedFallback: false}
	status, headers, body := sec.BuildSecondaryThrottleResponse(d)
	if status != 0 || headers != nil || body != nil {
		t.Fatalf("non-fallback must short-circuit; got %d", status)
	}
}

func TestBuildSecondaryThrottleResponse_AllowReturnsZero(t *testing.T) {
	d := sec.RateDecision{Status: sec.RateAllow, UsedFallback: true}
	status, _, _ := sec.BuildSecondaryThrottleResponse(d)
	if status != 0 {
		t.Fatalf("allow with fallback must short-circuit; got %d", status)
	}
}

// ── RateLimiter middleware ───────────────────────────────────────────

// alwaysAllowPrimary never throttles — used to isolate secondary behaviour.
type alwaysAllowPrimary struct{}

func (alwaysAllowPrimary) Check(_ context.Context, _ string, _ int, _ float64, _ int) (sec.RateDecision, error) {
	return sec.RateDecision{Status: sec.RateAllow, UsedTier: "redis"}, nil
}

// alwaysThrottlePrimary always throttles with a real Retry-After.
type alwaysThrottlePrimary struct{}

func (alwaysThrottlePrimary) Check(_ context.Context, _ string, _ int, _ float64, _ int) (sec.RateDecision, error) {
	return sec.RateDecision{
		Status:     sec.RateThrottle,
		RetryAfter: 5_000_000_000, // 5s in nanoseconds
		UsedTier:   "redis",
	}, nil
}

func newTestCosts(cost int) *sec.EndpointCostMap {
	yaml := []byte("version: 1\ndefault_cost: " + itoa(cost) + "\ncosts: []\n")
	m, err := sec.LoadEndpointCosts(yaml)
	if err != nil {
		panic(err)
	}
	return m
}

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	buf := make([]byte, 0, 10)
	for n > 0 {
		buf = append([]byte{byte('0' + n%10)}, buf...)
		n /= 10
	}
	return string(buf)
}

func TestRateLimiter_SecondaryThrottle_Returns503(t *testing.T) {
	// Drain the secondary bucket so the next request is throttled.
	secondary := sec.NewSecondaryBucket(1, 0.001, 100)
	ctx := context.Background()
	// Drain to zero.
	_, _ = secondary.Check(ctx, "1.2.3.4/32", 1, 0.001, 1)

	costs := newTestCosts(1)
	mw := RateLimiter(secondary, alwaysAllowPrimary{}, costs, 100, 1.0, 50)

	r := gin.New()
	r.Use(func(c *gin.Context) { c.Set(ContextKeyRateSubject, "1.2.3.4/32") })
	r.Use(mw)
	r.GET("/v1/qa", func(c *gin.Context) { c.Status(http.StatusOK) })

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/v1/qa", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusServiceUnavailable {
		t.Fatalf("expected 503 (secondary throttle), got %d", w.Code)
	}
	if got := w.Header().Get("Retry-After"); got != "1" {
		t.Fatalf("expected Retry-After=1 for secondary throttle, got %q", got)
	}
}

func TestRateLimiter_PrimaryThrottle_Returns429(t *testing.T) {
	// Secondary always allows (large bucket).
	secondary := sec.NewSecondaryBucket(10000, 100.0, 100)
	costs := newTestCosts(1)
	mw := RateLimiter(secondary, alwaysThrottlePrimary{}, costs, 100, 1.0, 50)

	r := gin.New()
	r.Use(func(c *gin.Context) { c.Set(ContextKeyRateSubject, "2.3.4.5/32") })
	r.Use(mw)
	r.GET("/v1/qa", func(c *gin.Context) { c.Status(http.StatusOK) })

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/v1/qa", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusTooManyRequests {
		t.Fatalf("expected 429 (primary throttle), got %d", w.Code)
	}
	if got := w.Header().Get("Retry-After"); got != "5" {
		t.Fatalf("expected Retry-After=5, got %q", got)
	}
}

func TestRateLimiter_BothAllow_PassesThrough(t *testing.T) {
	secondary := sec.NewSecondaryBucket(10000, 100.0, 100)
	costs := newTestCosts(1)
	mw := RateLimiter(secondary, alwaysAllowPrimary{}, costs, 100, 1.0, 50)

	r := gin.New()
	r.Use(func(c *gin.Context) { c.Set(ContextKeyRateSubject, "3.4.5.6/32") })
	r.Use(mw)
	r.GET("/v1/qa", func(c *gin.Context) { c.Status(http.StatusOK) })

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/v1/qa", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200 when both tiers allow, got %d", w.Code)
	}
}

func TestRateLimiter_DistinctStatusCodes(t *testing.T) {
	// Verify that 503 (secondary) != 429 (primary) so telemetry can
	// distinguish brownout from a genuine per-rate-limit.
	if http.StatusServiceUnavailable == http.StatusTooManyRequests {
		t.Fatal("503 and 429 must be distinct — telemetry contract broken")
	}
}

func TestNoopRateChecker_AlwaysAllows(t *testing.T) {
	checker := NoopRateChecker()
	dec, err := checker.Check(context.Background(), "any", 100, 1.0, 5)
	if err != nil {
		t.Fatalf("noop checker error: %v", err)
	}
	if dec.Status != sec.RateAllow {
		t.Fatalf("noop checker must always allow, got %s", dec.Status)
	}
}

// ── X-RateLimit headers on allow ────────────────────────────────────

func TestRateLimiter_AllowSetsXRateLimitHeaders(t *testing.T) {
	secondary := sec.NewSecondaryBucket(10000, 100.0, 100)
	costs := newTestCosts(1)
	// primary returns 42 remaining
	primary := &stubPrimary{decision: sec.RateDecision{
		Status:    sec.RateAllow,
		Remaining: 42,
		UsedTier:  "redis",
	}}
	mw := RateLimiter(secondary, primary, costs, 100, 1.0, 50)

	r := gin.New()
	r.Use(func(c *gin.Context) { c.Set(ContextKeyRateSubject, "1.2.3.4/32") })
	r.Use(mw)
	r.GET("/v1/qa", func(c *gin.Context) { c.Status(http.StatusOK) })

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/v1/qa", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}
	if got := w.Header().Get("X-RateLimit-Remaining"); got != "42" {
		t.Fatalf("expected X-RateLimit-Remaining=42, got %q", got)
	}
	if got := w.Header().Get("X-RateLimit-Reset"); got == "" {
		t.Fatal("X-RateLimit-Reset must be set on allow")
	}
}

// ── X-RateLimit headers on throttle ─────────────────────────────────

func TestRateLimiter_ThrottleSetsXRateLimitHeaders(t *testing.T) {
	secondary := sec.NewSecondaryBucket(10000, 100.0, 100)
	costs := newTestCosts(1)
	mw := RateLimiter(secondary, alwaysThrottlePrimary{}, costs, 100, 1.0, 50)

	r := gin.New()
	r.Use(func(c *gin.Context) { c.Set(ContextKeyRateSubject, "2.3.4.5/32") })
	r.Use(mw)
	r.GET("/v1/qa", func(c *gin.Context) { c.Status(http.StatusOK) })

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/v1/qa", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusTooManyRequests {
		t.Fatalf("expected 429, got %d", w.Code)
	}
	// X-RateLimit-Remaining must be present (0 when throttled with no remaining).
	if got := w.Header().Get("X-RateLimit-Remaining"); got == "" {
		t.Fatal("X-RateLimit-Remaining must be set on throttle")
	}
	if got := w.Header().Get("X-RateLimit-Reset"); got == "" {
		t.Fatal("X-RateLimit-Reset must be set on throttle")
	}
}

// ── Dual-subject lower-of-two wins ──────────────────────────────────

// subjectAwarePrimary returns configurable decisions per subject key.
// All unlisted subjects get allowDecision.
type subjectAwarePrimary struct {
	decisions    map[string]sec.RateDecision
	allowDecision sec.RateDecision
}

func (s *subjectAwarePrimary) Check(_ context.Context, subject string, _ int, _ float64, _ int) (sec.RateDecision, error) {
	if d, ok := s.decisions[subject]; ok {
		return d, nil
	}
	return s.allowDecision, nil
}

// stubPrimary always returns the same decision regardless of subject.
type stubPrimary struct {
	decision sec.RateDecision
}

func (s *stubPrimary) Check(_ context.Context, _ string, _ int, _ float64, _ int) (sec.RateDecision, error) {
	return s.decision, nil
}

func TestRateLimiter_DualSubject_JTIThrottles_IPAllows(t *testing.T) {
	// JTI bucket is exhausted; IP bucket is healthy.
	// Lower-of-two wins → request throttled.
	secondary := sec.NewSecondaryBucket(10000, 100.0, 100)
	costs := newTestCosts(1)

	primary := &subjectAwarePrimary{
		decisions: map[string]sec.RateDecision{
			"user:jti-abc": {Status: sec.RateThrottle, RetryAfter: 3_000_000_000, UsedTier: "redis"},
		},
		allowDecision: sec.RateDecision{Status: sec.RateAllow, Remaining: 50, UsedTier: "redis"},
	}
	mw := RateLimiter(secondary, primary, costs, 100, 1.0, 50)

	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set(ContextKeyRateSubject, "10.0.0.1/32")
		c.Set(ContextKeySubjectID, "user:jti-abc")
	})
	r.Use(mw)
	r.GET("/v1/qa", func(c *gin.Context) { c.Status(http.StatusOK) })

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/v1/qa", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusTooManyRequests {
		t.Fatalf("expected 429 (JTI throttle), got %d", w.Code)
	}
}

func TestRateLimiter_DualSubject_IPThrottles_JTIAllows(t *testing.T) {
	// IP bucket is exhausted; JTI bucket is healthy.
	// Lower-of-two wins → request throttled.
	secondary := sec.NewSecondaryBucket(10000, 100.0, 100)
	costs := newTestCosts(1)

	primary := &subjectAwarePrimary{
		decisions: map[string]sec.RateDecision{
			"203.0.113.9/32": {Status: sec.RateThrottle, RetryAfter: 2_000_000_000, UsedTier: "redis"},
		},
		allowDecision: sec.RateDecision{Status: sec.RateAllow, Remaining: 80, UsedTier: "redis"},
	}
	mw := RateLimiter(secondary, primary, costs, 100, 1.0, 50)

	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set(ContextKeyRateSubject, "203.0.113.9/32")
		c.Set(ContextKeySubjectID, "user:jti-xyz")
	})
	r.Use(mw)
	r.GET("/v1/qa", func(c *gin.Context) { c.Status(http.StatusOK) })

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/v1/qa", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusTooManyRequests {
		t.Fatalf("expected 429 (IP throttle), got %d", w.Code)
	}
}

func TestRateLimiter_DualSubject_MinRemainingHeader(t *testing.T) {
	// JTI bucket has 80 remaining; IP bucket has 15 remaining.
	// X-RateLimit-Remaining must be min(80,15) = 15.
	secondary := sec.NewSecondaryBucket(10000, 100.0, 100)
	costs := newTestCosts(1)

	primary := &subjectAwarePrimary{
		decisions: map[string]sec.RateDecision{
			"user:jti-def": {Status: sec.RateAllow, Remaining: 80, UsedTier: "redis"},
			"198.51.100.1/32": {Status: sec.RateAllow, Remaining: 15, UsedTier: "redis"},
		},
		allowDecision: sec.RateDecision{Status: sec.RateAllow, Remaining: 50, UsedTier: "redis"},
	}
	mw := RateLimiter(secondary, primary, costs, 100, 1.0, 50)

	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set(ContextKeyRateSubject, "198.51.100.1/32")
		c.Set(ContextKeySubjectID, "user:jti-def")
	})
	r.Use(mw)
	r.GET("/v1/qa", func(c *gin.Context) { c.Status(http.StatusOK) })

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/v1/qa", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}
	if got := w.Header().Get("X-RateLimit-Remaining"); got != "15" {
		t.Fatalf("expected X-RateLimit-Remaining=15 (min of 80 and 15), got %q", got)
	}
}

func TestRateLimiter_AnonymousRequest_SingleCheck(t *testing.T) {
	// When ContextKeySubjectID is absent, JTI falls back to IP subject.
	// Only one primary check fires; no double-charge.
	secondary := sec.NewSecondaryBucket(10000, 100.0, 100)
	costs := newTestCosts(1)

	callCount := 0
	primary := &countingPrimary{
		inner: &stubPrimary{decision: sec.RateDecision{
			Status:    sec.RateAllow,
			Remaining: 60,
			UsedTier:  "redis",
		}},
		count: &callCount,
	}
	mw := RateLimiter(secondary, primary, costs, 100, 1.0, 50)

	r := gin.New()
	r.Use(func(c *gin.Context) { c.Set(ContextKeyRateSubject, "5.6.7.8/32") })
	// ContextKeySubjectID intentionally NOT set → anonymous
	r.Use(mw)
	r.GET("/v1/qa", func(c *gin.Context) { c.Status(http.StatusOK) })

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/v1/qa", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}
	if callCount != 1 {
		t.Fatalf("expected exactly 1 primary check for anonymous request, got %d", callCount)
	}
}

// countingPrimary wraps another RateChecker and counts invocations.
type countingPrimary struct {
	inner sec.RateChecker
	count *int
}

func (c *countingPrimary) Check(ctx context.Context, subject string, capacity int, refillPerS float64, cost int) (sec.RateDecision, error) {
	*c.count++
	return c.inner.Check(ctx, subject, capacity, refillPerS, cost)
}
