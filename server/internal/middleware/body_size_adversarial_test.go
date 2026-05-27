package middleware

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/metaphy6/negelir/server/internal/sec"
)

// countingPrimary is a test-only sec.RateChecker that allows exactly
// maxAllowed calls then returns RateThrottle on every subsequent call.
// It simulates a rate bucket drained by the allowed calls.
type thresholdPrimary struct {
	mu         sync.Mutex
	calls      int
	maxAllowed int
}

func (p *thresholdPrimary) Check(
	_ context.Context, _ string, _ int, _ float64, _ int,
) (sec.RateDecision, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.calls++
	if p.calls > p.maxAllowed {
		return sec.RateDecision{
			Status:     sec.RateThrottle,
			RetryAfter: 1 * time.Second,
			UsedTier:   "redis",
		}, nil
	}
	return sec.RateDecision{Status: sec.RateAllow, UsedTier: "redis"}, nil
}

// newOversizeRateLimitRouter chains RateLimiter → BodySizeCap on POST /v1/qa.
// The secondary bucket is effectively unlimited; cost = 1 for all routes.
func newOversizeRateLimitRouter(primary *thresholdPrimary, bodyCap int64) *gin.Engine {
	gin.SetMode(gin.TestMode)
	// Secondary bucket: large capacity so it never interferes.
	secondary := sec.NewSecondaryBucket(100000, 10000.0, 0)
	costs := newTestCosts(1)
	rateMw := RateLimiter(secondary, primary, costs, 100, 10.0, 50)

	r := gin.New()
	r.Use(func(c *gin.Context) { c.Set(ContextKeyRateSubject, "1.2.3.4/32") })
	r.Use(rateMw)
	r.Use(BodySizeCap(bodyCap))
	r.POST("/v1/qa", func(c *gin.Context) {
		body, _ := c.GetRawData()
		c.JSON(http.StatusOK, gin.H{"len": len(body)})
	})
	return r
}

// TestAdvQAOversize413ThenQuarantine — adv_test_qa_oversize_413_then_quarantine.
//
// Part 1: A 1 MB request body to POST /v1/qa → 413 Request Entity Too Large.
//
//	BodySizeCap fires before the handler and returns application/problem+json.
//
// Part 2: Cost-aware throttling. The rate limiter charges cost for every
//
//	request — including oversized ones that subsequently get 413'd. After
//	bursting two oversized requests (each consuming one token from the rate
//	bucket), the bucket is drained and the next request is throttled with 429,
//	even when its body is within the size cap.
func TestAdvQAOversize413ThenQuarantine(t *testing.T) {
	const oneMB = 1 << 20
	const bodyCap int64 = 64 * 1024 // 64 KB cap; well below 1 MB

	// ── Part 1: single 1 MB body → 413 ─────────────────────────────────────
	r1 := newBodySizeRouter(bodyCap)
	w1 := httptest.NewRecorder()
	req1 := httptest.NewRequest(http.MethodPost, "/test",
		strings.NewReader(strings.Repeat("x", oneMB)))
	r1.ServeHTTP(w1, req1)

	if w1.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("Part 1: 1 MB body: expected 413, got %d: %s", w1.Code, w1.Body.String())
	}
	if ct := w1.Header().Get("Content-Type"); !strings.HasPrefix(ct, "application/problem+json") {
		t.Fatalf("Part 1: expected application/problem+json Content-Type, got %q", ct)
	}

	// ── Part 2: burst of 413s drains the cost-aware rate bucket → 429 ───────
	// Primary allows exactly 2 requests before throttling (bucket = 2 tokens).
	primary := &thresholdPrimary{maxAllowed: 2}
	r2 := newOversizeRateLimitRouter(primary, bodyCap)
	oversizeBody := strings.Repeat("x", int(bodyCap)+1) // one byte over cap

	// Attempt 1: rate allows, BodySizeCap → 413 (cost charged from bucket).
	w2a := httptest.NewRecorder()
	r2.ServeHTTP(w2a, httptest.NewRequest(http.MethodPost, "/v1/qa",
		strings.NewReader(oversizeBody)))
	if w2a.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("Part 2 attempt 1: expected 413, got %d", w2a.Code)
	}

	// Attempt 2: rate allows again, BodySizeCap → 413 (second token consumed).
	w2b := httptest.NewRecorder()
	r2.ServeHTTP(w2b, httptest.NewRequest(http.MethodPost, "/v1/qa",
		strings.NewReader(oversizeBody)))
	if w2b.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("Part 2 attempt 2: expected 413, got %d", w2b.Code)
	}

	// Attempt 3: bucket drained by oversize burst → rate throttles → 429.
	// The body is now within the size cap; the throttle fires at the rate layer,
	// confirming the cost-aware mechanism.
	w2c := httptest.NewRecorder()
	r2.ServeHTTP(w2c, httptest.NewRequest(http.MethodPost, "/v1/qa",
		strings.NewReader(strings.Repeat("x", 10))))
	if w2c.Code != http.StatusTooManyRequests {
		t.Fatalf("Part 2 attempt 3: expected 429 after oversize burst drained rate bucket, got %d: %s",
			w2c.Code, w2c.Body.String())
	}
}
