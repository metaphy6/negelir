package middleware

import (
	"context"
	"fmt"
	"sync/atomic"
	"time"

	"github.com/redis/go-redis/v9"
)

// PredictionSWRStore is the minimal Redis surface for prediction SWR cache reads.
//
// Implementations:
//   - RedisPredictionSWR (this package) — production adapter over *redis.Client.
//   - stubPredictionSWRStore in predictions_swr_test.go — unit-test stand-in.
type PredictionSWRStore interface {
	// Get returns (value, nil) on a hit, ("", redis.Nil) on miss, ("", err) on fault.
	Get(ctx context.Context, key string) (string, error)
	// PTTL returns the remaining time-to-live of key.
	// Returns a negative duration when the key does not exist or has no expiry.
	PTTL(ctx context.Context, key string) (time.Duration, error)
	// SetNX sets key=value with ttl only if the key does not already exist.
	// Returns (true, nil) when the key was absent and set successfully.
	// Returns (false, nil) when the key already existed (not set).
	// Returns (false, err) on a Redis communication fault.
	SetNX(ctx context.Context, key, value string, ttl time.Duration) (bool, error)
}

// RedisPredictionSWR adapts a *redis.Client to PredictionSWRStore.
type RedisPredictionSWR struct{ C *redis.Client }

// Get delegates to the underlying Redis client.
func (r *RedisPredictionSWR) Get(ctx context.Context, key string) (string, error) {
	return r.C.Get(ctx, key).Result()
}

// PTTL delegates to the underlying Redis client.
func (r *RedisPredictionSWR) PTTL(ctx context.Context, key string) (time.Duration, error) {
	return r.C.PTTL(ctx, key).Result()
}

// SetNX delegates to the underlying Redis client.
func (r *RedisPredictionSWR) SetNX(ctx context.Context, key, value string, ttl time.Duration) (bool, error) {
	return r.C.SetNX(ctx, key, value, ttl).Result()
}

// PredictionCacheKey returns the Redis key for a prediction cache entry.
//
//	Format: cache.v1:prediction:<match_id>:<market_set>:<calibration_version>
//
// market_set is a caller-normalised (sorted, comma-joined) string of market names
// so that {"1x2","ou_2.5"} and {"ou_2.5","1x2"} produce the same key.
func PredictionCacheKey(matchID, marketSet string, calibVersion int) string {
	return fmt.Sprintf("cache.v1:prediction:%s:%s:%d", matchID, marketSet, calibVersion)
}

// SWRLockKey returns the Redis SETNX key that gates SWR fan-out for a
// (matchID, marketSet) pair.
//
//	Format: swr_lock:<match_id>:<market_set>
func SWRLockKey(matchID, marketSet string) string {
	return fmt.Sprintf("swr_lock:%s:%s", matchID, marketSet)
}

// PredictionSWR implements the cache-read and stale-while-revalidate (SWR)
// logic for the predictions endpoint. It is constructed in cmd/api/main.go
// and injected into handlers.PredictionsHandler via the PredictionCacheChecker
// interface defined in internal/handlers.
//
// Thread-safety: all exported fields are read-only after construction.
// The inflight counter uses sync/atomic.Int64.
type PredictionSWR struct {
	Store       PredictionSWRStore
	StaleAfterS int // entries older than this (s) trigger SWR; must be < MaxAgeS
	MaxAgeS     int // entries older than this (s) are treated as miss
	InflightMax int // pod-level cap on concurrent SWR async goroutines

	inflight atomic.Int64
}

// Check looks up the prediction cache entry at key and classifies it.
//
// Returns (body, isFresh, isStale):
//   - isFresh=true  — fresh HIT; caller serves with X-Cache: hit.
//   - isStale=true  — stale HIT; caller serves with X-Cache: stale and
//     should trigger an async revalidation via TryFanout.
//   - both false    — cache miss; caller should issue the RPC.
//
// Age is approximated as: MaxAgeS − PTTL(key) in whole seconds.
// Fail-open on Redis errors: if PTTL fails but the entry was readable, the
// entry is served as a fresh HIT to avoid unnecessary RPC storms.
func (p *PredictionSWR) Check(ctx context.Context, key string) (body string, isFresh, isStale bool) {
	body, err := p.Store.Get(ctx, key)
	if err != nil || body == "" {
		return "", false, false // miss
	}

	pttl, err := p.Store.PTTL(ctx, key)
	if err != nil || pttl < 0 {
		// Fail-open: entry exists but PTTL is unavailable → serve as fresh.
		return body, true, false
	}

	ageS := p.MaxAgeS - int(pttl.Seconds())
	if ageS < 0 {
		ageS = 0
	}
	if ageS > p.StaleAfterS {
		return body, false, true // stale
	}
	return body, true, false // fresh
}

// TryFanout attempts to gate an async SWR refresh for (matchID, marketSet).
//
// Returns true when the caller should fire a predict.request async publish.
// Returns false when:
//   - the pod-level inflight count has reached InflightMax (no-op), OR
//   - SETNX fails — another goroutine or pod already holds the lock (no-op), OR
//   - a Redis error occurred (fail-open, no-op).
//
// Callers MUST call DoneFanout after the async work completes, whether it
// succeeded or failed, so the inflight counter is decremented.
//
// The inflight counter is the semaphore: it is incremented atomically before
// the SETNX call. If SETNX fails (or the cap would be exceeded), the counter
// is decremented before returning false. This prevents check-then-act races.
func (p *PredictionSWR) TryFanout(ctx context.Context, matchID, marketSet string) bool {
	// Reserve a slot in the inflight counter first (atomic increment).
	if newVal := p.inflight.Add(1); newVal > int64(p.InflightMax) {
		p.inflight.Add(-1) // no slot available — relinquish immediately
		return false
	}
	lockKey := SWRLockKey(matchID, marketSet)
	// Lock TTL = 2×MaxAgeS to guarantee expiry even if DoneFanout is never
	// called (goroutine panic / pod crash). Belt-and-suspenders.
	lockTTL := time.Duration(p.MaxAgeS*2) * time.Second
	ok, err := p.Store.SetNX(ctx, lockKey, "1", lockTTL)
	if err != nil || !ok {
		p.inflight.Add(-1) // release the reserved slot
		return false
	}
	return true
}

// DoneFanout decrements the inflight counter. Must be called (typically via
// defer) by the async goroutine spawned after TryFanout returns true.
func (p *PredictionSWR) DoneFanout() {
	p.inflight.Add(-1)
}
