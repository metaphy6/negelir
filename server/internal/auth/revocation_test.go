package auth_test

import (
	"context"
	"sync"
	"testing"
	"time"

	"github.com/metaphy6/negelir/server/internal/auth"
)

// -- in-memory RevocationRedis stub ------------------------------------------

type memRevRedis struct {
	mu     sync.Mutex
	kv     map[string]string
	sorted map[string][]scoredMember // key → sorted slice by score
}

type scoredMember struct {
	score  float64
	member string
}

func newMemRevRedis() *memRevRedis {
	return &memRevRedis{kv: make(map[string]string), sorted: make(map[string][]scoredMember)}
}

func (r *memRevRedis) Exists(_ context.Context, key string) (bool, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	_, ok := r.kv[key]
	return ok, nil
}

func (r *memRevRedis) Set(_ context.Context, key, value string, _ time.Duration) error {
	r.mu.Lock()
	r.kv[key] = value
	r.mu.Unlock()
	return nil
}

func (r *memRevRedis) Del(_ context.Context, key string) error {
	r.mu.Lock()
	delete(r.kv, key)
	r.mu.Unlock()
	return nil
}

func (r *memRevRedis) ZAdd(_ context.Context, key string, score float64, member string) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	// Insert in score-sorted order (insertion sort on small slices is fine for tests).
	s := r.sorted[key]
	for _, m := range s {
		if m.member == member {
			return nil // already present; ignore
		}
	}
	newMember := scoredMember{score: score, member: member}
	inserted := false
	for i, m := range s {
		if newMember.score < m.score {
			r.sorted[key] = append(s[:i], append([]scoredMember{newMember}, s[i:]...)...)
			inserted = true
			break
		}
	}
	if !inserted {
		r.sorted[key] = append(s, newMember)
	}
	return nil
}

func (r *memRevRedis) ZCard(_ context.Context, key string) (int64, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	return int64(len(r.sorted[key])), nil
}

func (r *memRevRedis) ZRangeByRank(_ context.Context, key string, start, stop int64) ([]string, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	s := r.sorted[key]
	n := int64(len(s))
	if start < 0 || start >= n {
		return nil, nil
	}
	if stop >= n {
		stop = n - 1
	}
	out := make([]string, 0, stop-start+1)
	for i := start; i <= stop; i++ {
		out = append(out, s[i].member)
	}
	return out, nil
}

func (r *memRevRedis) ZRemRangeByRank(_ context.Context, key string, start, stop int64) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	s := r.sorted[key]
	n := int64(len(s))
	if start < 0 || start >= n {
		return nil
	}
	if stop >= n {
		stop = n - 1
	}
	r.sorted[key] = append(s[:start], s[stop+1:]...)
	return nil
}

// -- tests -------------------------------------------------------------------

func newRevStore(max int64, alertFn auth.RevocationAlertFunc) (*auth.RevocationStore, *memRevRedis) {
	r := newMemRevRedis()
	return auth.NewRevocationStore(r, max, alertFn), r
}

func TestRevocationStore_Revoke_StoresKey(t *testing.T) {
	s, r := newRevStore(100, nil)
	ctx := context.Background()

	if err := s.Revoke(ctx, "jti-001", 900*time.Second); err != nil {
		t.Fatalf("Revoke: %v", err)
	}

	r.mu.Lock()
	_, ok := r.kv["auth:rev:jti-001"]
	r.mu.Unlock()
	if !ok {
		t.Error("auth:rev:jti-001 not found in Redis after Revoke")
	}
}

func TestRevocationStore_IsRevoked_True(t *testing.T) {
	s, _ := newRevStore(100, nil)
	ctx := context.Background()
	_ = s.Revoke(ctx, "jti-002", 900*time.Second)

	revoked, err := s.IsRevoked(ctx, "jti-002")
	if err != nil {
		t.Fatalf("IsRevoked: %v", err)
	}
	if !revoked {
		t.Error("IsRevoked returned false for a revoked JTI")
	}
}

func TestRevocationStore_IsRevoked_False_UnknownJTI(t *testing.T) {
	s, _ := newRevStore(100, nil)
	ctx := context.Background()

	revoked, err := s.IsRevoked(ctx, "jti-unknown")
	if err != nil {
		t.Fatalf("IsRevoked: %v", err)
	}
	if revoked {
		t.Error("IsRevoked returned true for an unknown JTI")
	}
}

func TestRevocationStore_Revoke_Noop_ExpiredToken(t *testing.T) {
	s, r := newRevStore(100, nil)
	ctx := context.Background()

	if err := s.Revoke(ctx, "jti-expired", 0); err != nil {
		t.Fatalf("Revoke with TTL=0 must not error, got: %v", err)
	}
	r.mu.Lock()
	_, ok := r.kv["auth:rev:jti-expired"]
	r.mu.Unlock()
	if ok {
		t.Error("Revoke with TTL=0 must not store a key")
	}
}

func TestRevocationStore_Revoke_Noop_NegativeTTL(t *testing.T) {
	s, r := newRevStore(100, nil)
	ctx := context.Background()

	if err := s.Revoke(ctx, "jti-neg", -1*time.Second); err != nil {
		t.Fatalf("Revoke with negative TTL must not error, got: %v", err)
	}
	r.mu.Lock()
	_, ok := r.kv["auth:rev:jti-neg"]
	r.mu.Unlock()
	if ok {
		t.Error("Revoke with negative TTL must not store a key")
	}
}

