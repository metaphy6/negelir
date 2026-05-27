// Package cache implements the Phase 9 §9.17.6 in-process L0 LRU cache that
// sits ahead of the Redis L1 layer to absorb the hottest keys per pod.
//
// Design constraints (§9.17.6):
//   - LRU eviction by entry count (L0Config.MaxEntries) AND byte usage
//     (L0Config.MaxBytes). The bytes cap is enforced best-effort via an
//     atomic counter; slight over-provisioning under concurrent writes is
//     bounded to a few entry widths.
//   - TTL per entry = min(provided TTL, L0Config.MaxTTL).
//   - Negative cache: 404 + 410 statuses only; never 5xx.
//   - Stampede protection: per-key sync.Cond; max wait = L0Config.RefreshMaxWait
//     then fall through to direct fetch (bounded queue depth).
//   - Redis keyspace invalidation: background goroutine subscribes to
//     "__keyevent@0__:set" and evicts matching L0 entries on "cache:*:gen"
//     changes. Redis must have keyspace events enabled:
//       CONFIG SET notify-keyspace-events "KE$"
//   - Fallback gen check: every Get also verifies the gen counter via Redis
//     (extra round-trip on hit; no-op when rdb is nil or gen=0).
package cache

import (
	"context"
	"fmt"
	"net/http"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	lru "github.com/hashicorp/golang-lru/v2"
	"github.com/redis/go-redis/v9"
)

// entry is a single L0 cache slot.
type entry struct {
	value      []byte
	expiresAt  time.Time
	gen        int64 // Redis gen at cache time; 0 = not tracking
	negative   bool  // true for 404/410 negative-cache entries
	statusCode int   // HTTP status for negative entries (404 or 410)
	sizeBytes  int   // len(value); used for bytes-cap accounting
}

// keyState tracks an in-progress fetch for stampede protection.
// Only one goroutine may fetch a key at a time; others wait on the Cond.
type keyState struct {
	mu       sync.Mutex
	cond     *sync.Cond
	fetching bool
}

func newKeyState() *keyState {
	ks := &keyState{}
	ks.cond = sync.NewCond(&ks.mu)
	return ks
}

// AlertFunc is the sec.alert.v1 emission callback. kind is one of the
// "api_l0_*" alert kinds defined in §9.17.13.
type AlertFunc func(ctx context.Context, kind, severity string)

// L0Config holds all §9.17.6 tunable knobs. Build from *config.Config using
// the duration helpers L0MaxTTL(), NegativeCacheTTL(), etc.
type L0Config struct {
	// MaxEntries is the maximum number of L0 entries (cfg.api_l0_cache_max_entries).
	MaxEntries int
	// MaxBytes is the maximum total byte footprint (cfg.api_l0_cache_max_bytes).
	MaxBytes int64
	// MaxTTL caps per-entry TTL to min(cache.v1 TTL, MaxTTL) (cfg.api_l0_max_ttl_s).
	MaxTTL time.Duration
	// NegativeCacheTTL is the TTL for 404/410 negative entries (cfg.api_negative_cache_s).
	NegativeCacheTTL time.Duration
	// RefreshMaxWait is the max block time for stampede-waiting goroutines
	// before falling through to a direct fetch (cfg.api_l0_refresh_max_wait_ms).
	RefreshMaxWait time.Duration
	// InvalidationLagMax is the SLO target for keyspace-notification eviction
	// (cfg.api_l0_invalidation_lag_max_ms). Used only for alerting.
	InvalidationLagMax time.Duration
}

// L0 is the in-process LRU cache (Phase 9 §9.17.6).
// Construct with NewL0; call StartInvalidationListener before serving traffic.
type L0 struct {
	cfg        L0Config
	lruCache   *lru.Cache[string, *entry]
	totalBytes atomic.Int64
	inflight   sync.Map // key → *keyState
	rdb        redis.UniversalClient // nil OK — disables gen checks + listener
	alertFn    AlertFunc             // nil OK
}

// NewL0 builds an L0 cache. rdb and alertFn may be nil (disables
// Redis-backed features; useful in unit tests that exercise non-Redis paths).
func NewL0(cfg L0Config, rdb redis.UniversalClient, alertFn AlertFunc) (*L0, error) {
	if cfg.MaxEntries <= 0 {
		return nil, fmt.Errorf("l0: MaxEntries must be > 0, got %d", cfg.MaxEntries)
	}
	l := &L0{cfg: cfg, rdb: rdb, alertFn: alertFn}
	c, err := lru.NewWithEvict[string, *entry](cfg.MaxEntries, l.onEvict)
	if err != nil {
		return nil, fmt.Errorf("l0: lru.New(%d): %w", cfg.MaxEntries, err)
	}
	l.lruCache = c
	return l, nil
}

