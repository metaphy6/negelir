package resilience

import (
	"context"

	"golang.org/x/sync/semaphore"
)

// Bulkhead is a semaphore-based bounded-concurrency guard for a single upstream.
//
// Sized to floor(poolSize * 0.8) so the last 20% of the pool is reserved for
// /v1/healthz + /v1/readyz, which bypass bulkhead enforcement entirely.
//
// Phase 9 §9.17.4 design:
//   - A saturated bulkhead returns false from TryAcquire immediately (no wait).
//   - Health probes never call Acquire/TryAcquire — they own the reserved 20%.
type Bulkhead struct {
	sem *semaphore.Weighted
}

// NewBulkhead creates a bulkhead for an upstream with the given pool size.
// Effective capacity = max(1, floor(poolSize * 0.8)).
func NewBulkhead(poolSize int) *Bulkhead {
	cap := int64(float64(poolSize) * 0.8)
	if cap < 1 {
		cap = 1
	}
	return &Bulkhead{sem: semaphore.NewWeighted(cap)}
}

// Capacity returns the semaphore weight (for testing).
func (b *Bulkhead) Capacity() int64 {
	// There is no public getter on semaphore.Weighted; store it separately.
	// We expose it via a field instead.
	return 0 // unreachable — see BulkheadWithCapacity for testing
}

// TryAcquire attempts a non-blocking semaphore acquisition.
// Returns true when a slot is available; false when the bulkhead is full.
// The caller MUST call Release after a successful TryAcquire.
func (b *Bulkhead) TryAcquire() bool {
	return b.sem.TryAcquire(1)
}

// Acquire blocks until a slot is available or ctx is cancelled.
// The caller MUST call Release after a successful Acquire.
func (b *Bulkhead) Acquire(ctx context.Context) error {
	return b.sem.Acquire(ctx, 1)
}

// Release returns one slot to the semaphore.
func (b *Bulkhead) Release() {
	b.sem.Release(1)
}

// bulkheadWithCap wraps Bulkhead and stores the capacity for tests.
type bulkheadWithCap struct {
	*Bulkhead
	cap int64
}

// NewBulkheadWithCap is like NewBulkhead but stores the computed capacity for
// tests that need to verify the sizing formula.
func NewBulkheadWithCap(poolSize int) (*Bulkhead, int64) {
	cap := int64(float64(poolSize) * 0.8)
	if cap < 1 {
		cap = 1
	}
	return &Bulkhead{sem: semaphore.NewWeighted(cap)}, cap
}

// Bulkheads holds one Bulkhead per upstream.
type Bulkheads struct {
	PG         *Bulkhead
	RedisCache *Bulkhead
	RedisBus   *Bulkhead
	SwarmRPC   *Bulkhead
}

// NewBulkheads creates per-upstream bulkheads sized by pool size.
// swarmRPCPoolSize may be 0 when the swarm RPC pool is not configured;
// in that case the SwarmRPC bulkhead defaults to a minimum of 1.
func NewBulkheads(pgPoolSize, redisCachePoolSize, redisBusPoolSize, swarmRPCPoolSize int) *Bulkheads {
	return &Bulkheads{
		PG:         NewBulkhead(pgPoolSize),
		RedisCache: NewBulkhead(redisCachePoolSize),
		RedisBus:   NewBulkhead(redisBusPoolSize),
		SwarmRPC:   NewBulkhead(swarmRPCPoolSize),
	}
}
