package cache_test

import (
	"context"
	"net/http"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/redis/go-redis/v9"

	"github.com/metaphy6/negelir/server/internal/cache"
)

// defaultCfg returns a small L0Config suitable for unit tests.
func defaultCfg() cache.L0Config {
	return cache.L0Config{
		MaxEntries:         100,
		MaxBytes:           1 << 20, // 1 MiB
		MaxTTL:             30 * time.Second,
		NegativeCacheTTL:   10 * time.Second,
		RefreshMaxWait:     200 * time.Millisecond,
		InvalidationLagMax: 500 * time.Millisecond,
	}
}

// TestL0SetAndGet exercises the basic set/get path, TTL capping, and bytes tracking.
func TestL0SetAndGet(t *testing.T) {
	t.Parallel()
	l0, err := cache.NewL0(defaultCfg(), nil, nil)
	if err != nil {
		t.Fatalf("NewL0: %v", err)
	}

	// Set and immediately Get — should hit.
	l0.Set("key1", []byte("value1"), 5*time.Second, 0)
	val, ok, err := l0.Get(context.Background(), "key1")
	if err != nil {
		t.Fatalf("Get error: %v", err)
	}
	if !ok {
		t.Fatal("expected L0 hit after Set")
	}
	if string(val) != "value1" {
		t.Errorf("Get = %q; want %q", val, "value1")
	}

	// Missing key — should miss.
	_, ok, _ = l0.Get(context.Background(), "missing")
	if ok {
		t.Fatal("expected L0 miss for unknown key")
	}
}

// TestL0TTLCapping ensures effectiveTTL = min(provided, MaxTTL).
func TestL0TTLCapping(t *testing.T) {
	t.Parallel()
	cfg := defaultCfg()
	cfg.MaxTTL = 100 * time.Millisecond // tiny MaxTTL so we can observe expiry
	l0, _ := cache.NewL0(cfg, nil, nil)

	// TTL longer than MaxTTL — should be capped and expire quickly.
	l0.Set("k", []byte("v"), 30*time.Second, 0)
	if !l0.ContainsKey("k") {
		t.Fatal("expected key present immediately after Set")
	}
	time.Sleep(150 * time.Millisecond)
	if l0.ContainsKey("k") {
		t.Fatal("expected key expired after MaxTTL elapsed")
	}
}

// TestL0NegativeCache verifies that 404/410 are cached and 5xx are never cached.
func TestL0NegativeCache(t *testing.T) {
	t.Parallel()
	l0, _ := cache.NewL0(defaultCfg(), nil, nil)

	// 404 should be cached.
	l0.SetNegative("not-found", http.StatusNotFound)
	if s, ok := l0.GetNegative("not-found"); !ok || s != http.StatusNotFound {
		t.Errorf("GetNegative(not-found) = (%d, %v); want (404, true)", s, ok)
	}

	// 410 should be cached.
	l0.SetNegative("gone", http.StatusGone)
	if s, ok := l0.GetNegative("gone"); !ok || s != http.StatusGone {
		t.Errorf("GetNegative(gone) = (%d, %v); want (410, true)", s, ok)
	}

	// 500 must never be cached.
	l0.SetNegative("srv-err", http.StatusInternalServerError)
	if _, ok := l0.GetNegative("srv-err"); ok {
		t.Error("500 must not be stored in negative cache")
	}

	// Negative entries must not bleed through the positive Get path.
	_, ok, _ := l0.Get(context.Background(), "not-found")
	if ok {
		t.Error("negative-cache entry must not be returned by Get")
	}
}