// onEvict is called by the LRU on capacity eviction or explicit Remove.
// NOTE: hashicorp/golang-lru/v2 does NOT call onEvict for in-place key
// updates (Add on an existing key). Set handles the replacement-bytes
// adjustment explicitly via Peek before calling Add.
func (l *L0) onEvict(_ string, e *entry) {
	l.totalBytes.Add(-int64(e.sizeBytes))
}

// effectiveTTL returns min(ttl, cfg.MaxTTL). Non-positive ttl defaults to MaxTTL.
func (l *L0) effectiveTTL(ttl time.Duration) time.Duration {
	if ttl <= 0 || ttl > l.cfg.MaxTTL {
		return l.cfg.MaxTTL
	}
	return ttl
}

// ── Core cache operations ──────────────────────────────────────────────────

// Set stores value for key with the given TTL (capped to MaxTTL) and gen.
// gen=0 disables the fallback gen check on subsequent Get calls.
// The bytes cap is a soft cap (best-effort; slight over-provisioning under
// concurrent writes is bounded to a few entry widths).
func (l *L0) Set(key string, value []byte, ttl time.Duration, gen int64) {
	size := int64(len(value))

	// Soft bytes cap: proactively evict LRU entries until there is likely room.
	for l.totalBytes.Load()+size > l.cfg.MaxBytes {
		if _, _, ok := l.lruCache.RemoveOldest(); !ok {
			break
		}
	}

	// Adjust bytes for in-place replacement: onEvict is not called by
	// hashicorp/golang-lru/v2 when Add updates an existing key.
	if prev, ok := l.lruCache.Peek(key); ok {
		l.totalBytes.Add(-int64(prev.sizeBytes))
	}

	e := &entry{
		value:     value,
		expiresAt: time.Now().Add(l.effectiveTTL(ttl)),
		gen:       gen,
		sizeBytes: int(size),
	}
	l.totalBytes.Add(size)
	l.lruCache.Add(key, e)
}

// SetNegative caches a negative response for key.
// Only http.StatusNotFound (404) and http.StatusGone (410) are accepted.
// 5xx codes are silently ignored — caching them would mask transient outages.
func (l *L0) SetNegative(key string, statusCode int) {
	if statusCode != http.StatusNotFound && statusCode != http.StatusGone {
		return
	}
	e := &entry{
		expiresAt:  time.Now().Add(l.cfg.NegativeCacheTTL),
		negative:   true,
		statusCode: statusCode,
	}
	l.lruCache.Add(key, e)
}

// GetNegative returns the cached negative HTTP status for key, or (0, false)
// when there is no live negative-cache entry.
func (l *L0) GetNegative(key string) (int, bool) {
	e, ok := l.lruCache.Get(key)
	if !ok || !e.negative {
		return 0, false
	}
	if time.Now().After(e.expiresAt) {
		l.lruCache.Remove(key)
		return 0, false
	}
	return e.statusCode, true
}

// Get returns (value, true, nil) for a live positive L0 hit.
// Returns (nil, false, nil) on miss, expiry, or when the entry is negative.
//
// Fallback gen check: when rdb is non-nil and the entry has a non-zero gen,
// the current "cache:<key>:gen" Redis counter is fetched. A mismatch evicts
// the entry and returns a miss. Redis errors during the gen check are
// tolerated — the entry is treated as valid; the background listener is the
// primary invalidation path.
func (l *L0) Get(ctx context.Context, key string) ([]byte, bool, error) {
	e, ok := l.lruCache.Get(key)
	if !ok || e.negative {
		return nil, false, nil
	}
	if time.Now().After(e.expiresAt) {
		l.lruCache.Remove(key)
		return nil, false, nil
	}
	// Fallback gen check (extra Redis round-trip on hit).
	if l.rdb != nil && e.gen != 0 {
		if cur, err := l.currentGen(ctx, key); err == nil && cur != 0 && cur != e.gen {
			l.lruCache.Remove(key)
			return nil, false, nil
		}
	}
	return e.value, true, nil
}

// currentGen fetches the Redis gen counter for "cache:<key>:gen".
// Returns (0, nil) when the key is absent (never invalidated = gen 0).
func (l *L0) currentGen(ctx context.Context, cacheKey string) (int64, error) {
	v, err := l.rdb.Get(ctx, "cache:"+cacheKey+":gen").Int64()
	if err == redis.Nil {
		return 0, nil
	}
	return v, err
}

// Invalidate evicts the L0 entry for cacheKey. Called by the background
// invalidation listener and directly from handlers when needed.
func (l *L0) Invalidate(key string) {
	l.lruCache.Remove(key)
}

