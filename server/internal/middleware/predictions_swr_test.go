package middleware

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// stubPredictionSWRStore is a thread-safe in-memory PredictionSWRStore for tests.
type stubPredictionSWRStore struct {
	mu       sync.Mutex
	data     map[string]stubEntry
	getErr   error
	pttlErr  error
	setnxErr error
}

type stubEntry struct {
	value string
	pttl  time.Duration // negative means no TTL / key absent
}

func (s *stubPredictionSWRStore) Get(_ context.Context, key string) (string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.getErr != nil {
		return "", s.getErr
	}
	e, ok := s.data[key]
	if !ok {
		return "", errors.New("redis: nil")
	}
	return e.value, nil
}

func (s *stubPredictionSWRStore) PTTL(_ context.Context, key string) (time.Duration, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.pttlErr != nil {
		return 0, s.pttlErr
	}
	e, ok := s.data[key]
	if !ok {
		return -1, nil // key absent
	}
	return e.pttl, nil
}

func (s *stubPredictionSWRStore) SetNX(_ context.Context, key, value string, _ time.Duration) (bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.setnxErr != nil {
		return false, s.setnxErr
	}
	if _, ok := s.data[key]; ok {
		return false, nil // already exists
	}
	if s.data == nil {
		s.data = map[string]stubEntry{}
	}
	s.data[key] = stubEntry{value: value, pttl: -1}
	return true, nil
}

// ── PredictionCacheKey ────────────────────────────────────────────────────

func TestPredictionCacheKey(t *testing.T) {
	got := PredictionCacheKey("m1", "1x2,ou_2.5", 7)
	want := "cache.v1:prediction:m1:1x2,ou_2.5:7"
	if got != want {
		t.Errorf("PredictionCacheKey = %q, want %q", got, want)
	}
}

func TestSWRLockKey(t *testing.T) {
	got := SWRLockKey("m2", "1x2")
	want := "swr_lock:m2:1x2"
	if got != want {
		t.Errorf("SWRLockKey = %q, want %q", got, want)
	}
}

// ── PredictionSWR.Check ───────────────────────────────────────────────────

func newSWR(store PredictionSWRStore, staleAfterS, maxAgeS, inflightMax int) *PredictionSWR {
	return &PredictionSWR{
		Store:       store,
		StaleAfterS: staleAfterS,
		MaxAgeS:     maxAgeS,
		InflightMax: inflightMax,
	}
}

// TestCheck_Miss — key absent → (empty, false, false).
func TestCheck_Miss(t *testing.T) {
	store := &stubPredictionSWRStore{data: map[string]stubEntry{}}
	swr := newSWR(store, 30, 300, 64)

	body, fresh, stale := swr.Check(context.Background(), "cache.v1:prediction:m:1x2:1")
	if body != "" || fresh || stale {
		t.Errorf("miss: want ('', false, false), got (%q, %v, %v)", body, fresh, stale)
	}
}

// TestCheck_FreshHit — entry age well below stale_after_s → (body, true, false).
func TestCheck_FreshHit(t *testing.T) {
	key := PredictionCacheKey("m1", "1x2", 3)
	// MaxAgeS=300, StaleAfterS=30. PTTL=290s → age=10s < 30s → fresh.
	store := &stubPredictionSWRStore{
		data: map[string]stubEntry{
			key: {value: `{"ok":true}`, pttl: 290 * time.Second},
		},
	}
	swr := newSWR(store, 30, 300, 64)

	body, fresh, stale := swr.Check(context.Background(), key)
	if body != `{"ok":true}` || !fresh || stale {
		t.Errorf("fresh hit: want (body, true, false), got (%q, %v, %v)", body, fresh, stale)
	}
}

// TestCheck_StaleHit — entry age between stale_after_s and max_age_s → (body, false, true).
func TestCheck_StaleHit(t *testing.T) {
	key := PredictionCacheKey("m2", "1x2", 5)
	// MaxAgeS=300, StaleAfterS=30. PTTL=240s → age=60s; 60 > 30 → stale.
	store := &stubPredictionSWRStore{
		data: map[string]stubEntry{
			key: {value: `{"stale":true}`, pttl: 240 * time.Second},
		},
	}
	swr := newSWR(store, 30, 300, 64)

	body, fresh, stale := swr.Check(context.Background(), key)
	if body != `{"stale":true}` || fresh || !stale {
		t.Errorf("stale hit: want (body, false, true), got (%q, %v, %v)", body, fresh, stale)
	}
}