func TestRevocationStore_LRU_Eviction(t *testing.T) {
	// max=3: on the 4th revoke the oldest entry should be evicted.
	s, r := newRevStore(3, nil)
	ctx := context.Background()

	for i, jti := range []string{"jti-a", "jti-b", "jti-c"} {
		// Spread scores slightly so order is deterministic.
		time.Sleep(time.Duration(i) * time.Microsecond)
		_ = s.Revoke(ctx, jti, 900*time.Second)
	}

	// Fourth entry triggers eviction of "jti-a" (lowest score = oldest).
	_ = s.Revoke(ctx, "jti-d", 900*time.Second)

	r.mu.Lock()
	_, hasA := r.kv["auth:rev:jti-a"]
	_, hasD := r.kv["auth:rev:jti-d"]
	r.mu.Unlock()

	if hasA {
		t.Error("oldest entry jti-a was not evicted after cap exceeded")
	}
	if !hasD {
		t.Error("newest entry jti-d should remain after eviction")
	}
}

func TestRevocationStore_PressureAlert_Above80Pct(t *testing.T) {
	var alertKind string
	fn := func(_ context.Context, kind, _ string) { alertKind = kind }

	// max=10; add 9 entries → 90% → must alert.
	s, _ := newRevStore(10, fn)
	ctx := context.Background()

	for i := 0; i < 9; i++ {
		_ = s.Revoke(ctx, "jti-p"+string(rune('a'+i)), 900*time.Second)
	}

	if alertKind != "jti_revocation_set_pressure" {
		t.Errorf("expected jti_revocation_set_pressure alert, got %q", alertKind)
	}
}

func TestRevocationStore_NoPressureAlert_Below80Pct(t *testing.T) {
	called := false
	fn := func(_ context.Context, _, _ string) { called = true }

	// max=10; add 7 entries → 70% → must NOT alert.
	s, _ := newRevStore(10, fn)
	ctx := context.Background()

	for i := 0; i < 7; i++ {
		_ = s.Revoke(ctx, "jti-q"+string(rune('a'+i)), 900*time.Second)
	}

	if called {
		t.Error("pressure alert must not fire at 70% capacity")
	}
}

func TestRevocationStore_CheckPressure_ReturnsCount(t *testing.T) {
	s, _ := newRevStore(100, nil)
	ctx := context.Background()
	_ = s.Revoke(ctx, "jti-r1", 900*time.Second)
	_ = s.Revoke(ctx, "jti-r2", 900*time.Second)

	count, err := s.CheckPressure(ctx)
	if err != nil {
		t.Fatalf("CheckPressure: %v", err)
	}
	if count != 2 {
		t.Errorf("expected count=2, got %d", count)
	}
}

// ─── §9.14 proof tests ────────────────────────────────────────────────────────

// TestJTIRevocationImmediate — §9.14 test_jti_revocation_immediate:
// Revoke a live token; IsRevoked must return true within < 50ms
// (exercising the Redis EXISTS fast-path on the in-memory stub).
func TestJTIRevocationImmediate(t *testing.T) {
	s, _ := newRevStore(100, nil)
	ctx := context.Background()

	const jti = "jti-proof-immediate"

	start := time.Now()
	if err := s.Revoke(ctx, jti, 900*time.Second); err != nil {
		t.Fatalf("Revoke: %v", err)
	}
	revoked, err := s.IsRevoked(ctx, jti)
	elapsed := time.Since(start)

	if err != nil {
		t.Fatalf("IsRevoked: %v", err)
	}
	if !revoked {
		t.Error("IsRevoked must return true immediately after Revoke")
	}
	if elapsed > 50*time.Millisecond {
		t.Errorf("IsRevoked took %v — must complete in < 50ms (Redis EXISTS fast-path)", elapsed)
	}
}

// TestJTIRevocationSetPressureAlert — §9.14 test_jti_revocation_set_pressure_alert:
// Fill the revocation set to > 80% of max; assert the alertFn is emitted
// with kind="jti_revocation_set_pressure" and severity="warn".
func TestJTIRevocationSetPressureAlert(t *testing.T) {
	var alertKind, alertSeverity string
	alertFn := auth.RevocationAlertFunc(func(_ context.Context, kind, severity string) {
		alertKind = kind
		alertSeverity = severity
	})

	const max = 10
	s, _ := newRevStore(max, alertFn)
	ctx := context.Background()

	// Revoke enough tokens to cross the 80% threshold (9 out of 10 = 90%).
	// The alert fires when count > 80% of max, i.e. count > 8.
	for i := 0; i < max-1; i++ {
		jti := "jti-pressure-" + string(rune('a'+i))
		if err := s.Revoke(ctx, jti, 900*time.Second); err != nil {
			t.Fatalf("Revoke[%d]: %v", i, err)
		}
	}

	if alertKind == "" {
		t.Fatal("alert must fire when revocation set exceeds 80% capacity")
	}
	if alertKind != "jti_revocation_set_pressure" {
		t.Errorf("alert kind: want %q, got %q", "jti_revocation_set_pressure", alertKind)
	}
	if alertSeverity != "warn" {
		t.Errorf("alert severity: want %q, got %q", "warn", alertSeverity)
	}
}