// TestL0BytesCap verifies that the cache evicts oldest entries when MaxBytes
// would be exceeded, keeping totalBytes within bounds.
func TestL0BytesCap(t *testing.T) {
	t.Parallel()
	cfg := cache.L0Config{
		MaxEntries:         1000,
		MaxBytes:           200, // tiny cap — 200 bytes total
		MaxTTL:             30 * time.Second,
		NegativeCacheTTL:   10 * time.Second,
		RefreshMaxWait:     200 * time.Millisecond,
		InvalidationLagMax: 500 * time.Millisecond,
	}
	l0, _ := cache.NewL0(cfg, nil, nil)

	// Add 3 x 80-byte entries; only the most recent 2 should survive the cap.
	v80 := make([]byte, 80)
	l0.Set("a", v80, 30*time.Second, 0)
	l0.Set("b", v80, 30*time.Second, 0)
	l0.Set("c", v80, 30*time.Second, 0) // "a" should be evicted to make room

	if l0.ContainsKey("a") {
		t.Error("expected key 'a' to be evicted by bytes cap")
	}
	if !l0.ContainsKey("b") || !l0.ContainsKey("c") {
		t.Error("expected keys 'b' and 'c' to survive bytes cap")
	}
}

// TestL0StampedeProtection verifies that StartFetch/WaitForFetch/DoneFetch
// serialise concurrent fetches: only one goroutine is the designated fetcher.
func TestL0StampedeProtection(t *testing.T) {
	t.Parallel()
	l0, _ := cache.NewL0(defaultCfg(), nil, nil)

	const key = "stampede-key"
	const numWaiters = 20

	var fetchers atomic.Int32
	var wg sync.WaitGroup
	wg.Add(numWaiters)

	// Simulate numWaiters concurrent cache misses for the same key.
	for i := 0; i < numWaiters; i++ {
		go func() {
			defer wg.Done()
			if l0.StartFetch(key) {
				// This goroutine is the designated fetcher.
				fetchers.Add(1)
				time.Sleep(20 * time.Millisecond) // simulate fetch work
				l0.Set(key, []byte("result"), 5*time.Second, 0)
				l0.DoneFetch(key)
			} else {
				// This goroutine waits for the fetcher.
				l0.WaitForFetch(key, 200*time.Millisecond)
			}
		}()
	}

	wg.Wait()

	if n := fetchers.Load(); n != 1 {
		t.Errorf("expected exactly 1 fetcher goroutine, got %d", n)
	}
	if !l0.ContainsKey(key) {
		t.Error("expected key to be present after fetch completed")
	}
}

// TestL0WaitForFetchTimeout verifies that WaitForFetch returns false when
// the fetcher goroutine takes longer than maxWait.
func TestL0WaitForFetchTimeout(t *testing.T) {
	t.Parallel()
	l0, _ := cache.NewL0(defaultCfg(), nil, nil)

	const key = "slow-key"
	if !l0.StartFetch(key) {
		t.Fatal("expected to claim the fetch slot")
	}

	// Waiter with a 50ms timeout; the fetch never completes.
	start := time.Now()
	completed := l0.WaitForFetch(key, 50*time.Millisecond)
	elapsed := time.Since(start)

	if completed {
		t.Error("expected WaitForFetch to return false on timeout")
	}
	if elapsed < 40*time.Millisecond {
		t.Errorf("WaitForFetch returned too early: %v; want ≥ 40ms", elapsed)
	}
	if elapsed > 300*time.Millisecond {
		t.Errorf("WaitForFetch took too long: %v; want ≤ 300ms", elapsed)
	}

	// Clean up: signal done so no goroutine leaks.
	l0.DoneFetch(key)
}

// TestL0InvalidateDirectly verifies that Invalidate removes the entry.
func TestL0InvalidateDirectly(t *testing.T) {
	t.Parallel()
	l0, _ := cache.NewL0(defaultCfg(), nil, nil)

	l0.Set("x", []byte("data"), 30*time.Second, 0)
	if !l0.ContainsKey("x") {
		t.Fatal("expected key before invalidation")
	}
	l0.Invalidate("x")
	if l0.ContainsKey("x") {
		t.Error("expected key to be gone after Invalidate")
	}
}