// TestCheck_RedisGetError_Miss — Get error → miss (fail-open as miss).
func TestCheck_RedisGetError_Miss(t *testing.T) {
	store := &stubPredictionSWRStore{getErr: errors.New("redis: connection refused")}
	swr := newSWR(store, 30, 300, 64)

	body, fresh, stale := swr.Check(context.Background(), "any-key")
	if body != "" || fresh || stale {
		t.Errorf("get error: want miss, got (%q, %v, %v)", body, fresh, stale)
	}
}

// TestCheck_RedisPTTLError_FailOpenFresh — entry readable but PTTL fails → fresh HIT.
func TestCheck_RedisPTTLError_FailOpenFresh(t *testing.T) {
	key := PredictionCacheKey("m3", "1x2", 2)
	store := &stubPredictionSWRStore{
		data:    map[string]stubEntry{key: {value: `{"x":1}`}},
		pttlErr: errors.New("redis: i/o timeout"),
	}
	swr := newSWR(store, 30, 300, 64)

	body, fresh, stale := swr.Check(context.Background(), key)
	if body != `{"x":1}` || !fresh || stale {
		t.Errorf("pttl error fail-open: want (body, true, false), got (%q, %v, %v)", body, fresh, stale)
	}
}

// ── PredictionSWR.TryFanout ───────────────────────────────────────────────

// TestTryFanout_Success — first call acquires lock and increments inflight.
func TestTryFanout_Success(t *testing.T) {
	store := &stubPredictionSWRStore{data: map[string]stubEntry{}}
	swr := newSWR(store, 30, 300, 64)

	if !swr.TryFanout(context.Background(), "m1", "1x2") {
		t.Fatal("TryFanout: expected true on first call")
	}
	if got := swr.inflight.Load(); got != 1 {
		t.Errorf("inflight after TryFanout = %d, want 1", got)
	}
}

// TestTryFanout_LockAlreadyHeld — SETNX fails (key exists) → returns false, inflight unchanged.
func TestTryFanout_LockAlreadyHeld(t *testing.T) {
	lockKey := SWRLockKey("m1", "1x2")
	store := &stubPredictionSWRStore{
		data: map[string]stubEntry{lockKey: {value: "1"}},
	}
	swr := newSWR(store, 30, 300, 64)

	if swr.TryFanout(context.Background(), "m1", "1x2") {
		t.Fatal("TryFanout: expected false when lock already held")
	}
	if got := swr.inflight.Load(); got != 0 {
		t.Errorf("inflight with lock held = %d, want 0", got)
	}
}

// TestTryFanout_InflightCapReached — pod-level cap → returns false before SETNX.
func TestTryFanout_InflightCapReached(t *testing.T) {
	store := &stubPredictionSWRStore{data: map[string]stubEntry{}}
	swr := newSWR(store, 30, 300, 2)
	// Pre-fill the counter to the cap.
	swr.inflight.Store(2)

	if swr.TryFanout(context.Background(), "m2", "1x2") {
		t.Fatal("TryFanout: expected false when inflight cap reached")
	}
}

// TestDoneFanout — decrements the inflight counter.
func TestDoneFanout(t *testing.T) {
	swr := newSWR(nil, 30, 300, 64)
	swr.inflight.Store(3)
	swr.DoneFanout()
	if got := swr.inflight.Load(); got != 2 {
		t.Errorf("inflight after DoneFanout = %d, want 2", got)
	}
}

// TestTryFanout_SWRFanoutBounded — proof: at most InflightMax concurrent
// TryFanout calls succeed across unique (matchID, marketSet) pairs.
//
// Fires InflightMax+5 goroutines; each acquires a unique lock key.
// The cap is InflightMax so exactly InflightMax should succeed.
func TestTryFanout_SWRFanoutBounded(t *testing.T) {
	cap := 4
	store := &stubPredictionSWRStore{data: map[string]stubEntry{}}
	swr := newSWR(store, 30, 300, cap)

	var successes atomic.Int64
	done := make(chan struct{})

	for i := 0; i < cap+5; i++ {
		matchID := "m" + string(rune('a'+i))
		go func(id string) {
			if swr.TryFanout(context.Background(), id, "1x2") {
				successes.Add(1)
			}
			done <- struct{}{}
		}(matchID)
	}

	for i := 0; i < cap+5; i++ {
		<-done
	}

	got := int(successes.Load())
	if got > cap {
		t.Errorf("SWR fan-out: %d goroutines succeeded, cap is %d — bounded invariant violated", got, cap)
	}
}

