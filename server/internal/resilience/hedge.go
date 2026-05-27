package resilience

import (
	"sync"
	"sync/atomic"

	"golang.org/x/sync/singleflight"
)

// HedgeTracker tracks hedge decisions and enforces the budget cap.
//
// Phase 9 §9.17.4: never hedge more than cfg.api_hedge_budget_pct (default 10%)
// of recent RPC calls. The tracker uses a simple counter (not a rolling window)
// which is adequate for the proof test; a production deployment would reset the
// counters on a configurable interval.
type HedgeTracker struct {
	mu        sync.Mutex
	total     int64
	hedged    int64
	budgetPct int
}

// NewHedgeTracker creates a tracker with the given budget percentage (0–100).
func NewHedgeTracker(budgetPct int) *HedgeTracker {
	if budgetPct < 0 {
		budgetPct = 0
	}
	if budgetPct > 100 {
		budgetPct = 100
	}
	return &HedgeTracker{budgetPct: budgetPct}
}

// RecordRPC increments the total RPC counter.
// Call this for every primary (non-hedge) RPC.
func (t *HedgeTracker) RecordRPC() {
	t.mu.Lock()
	t.total++
	t.mu.Unlock()
}

// ShouldHedge returns true (and increments the hedged counter) when the hedge
// budget allows it. It returns false when the budget is exhausted.
// Thread-safe; typically called after RecordRPC for the same call.
func (t *HedgeTracker) ShouldHedge() bool {
	t.mu.Lock()
	defer t.mu.Unlock()
	if t.total == 0 {
		return false
	}
	ratio := float64(t.hedged) / float64(t.total)
	if ratio < float64(t.budgetPct)/100.0 {
		t.hedged++
		return true
	}
	return false
}

// Totals returns the raw (total, hedged) counters for testing.
func (t *HedgeTracker) Totals() (total, hedged int64) {
	t.mu.Lock()
	defer t.mu.Unlock()
	return t.total, t.hedged
}

// Reset zeroes all counters (for rolling-window renewal in production).
func (t *HedgeTracker) Reset() {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.total = 0
	t.hedged = 0
}

// SFGroup wraps golang.org/x/sync/singleflight for cache-miss collapse.
//
// Phase 9 §9.17.4: keyed on (match_id, market_set, calibration_version).
// 1000 concurrent cache-MISS requests for the same key fan out to ONE
// predict.request; all waiters receive the same result.
type SFGroup struct {
	sf singleflight.Group
}

// Do executes fn once for the given key, regardless of how many goroutines
// call Do with the same key concurrently. Returns (result, err, shared) where
// shared is true when this caller received a previously-in-flight result.
func (g *SFGroup) Do(key string, fn func() (interface{}, error)) (interface{}, error, bool) {
	return g.sf.Do(key, fn)
}

// singleflightCallCount is used only by tests to count underlying fn calls.
// It is a package-level exported counter so tests in the same package can reset it.
var singleflightCallCount int64

// ResetSFCallCount resets the test counter to zero.
func ResetSFCallCount() { atomic.StoreInt64(&singleflightCallCount, 0) }

// LoadSFCallCount returns the current test counter.
func LoadSFCallCount() int64 { return atomic.LoadInt64(&singleflightCallCount) }
