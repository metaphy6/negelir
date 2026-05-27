package middleware

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
)

// ── Test stubs ────────────────────────────────────────────────────────────

type stubTierQuotaCfg struct{ enabled bool }

func (s *stubTierQuotaCfg) TierEnforcementEnabled() bool { return s.enabled }

type stubTierStore struct {
	cap *int64
	err error
}

func (s *stubTierStore) DailyRequestCap(_ context.Context, _ int64) (*int64, error) {
	return s.cap, s.err
}

type stubTierQuotaCounter struct {
	nextVal   int64
	incrErr   error
	expireCalls int
}

func (s *stubTierQuotaCounter) Incr(_ context.Context, _ string) (int64, error) {
	return s.nextVal, s.incrErr
}
func (s *stubTierQuotaCounter) Expire(_ context.Context, _ string, _ time.Duration) error {
	s.expireCalls++
	return nil
}

// ── Helpers ───────────────────────────────────────────────────────────────

func cap64(n int64) *int64 { return &n }

func newTierQuotaRouter(cfg TierQuotaCfg, counter TierQuotaCounter, store TierStore, userID string, tierID int64) *gin.Engine {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	// Simulate the Authenticate middleware setting user_id and tier_id.
	r.Use(func(c *gin.Context) {
		if userID != "" {
			c.Set(ContextKeyUserID, userID)
			c.Set(ContextKeyTierID, tierID)
		}
	})
	r.Use(TierQuota(cfg, counter, store))
	r.GET("/v1/predictions", func(c *gin.Context) { c.Status(http.StatusOK) })
	return r
}

func doGet(r *gin.Engine, path string) *httptest.ResponseRecorder {
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, path, nil)
	r.ServeHTTP(w, req)
	return w
}

// ── Tests ─────────────────────────────────────────────────────────────────

// TestTierQuota_DormantByDefault verifies that when the enforcement flag is
// false the handler is invoked and the counter is never touched.
func TestTierQuota_DormantByDefault(t *testing.T) {
	counter := &stubTierQuotaCounter{nextVal: 0}
	store := &stubTierStore{cap: cap64(5)}
	cfg := &stubTierQuotaCfg{enabled: false}

	r := newTierQuotaRouter(cfg, counter, store, "user-uuid-001", 1)
	w := doGet(r, "/v1/predictions")

	if w.Code != http.StatusOK {
		t.Fatalf("dormant: expected 200, got %d", w.Code)
	}
	// Counter must NOT have been incremented when flag is off.
	if counter.nextVal != 0 {
		t.Fatalf("dormant: expected counter.nextVal unchanged (0), got %d", counter.nextVal)
	}
}

// TestTierQuota_ActiveNullCap_PassThrough verifies that a nil cap (unlimited
// tier) always lets requests through even when enforcement is enabled.
func TestTierQuota_ActiveNullCap_PassThrough(t *testing.T) {
	counter := &stubTierQuotaCounter{nextVal: 99}
	store := &stubTierStore{cap: nil} // nil = no cap
	cfg := &stubTierQuotaCfg{enabled: true}

	r := newTierQuotaRouter(cfg, counter, store, "user-uuid-002", 1)
	w := doGet(r, "/v1/predictions")

	if w.Code != http.StatusOK {
		t.Fatalf("null cap: expected 200, got %d", w.Code)
	}
}

// TestTierQuota_ActiveCapExceeded_Returns429EmptyBody verifies that when the
// counter after INCR exceeds the daily_request_cap the middleware responds
// with 429 and an empty body (consistent with the denylist pattern).
func TestTierQuota_ActiveCapExceeded_Returns429EmptyBody(t *testing.T) {
	counter := &stubTierQuotaCounter{nextVal: 11} // INCR returns 11; cap is 10
	store := &stubTierStore{cap: cap64(10)}
	cfg := &stubTierQuotaCfg{enabled: true}

	r := newTierQuotaRouter(cfg, counter, store, "user-uuid-003", 1)
	w := doGet(r, "/v1/predictions")

	if w.Code != http.StatusTooManyRequests {
		t.Fatalf("cap exceeded: expected 429, got %d", w.Code)
	}
	if body := w.Body.String(); body != "" {
		t.Fatalf("cap exceeded: expected empty body, got %q", body)
	}
}