// TestRedisPredictionSWR_InterfaceSatisfied — compile-time check that
// *RedisPredictionSWR satisfies PredictionSWRStore.
func TestRedisPredictionSWR_InterfaceSatisfied(t *testing.T) {
	var _ PredictionSWRStore = (*RedisPredictionSWR)(nil)
}

// TestPredictionSWR_InterfaceCheck_MethodSet — compile-time check that
// *PredictionSWR exposes the three methods required by
// handlers.PredictionCacheChecker (checked structurally, not via import).
func TestPredictionSWR_InterfaceCheck_MethodSet(t *testing.T) {
	type cacheChecker interface {
		Check(ctx context.Context, key string) (body string, isFresh, isStale bool)
		TryFanout(ctx context.Context, matchID, marketSet string) bool
		DoneFanout()
	}
	var _ cacheChecker = (*PredictionSWR)(nil)
}

// TestSWRAsyncFanoutBounded — §9.14 proof: flooding 200 concurrent TryFanout
// calls with distinct keys must succeed at most cfg.api_swr_inflight_max times.
// Regression guard for the atomic inflight cap in PredictionSWR.TryFanout.
func TestSWRAsyncFanoutBounded(t *testing.T) {
	const total = 200
	const cap = 10
	store := &stubPredictionSWRStore{data: map[string]stubEntry{}}
	swr := newSWR(store, 30, 300, cap)

	var successes atomic.Int64
	done := make(chan struct{}, total)

	for i := 0; i < total; i++ {
		go func(idx int) {
			// Each goroutine uses a unique matchID so SETNX always succeeds;
			// the only limit is the pod-level inflight counter.
			matchID := fmt.Sprintf("match-%04d", idx)
			if swr.TryFanout(context.Background(), matchID, "1x2") {
				successes.Add(1)
			}
			done <- struct{}{}
		}(i)
	}
	for i := 0; i < total; i++ {
		<-done
	}

	if got := int(successes.Load()); got > cap {
		t.Errorf("SWRAsyncFanoutBounded: %d goroutines succeeded, cap=%d — bounded invariant violated", got, cap)
	}
}

// TestAdvSWRThunderingHerd — adv_test_swr_thundering_herd.
//
// 1000 concurrent goroutines all attempt TryFanout for the SAME (matchID,
// marketSet) pair simultaneously (thundering-herd scenario at t=0).
// The SETNX lock is the sole gate; the inflight cap is set well above 1000
// so it is NOT the limiting factor.
//
// Invariant: exactly 1 goroutine must win TryFanout (acquire the SETNX lock),
// meaning exactly 1 async revalidation goroutine would be spawned — i.e.
// exactly 1 "backend RPC" fires.
//
// Phase 12 prerequisite; must be green at Phase 9 close. Run with -race.
func TestAdvSWRThunderingHerd(t *testing.T) {
	const goroutines = 1000
	const matchID   = "match-thunderherd"
	const marketSet = "1x2"

	store := &stubPredictionSWRStore{data: map[string]stubEntry{}}
	// InflightMax >> goroutines: the atomic inflight counter is NOT the binding
	// constraint here. Only the SETNX lock on the shared key limits fan-out.
	swr := newSWR(store, 30, 300, goroutines+1)

	var wins atomic.Int64
	done := make(chan struct{}, goroutines)

	for i := 0; i < goroutines; i++ {
		go func() {
			if swr.TryFanout(context.Background(), matchID, marketSet) {
				wins.Add(1)
				// Release the inflight slot — in production this is done by
				// defer cache.DoneFanout() in the async goroutine.
				swr.DoneFanout()
			}
			done <- struct{}{}
		}()
	}
	for i := 0; i < goroutines; i++ {
		<-done
	}

	got := int(wins.Load())
	if got != 1 {
		t.Errorf("thundering herd: %d goroutines won TryFanout for the same key; want exactly 1 (SETNX must gate)", got)
	}
}
