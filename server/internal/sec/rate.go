package sec

import (
	"context"
	"sync"
	"time"
)

// RateStatus mirrors the Lua script's return enum (sec_rate_check.lua).
type RateStatus string

const (
	RateAllow    RateStatus = "allow"
	RateThrottle RateStatus = "throttle"
	RateDenied   RateStatus = "denied"
	RateError    RateStatus = "error"
)

// RateDecision is the gateway's view of one rate-check result.
type RateDecision struct {
	Status        RateStatus
	Remaining     float64       // tokens left in the bucket post-charge
	RetryAfter    time.Duration // 0 for allow; positive for throttle / denied
	CostCharged   int           // tokens actually charged (zero for denied)
	UsedFallback  bool          // true when the secondary in-process bucket served the call
	UsedTier      string        // "redis" | "secondary" | "denylist"
	SubjectKey    string        // bucket key used (e.g. "203.0.113.7/32")
}

// RateChecker is the interface the middleware speaks to. The
// production implementation is `RedisRateChecker` (calls EVALSHA
// against sec_rate_check.lua); tests inject a fake.
type RateChecker interface {
	Check(ctx context.Context, subject string, capacity int, refillPerS float64, cost int) (RateDecision, error)
}

// SecondaryBucket is the in-process GCRA fallback used when Redis is
// unreachable or the EVALSHA round-trip blew the timeout. It is
// intentionally per-process (no cross-instance coordination) — the
// gateway's quorum live behind a load balancer, so the per-process
// budget acts as a coarse circuit-breaker against the load-balancer
// fanning a misbehaving subject across N instances.
//
// Doctrine: the secondary tier is FAIL-OPEN (lower capacity than
// Redis, refills slower) but it never DENIES — a sustained Redis
// outage degrades to "every legitimate user is throttled to the
// secondary's pace", not to "every user is denied". Denylisting only
// happens when Redis is healthy enough to consult sec.denylist.v1.
type SecondaryBucket struct {
	capacity   float64
	refillPerS float64

	mu      sync.Mutex
	buckets map[string]*gcraState
	maxKeys int
}

type gcraState struct {
	tokens    float64
	updatedAt time.Time
}

// NewSecondaryBucket builds a fail-open in-process limiter. `maxKeys`
// caps the LRU size; an entry past the cap evicts the oldest. Zero
// or negative means "unbounded" (only safe in tests).
func NewSecondaryBucket(capacity int, refillPerS float64, maxKeys int) *SecondaryBucket {
	cap := float64(capacity)
	if cap < 1 {
		cap = 1
	}
	if refillPerS <= 0 {
		refillPerS = 1
	}
	return &SecondaryBucket{
		capacity:   cap,
		refillPerS: refillPerS,
		buckets:    make(map[string]*gcraState),
		maxKeys:    maxKeys,
	}
}

// Check serves the same contract as RateChecker.Check but always
// against the in-process bucket. Returns RateAllow or RateThrottle
// only — never RateDenied (denylist enforcement requires Redis
// coordination).
//
// `cost` is the weighted token cost for the endpoint (per
// endpoint_costs.yaml). A cost of 0 always allows.
func (b *SecondaryBucket) Check(ctx context.Context, subject string, capacity int, refillPerS float64, cost int) (RateDecision, error) {
	if cost <= 0 {
		return RateDecision{
			Status:       RateAllow,
			Remaining:    b.capacity,
			SubjectKey:   subject,
			UsedFallback: true,
			UsedTier:     "secondary",
			CostCharged:  0,
		}, nil
	}
	now := time.Now()
	b.mu.Lock()
	defer b.mu.Unlock()
	st, ok := b.buckets[subject]
	if !ok {
		st = &gcraState{tokens: b.capacity, updatedAt: now}
		b.buckets[subject] = st
		b.evictIfFull(subject)
	}
	// Refill since last touch.
	elapsed := now.Sub(st.updatedAt).Seconds()
	if elapsed > 0 {
		st.tokens += elapsed * b.refillPerS
		if st.tokens > b.capacity {
			st.tokens = b.capacity
		}
		st.updatedAt = now
	}
	if st.tokens >= float64(cost) {
		st.tokens -= float64(cost)
		return RateDecision{
			Status:       RateAllow,
			Remaining:    st.tokens,
			SubjectKey:   subject,
			UsedFallback: true,
			UsedTier:     "secondary",
			CostCharged:  cost,
		}, nil
	}
	deficit := float64(cost) - st.tokens
	retryS := deficit / b.refillPerS
	return RateDecision{
		Status:       RateThrottle,
		Remaining:    st.tokens,
		RetryAfter:   time.Duration(retryS * float64(time.Second)),
		SubjectKey:   subject,
		UsedFallback: true,
		UsedTier:     "secondary",
		CostCharged:  0,
	}, nil
}

// evictIfFull is a coarse LRU: when the map exceeds maxKeys, evict
// the bucket with the oldest updatedAt. Linear scan is fine for the
// expected cap (low thousands of subjects per gateway pod).
func (b *SecondaryBucket) evictIfFull(latest string) {
	if b.maxKeys <= 0 || len(b.buckets) <= b.maxKeys {
		return
	}
	var oldestKey string
	var oldestTime time.Time
	first := true
	for k, st := range b.buckets {
		if k == latest {
			continue
		}
		if first || st.updatedAt.Before(oldestTime) {
			oldestKey = k
			oldestTime = st.updatedAt
			first = false
		}
	}
	if oldestKey != "" {
		delete(b.buckets, oldestKey)
	}
}

// Size returns the number of tracked subjects (handy for tests
// asserting LRU eviction).
func (b *SecondaryBucket) Size() int {
	b.mu.Lock()
	defer b.mu.Unlock()
	return len(b.buckets)
}
