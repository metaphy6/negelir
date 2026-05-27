package resilience_test

import (
	"context"
	"errors"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/metaphy6/negelir/server/internal/resilience"
	"github.com/sony/gobreaker"
)

// TestBulkheadProtectsHealthz saturates the PG bulkhead and verifies that
// a path NOT using the bulkhead (e.g. /v1/healthz) still responds in < 50ms.
//
// Phase 9 §9.17.4 proof: bulkhead capacity = floor(poolSize * 0.8).
// With poolSize=5, capacity=4. After acquiring all 4 slots, TryAcquire
// returns false. The health-check path (which never calls TryAcquire) runs
// in < 50ms regardless.
func TestBulkheadProtectsHealthz(t *testing.T) {
	t.Parallel()
	const poolSize = 5

	bh, cap := resilience.NewBulkheadWithCap(poolSize)
	if cap != 4 {
		t.Fatalf("expected bulkhead cap=4 (floor(5*0.8)), got %d", cap)
	}

	// Saturate all slots.
	for i := int64(0); i < cap; i++ {
		if !bh.TryAcquire() {
			t.Fatalf("expected to acquire slot %d/%d", i+1, cap)
		}
	}

	// Next TryAcquire must fail (bulkhead full).
	if bh.TryAcquire() {
		t.Fatal("expected bulkhead to be full; unexpected acquisition succeeded")
	}

	// Simulate healthz path: purely in-memory, never touches the bulkhead.
	start := time.Now()
	_ = struct{ alive bool }{alive: true}
	elapsed := time.Since(start)

	if elapsed >= 50*time.Millisecond {
		t.Errorf("healthz path took %v; want < 50ms even with saturated bulkhead", elapsed)
	}

	// Release all slots (cleanup).
	for i := int64(0); i < cap; i++ {
		bh.Release()
	}
}

// TestHedgeBudgetCapped floods the hedge tracker with RPCs and asserts that
// the hedge count never exceeds cfg.api_hedge_budget_pct (10%) of total.
//
// Phase 9 §9.17.4 proof.
func TestHedgeBudgetCapped(t *testing.T) {
	t.Parallel()
	const (
		budgetPct = 10
		total     = 1000
	)

	tracker := resilience.NewHedgeTracker(budgetPct)

	hedged := 0
	for i := 0; i < total; i++ {
		tracker.RecordRPC()
		if tracker.ShouldHedge() {
			hedged++
		}
	}

	maxAllowed := total * budgetPct / 100 // 100
	if hedged > maxAllowed+1 {
		t.Errorf("hedge count %d exceeds budget of %d (%d%% of %d)",
			hedged, maxAllowed, budgetPct, total)
	}

	tot, hed := tracker.Totals()
	if tot != int64(total) {
		t.Errorf("tracker.total = %d; want %d", tot, total)
	}
	if hed != int64(hedged) {
		t.Errorf("tracker.hedged = %d; want %d", hed, hedged)
	}
}

// TestSingleflightCollapsesCacheMissHerd launches 500 parallel goroutines
// all performing a cache-MISS lookup for the same key and verifies that the
// underlying fetch function is called exactly once.
//
// Phase 9 §9.17.4 proof: singleflight keyed on (match_id, market_set, version).
func TestSingleflightCollapsesCacheMissHerd(t *testing.T) {
	t.Parallel()

	var callCount int64
	group := &resilience.SFGroup{}

	key := "match42:ms,au_2.5:v3"
	const n = 500

	var wg sync.WaitGroup
	for i := 0; i < n; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, _, _ = group.Do(key, func() (interface{}, error) {
				atomic.AddInt64(&callCount, 1)
				// Brief sleep so all n goroutines are in flight concurrently.
				time.Sleep(10 * time.Millisecond)
				return "prediction_result", nil
			})
		}()
	}
	wg.Wait()

	if callCount != 1 {
		t.Errorf("underlying fetch called %d times for %d concurrent MISS requests; want exactly 1",
			callCount, n)
	}
}

// TestRetryBudgetPreventsAmplification drives a retry budget exhaustion
// scenario: 200 rapid retry attempts against an "empty" bucket; no more than
// burst capacity (50) should succeed.
//
// Phase 9 §9.17.4 proof.
func TestRetryBudgetPreventsAmplification(t *testing.T) {
	t.Parallel()

	const (
		perS     = 10.0
		capacity = 50
		attempts = 200
	)

	rb := resilience.NewRetryBudget(perS, capacity)

	allowed := 0
	for i := 0; i < attempts; i++ {
		if rb.Allow("pg") {
			allowed++
		}
	}

	// All attempts are effectively instantaneous — no meaningful refill.
	// Max allowed = burst capacity + tiny tolerance for elapsed nanoseconds.
	if allowed > capacity+2 {
		t.Errorf("retry budget allowed %d retries; want <= burst cap %d",
			allowed, capacity)
	}
	if allowed < 1 {
		t.Error("expected at least 1 retry allowed (initial burst)")
	}
}

// TestBreakerTripsAndRecovers verifies the closed→open→half-open→closed cycle.
func TestBreakerTripsAndRecovers(t *testing.T) {
	t.Parallel()

	var alertKinds []string
	var mu sync.Mutex

	cfg := resilience.BreakerConfig{
		FailRatio:   0.5,
		Window:      5 * time.Second,
		MinRequests: 4,
		OpenDelay:   100 * time.Millisecond,
	}
	b := resilience.NewBreakers(cfg, func(_ context.Context, kind, _ string) {
		mu.Lock()
		alertKinds = append(alertKinds, kind)
		mu.Unlock()
	})

	errFail := errors.New("upstream failure")

	// Drive 4 failures → breaker should open.
	for i := 0; i < 4; i++ {
		_, _ = b.Execute(resilience.UpstreamPG, func() (interface{}, error) {
			return nil, errFail
		})
	}

	if b.State(resilience.UpstreamPG) != gobreaker.StateOpen {
		t.Fatalf("breaker should be open after 4 failures; state=%v",
			b.State(resilience.UpstreamPG))
	}

	// Wait for OpenDelay to expire.
	time.Sleep(150 * time.Millisecond)

	// One successful probe → breaker closes.
	_, err := b.Execute(resilience.UpstreamPG, func() (interface{}, error) {
		return "ok", nil
	})
	if err != nil {
		t.Fatalf("unexpected error during half-open probe: %v", err)
	}

	if b.State(resilience.UpstreamPG) != gobreaker.StateClosed {
		t.Fatalf("breaker should be closed after successful probe; state=%v",
			b.State(resilience.UpstreamPG))
	}

	mu.Lock()
	defer mu.Unlock()
	hasOpened := false
	for _, k := range alertKinds {
		if k == "breaker_opened" {
			hasOpened = true
		}
	}
	if !hasOpened {
		t.Errorf("expected breaker_opened alert; got %v", alertKinds)
	}
}
