package sec

import (
	"context"
	"testing"
	"time"
)

func TestSecondaryBucketAllowsUnderCapacity(t *testing.T) {
	b := NewSecondaryBucket(10, 1.0, 100)
	dec, err := b.Check(context.Background(), "subject-a", 10, 1.0, 1)
	if err != nil {
		t.Fatalf("Check: %v", err)
	}
	if dec.Status != RateAllow {
		t.Fatalf("status = %s; want allow", dec.Status)
	}
	if !dec.UsedFallback {
		t.Fatal("secondary bucket must mark UsedFallback=true")
	}
	if dec.UsedTier != "secondary" {
		t.Fatalf("tier = %q; want secondary", dec.UsedTier)
	}
	if dec.CostCharged != 1 {
		t.Fatalf("cost charged = %d; want 1", dec.CostCharged)
	}
}

func TestSecondaryBucketThrottlesWhenEmpty(t *testing.T) {
	b := NewSecondaryBucket(2, 1.0, 100)
	ctx := context.Background()
	// drain
	for i := 0; i < 2; i++ {
		dec, _ := b.Check(ctx, "drain", 2, 1.0, 1)
		if dec.Status != RateAllow {
			t.Fatalf("drain %d: %s", i, dec.Status)
		}
	}
	dec, _ := b.Check(ctx, "drain", 2, 1.0, 1)
	if dec.Status != RateThrottle {
		t.Fatalf("expected throttle, got %s", dec.Status)
	}
	if dec.RetryAfter <= 0 {
		t.Fatalf("expected positive retry-after, got %v", dec.RetryAfter)
	}
}

func TestSecondaryBucketNeverDenies(t *testing.T) {
	// Denylist enforcement is Redis-only. The fail-open tier must
	// only ever return allow / throttle.
	b := NewSecondaryBucket(1, 1.0, 100)
	ctx := context.Background()
	for i := 0; i < 50; i++ {
		dec, _ := b.Check(ctx, "spammer", 1, 1.0, 1)
		if dec.Status == RateDenied {
			t.Fatalf("secondary tier must never deny; iter %d", i)
		}
	}
}

func TestSecondaryBucketZeroCostAlwaysAllows(t *testing.T) {
	b := NewSecondaryBucket(1, 1.0, 100)
	dec, _ := b.Check(context.Background(), "anyone", 1, 1.0, 0)
	if dec.Status != RateAllow {
		t.Fatalf("zero cost must allow, got %s", dec.Status)
	}
	if dec.CostCharged != 0 {
		t.Fatalf("zero cost must charge zero, got %d", dec.CostCharged)
	}
}

func TestSecondaryBucketRefillsOverTime(t *testing.T) {
	b := NewSecondaryBucket(5, 100.0, 100) // 100 tok/s — fast refill for tests
	ctx := context.Background()
	// Drain to zero.
	for i := 0; i < 5; i++ {
		_, _ = b.Check(ctx, "x", 5, 100.0, 1)
	}
	// Wait long enough to refill at least one token.
	time.Sleep(50 * time.Millisecond)
	dec, _ := b.Check(ctx, "x", 5, 100.0, 1)
	if dec.Status != RateAllow {
		t.Fatalf("expected allow after refill, got %s", dec.Status)
	}
}

func TestSecondaryBucketEvictionRespectsMaxKeys(t *testing.T) {
	b := NewSecondaryBucket(10, 1.0, 3)
	ctx := context.Background()
	for i, sub := range []string{"a", "b", "c", "d", "e"} {
		_, _ = b.Check(ctx, sub, 10, 1.0, 1)
		if i >= 3 && b.Size() > 3 {
			t.Fatalf("LRU cap violated at iter %d: size=%d", i, b.Size())
		}
	}
	if b.Size() != 3 {
		t.Fatalf("final size = %d; want 3", b.Size())
	}
}

func TestSecondaryBucketSubjectsIsolated(t *testing.T) {
	b := NewSecondaryBucket(1, 1.0, 100)
	ctx := context.Background()
	if d, _ := b.Check(ctx, "alice", 1, 1.0, 1); d.Status != RateAllow {
		t.Fatalf("alice first call must allow, got %s", d.Status)
	}
	// Bob has his own bucket; alice draining hers must not affect bob.
	if d, _ := b.Check(ctx, "bob", 1, 1.0, 1); d.Status != RateAllow {
		t.Fatalf("bob first call must allow, got %s", d.Status)
	}
}