// ContainsKey reports whether key has a live (non-expired) positive entry
// without updating LRU order or performing a gen counter check.
// Intended for tests; do not use on the hot path.
func (l *L0) ContainsKey(key string) bool {
	e, ok := l.lruCache.Peek(key)
	if !ok {
		return false
	}
	return !e.negative && time.Now().Before(e.expiresAt)
}

// Len returns the current number of entries in the L0 LRU (expired + live).
func (l *L0) Len() int { return l.lruCache.Len() }

// ── Stampede protection ────────────────────────────────────────────────────

// StartFetch claims the fetch slot for key. Returns true if this goroutine is
// the designated fetcher (it MUST call DoneFetch when done, even on error).
// Returns false if another goroutine is already fetching; the caller should
// call WaitForFetch and then re-check the L0 cache before deciding to fetch.
func (l *L0) StartFetch(key string) bool {
	ks := newKeyState()
	actual, loaded := l.inflight.LoadOrStore(key, ks)
	if loaded {
		ks = actual.(*keyState)
	}
	ks.mu.Lock()
	defer ks.mu.Unlock()
	if ks.fetching {
		return false
	}
	ks.fetching = true
	return true
}

// DoneFetch signals completion of the fetch for key and wakes all waiters.
// MUST be called (ideally via defer) by the goroutine that received true from
// StartFetch, regardless of whether the underlying fetch succeeded or failed.
func (l *L0) DoneFetch(key string) {
	v, ok := l.inflight.LoadAndDelete(key)
	if !ok {
		return
	}
	ks := v.(*keyState)
	ks.mu.Lock()
	ks.fetching = false
	ks.cond.Broadcast()
	ks.mu.Unlock()
}

// WaitForFetch waits up to maxWait for the in-progress fetch of key to finish.
// Returns true if the fetch completed within maxWait; false on timeout (caller
// should fall through to a direct fetch — the "bounded queue depth" guarantee).
//
// A watchdog goroutine broadcasts on the Cond after maxWait so this function
// always returns within ~maxWait regardless of the fetching goroutine.
func (l *L0) WaitForFetch(key string, maxWait time.Duration) bool {
	v, ok := l.inflight.Load(key)
	if !ok {
		// Race: DoneFetch ran between StartFetch(false) and here.
		return true
	}
	ks := v.(*keyState)

	// Watchdog: broadcast after maxWait so Wait never blocks indefinitely.
	stop := make(chan struct{})
	go func() {
		t := time.NewTimer(maxWait)
		defer t.Stop()
		select {
		case <-t.C:
			ks.cond.Broadcast() // safe to call without holding the mutex
		case <-stop:
		}
	}()
	defer close(stop)

	deadline := time.Now().Add(maxWait)
	ks.mu.Lock()
	for ks.fetching && time.Now().Before(deadline) {
		ks.cond.Wait()
	}
	completed := !ks.fetching
	ks.mu.Unlock()
	return completed
}

// ── Redis keyspace invalidation ────────────────────────────────────────────

// StartInvalidationListener starts the background goroutine that subscribes
// to "__keyevent@0__:set" Redis keyspace notifications and evicts L0 entries
// when "cache:*:gen" keys change within cfg.api_l0_invalidation_lag_max_ms.
//
// Redis must have keyspace events enabled:
//   CONFIG SET notify-keyspace-events "KE$"
//
// This method is a no-op when rdb is nil.
// It must be called at most once per L0 instance.
func (l *L0) StartInvalidationListener(ctx context.Context) {
	if l.rdb == nil {
		return
	}
	go l.invalidationLoop(ctx)
}

func (l *L0) invalidationLoop(ctx context.Context) {
	const channel = "__keyevent@0__:set"
	sub := l.rdb.Subscribe(ctx, channel)
	defer func() { _ = sub.Close() }()

	ch := sub.Channel()
	for {
		select {
		case <-ctx.Done():
			return
		case msg, ok := <-ch:
			if !ok {
				return
			}
			if cacheKey, match := genKeyToCacheKey(msg.Payload); match {
				l.Invalidate(cacheKey)
			}
		}
	}
}

// genKeyToCacheKey extracts the logical cache key from a "cache:<key>:gen"
// Redis key name. Returns ("", false) when the payload doesn't match.
func genKeyToCacheKey(payload string) (string, bool) {
	const pfx = "cache:"
	const sfx = ":gen"
	if !strings.HasPrefix(payload, pfx) || !strings.HasSuffix(payload, sfx) {
		return "", false
	}
	inner := payload[len(pfx) : len(payload)-len(sfx)]
	if inner == "" {
		return "", false
	}
	return inner, true
}
