package resilience

import (
	"sync"
	"time"
)

// RetryBudget is a per-upstream token-bucket that limits the retry rate.
//
// Phase 9 §9.17.4 design:
//   - One token bucket per named upstream (lazy-initialized).
//   - Tokens refill at cfg.api_retry_budget_per_s per second.
//   - Burst capacity is cfg.api_retry_budget_capacity.
//   - Out-of-budget retries are FAILED IMMEDIATELY (no queuing, no extra
//     latency, no extra load on the upstream).
//
// Refill is computed lazily on Allow() — no background goroutine required.
type RetryBudget struct {
	mu       sync.Mutex
	buckets  map[string]*retryBucket
	perS     float64
	capacity float64
}

type retryBucket struct {
	tokens     float64
	lastRefill time.Time
}

// NewRetryBudget creates a budget. perS is the token refill rate (tokens/second);
// capacity is the maximum burst depth.
func NewRetryBudget(perS float64, capacity int) *RetryBudget {
	if perS <= 0 {
		perS = 1
	}
	cap := float64(capacity)
	if cap < 1 {
		cap = 1
	}
	return &RetryBudget{
		buckets:  make(map[string]*retryBucket),
		perS:     perS,
		capacity: cap,
	}
}

// Allow checks whether a retry is permitted for the named upstream.
// Returns true and consumes one token when the budget allows it.
// Returns false immediately when the bucket is empty (caller treats it as
// an immediate failure — no retry, no extra wait).
func (rb *RetryBudget) Allow(upstream string) bool {
	rb.mu.Lock()
	defer rb.mu.Unlock()

	bkt, ok := rb.buckets[upstream]
	if !ok {
		// Lazy-init: first call starts with a full burst.
		bkt = &retryBucket{tokens: rb.capacity, lastRefill: time.Now()}
		rb.buckets[upstream] = bkt
	}

	// Lazy refill: add tokens proportional to elapsed time.
	now := time.Now()
	elapsed := now.Sub(bkt.lastRefill).Seconds()
	bkt.tokens += elapsed * rb.perS
	if bkt.tokens > rb.capacity {
		bkt.tokens = rb.capacity
	}
	bkt.lastRefill = now

	if bkt.tokens < 1.0 {
		return false
	}
	bkt.tokens -= 1.0
	return true
}

// Tokens returns the current token count for an upstream (for testing).
func (rb *RetryBudget) Tokens(upstream string) float64 {
	rb.mu.Lock()
	defer rb.mu.Unlock()
	bkt, ok := rb.buckets[upstream]
	if !ok {
		return rb.capacity
	}
	return bkt.tokens
}