// TestTierQuota_ActiveCapAtExactLimit_Allow verifies that a request whose
// counter equals the cap exactly is still allowed (cap is inclusive upper bound).
func TestTierQuota_ActiveCapAtExactLimit_Allow(t *testing.T) {
	counter := &stubTierQuotaCounter{nextVal: 10} // INCR returns 10; cap is 10
	store := &stubTierStore{cap: cap64(10)}
	cfg := &stubTierQuotaCfg{enabled: true}

	r := newTierQuotaRouter(cfg, counter, store, "user-uuid-004", 1)
	w := doGet(r, "/v1/predictions")

	if w.Code != http.StatusOK {
		t.Fatalf("at-cap: expected 200, got %d", w.Code)
	}
}

// TestTierQuota_ActiveNoUserID_FailOpen verifies that an unauthenticated
// request (no ContextKeyUserID in context) passes through without error.
func TestTierQuota_ActiveNoUserID_FailOpen(t *testing.T) {
	counter := &stubTierQuotaCounter{nextVal: 1}
	store := &stubTierStore{cap: cap64(5)}
	cfg := &stubTierQuotaCfg{enabled: true}

	// Pass empty userID so the router does not set context keys.
	r := newTierQuotaRouter(cfg, counter, store, "", 0)
	w := doGet(r, "/v1/predictions")

	if w.Code != http.StatusOK {
		t.Fatalf("no user_id: expected 200 (fail-open), got %d", w.Code)
	}
}

// TestTierQuota_RedisError_FailOpen verifies that a Redis INCR error causes
// the middleware to fail open rather than denying the request.
func TestTierQuota_RedisError_FailOpen(t *testing.T) {
	counter := &stubTierQuotaCounter{nextVal: 0, incrErr: context.DeadlineExceeded}
	store := &stubTierStore{cap: cap64(5)}
	cfg := &stubTierQuotaCfg{enabled: true}

	r := newTierQuotaRouter(cfg, counter, store, "user-uuid-005", 1)
	w := doGet(r, "/v1/predictions")

	if w.Code != http.StatusOK {
		t.Fatalf("redis error: expected 200 (fail-open), got %d", w.Code)
	}
}

// TestTierQuota_NewKey_SetsExpiry verifies that Expire is called exactly once
// when the counter returns 1 (new key), establishing the 26-hour TTL.
func TestTierQuota_NewKey_SetsExpiry(t *testing.T) {
	counter := &stubTierQuotaCounter{nextVal: 1} // first request of the day
	store := &stubTierStore{cap: cap64(100)}
	cfg := &stubTierQuotaCfg{enabled: true}

	r := newTierQuotaRouter(cfg, counter, store, "user-uuid-006", 1)
	_ = doGet(r, "/v1/predictions")

	if counter.expireCalls != 1 {
		t.Fatalf("new key: expected Expire called once, got %d", counter.expireCalls)
	}
}

// TestTierQuota_ExistingKey_NoExpireReset verifies that Expire is NOT called
// when the counter returns > 1 (existing key), preserving the original TTL.
func TestTierQuota_ExistingKey_NoExpireReset(t *testing.T) {
	counter := &stubTierQuotaCounter{nextVal: 5} // mid-day, not a new key
	store := &stubTierStore{cap: cap64(100)}
	cfg := &stubTierQuotaCfg{enabled: true}

	r := newTierQuotaRouter(cfg, counter, store, "user-uuid-007", 1)
	_ = doGet(r, "/v1/predictions")

	if counter.expireCalls != 0 {
		t.Fatalf("existing key: expected Expire not called, got %d", counter.expireCalls)
	}
}