// TestL0InvalidationWithin500ms is the §9.17.6 proof test.
//
// It stores a value in L0, then simulates a Redis keyspace notification by
// calling miniredis.Publish directly (miniredis does not auto-generate keyspace
// events on SET, so we use its Publish API to inject the exact message that real
// Redis would emit). The background listener must evict the entry within
// cfg.api_l0_invalidation_lag_max_ms (500ms).
func TestL0InvalidationWithin500ms(t *testing.T) {
	t.Parallel()

	mr, err := miniredis.Run()
	if err != nil {
		t.Fatalf("miniredis.Run: %v", err)
	}
	defer mr.Close()

	rdb := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	defer rdb.Close()

	cfg := cache.L0Config{
		MaxEntries:         100,
		MaxBytes:           1 << 20,
		MaxTTL:             30 * time.Second,
		NegativeCacheTTL:   10 * time.Second,
		RefreshMaxWait:     200 * time.Millisecond,
		InvalidationLagMax: 500 * time.Millisecond,
	}

	l0, err := cache.NewL0(cfg, rdb, nil)
	if err != nil {
		t.Fatalf("NewL0: %v", err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Start the background invalidation listener.
	l0.StartInvalidationListener(ctx)

	// Wait for the listener goroutine to establish its subscription with miniredis
	// before publishing the invalidation event. Without this, the Publish races
	// with the Subscribe handshake and the message is silently dropped.
	time.Sleep(80 * time.Millisecond)

	const cacheKey = "match:999"

	// Store the value in L0 with no gen tracking (gen=0).
	l0.Set(cacheKey, []byte(`{"id":999}`), 10*time.Second, 0)
	if !l0.ContainsKey(cacheKey) {
		t.Fatal("expected L0 hit immediately after Set")
	}

	// Simulate the Redis keyspace notification that real Redis would emit when
	// "cache:match:999:gen" is SET. Miniredis exposes Publish for this purpose.
	// The payload is the Redis key name, matching the "__keyevent@0__:set" channel.
	mr.Publish("__keyevent@0__:set", "cache:match:999:gen")

	// Assert eviction by the background listener within 500ms.
	deadline := time.Now().Add(500 * time.Millisecond)
	for time.Now().Before(deadline) {
		if !l0.ContainsKey(cacheKey) {
			return // evicted — proof test passes
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatalf("L0 entry for %q was not evicted within 500ms after keyspace notification", cacheKey)
}

// TestL0GenKeyToCacheKey_internal exercises the key-extraction helper via
// the observable behaviour of the invalidation loop (black-box test).
func TestL0InvalidationIgnoresNonGenKeys(t *testing.T) {
	t.Parallel()

	mr, err := miniredis.Run()
	if err != nil {
		t.Fatalf("miniredis.Run: %v", err)
	}
	defer mr.Close()

	rdb := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	defer rdb.Close()

	l0, _ := cache.NewL0(defaultCfg(), rdb, nil)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	l0.StartInvalidationListener(ctx)

	// Store a value under key "foo".
	l0.Set("foo", []byte("bar"), 30*time.Second, 0)

	// Publish an unrelated key to the keyevent channel — must NOT evict "foo".
	mr.Publish("__keyevent@0__:set", "some:other:key")
	time.Sleep(50 * time.Millisecond) // give listener time to process

	if !l0.ContainsKey("foo") {
		t.Error("L0 entry for 'foo' should not have been evicted by an unrelated key notification")
	}

	// Publish the exact gen key for "foo" — MUST evict "foo".
	mr.Publish("__keyevent@0__:set", "cache:foo:gen")
	deadline := time.Now().Add(500 * time.Millisecond)
	for time.Now().Before(deadline) {
		if !l0.ContainsKey("foo") {
			return // evicted as expected
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Error("L0 entry for 'foo' was not evicted after gen key notification")
}
