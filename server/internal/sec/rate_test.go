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

// ── BuildThrottleResponse (ROADMAP §7.3) ─────────────────────────

func TestBuildThrottleResponse_ThrottleReturns429(t *testing.T) {
	d := RateDecision{Status: RateThrottle, RetryAfter: 2500 * time.Millisecond}
	status, headers, body := BuildThrottleResponse(d, "")
	if status != 429 {
		t.Fatalf("expected 429, got %d", status)
	}
	if headers["Retry-After"] != "3" {
		t.Fatalf("expected Retry-After=3 (ceiling of 2.5s), got %q", headers["Retry-After"])
	}
	if got := headers["Content-Type"]; got != "application/json; charset=utf-8" {
		t.Fatalf("bad content-type: %q", got)
	}
	want := `{"error":"rate_limited","retry_after_ms":2500,"reason":"rate_limited"}`
	if string(body) != want {
		t.Fatalf("body mismatch:\n got %s\nwant %s", body, want)
	}
}

func TestBuildThrottleResponse_DeniedReturns403(t *testing.T) {
	d := RateDecision{Status: RateDenied, RetryAfter: 60 * time.Second}
	status, headers, body := BuildThrottleResponse(d, "denylisted_ip")
	if status != 403 {
		t.Fatalf("expected 403, got %d", status)
	}
	if headers["Retry-After"] != "60" {
		t.Fatalf("expected Retry-After=60, got %q", headers["Retry-After"])
	}
	want := `{"error":"denylisted","retry_after_ms":60000,"reason":"denylisted_ip"}`
	if string(body) != want {
		t.Fatalf("body mismatch:\n got %s\nwant %s", body, want)
	}
}

func TestBuildThrottleResponse_AllowReturnsZero(t *testing.T) {
	d := RateDecision{Status: RateAllow}
	status, headers, body := BuildThrottleResponse(d, "")
	if status != 0 || headers != nil || body != nil {
		t.Fatalf("allow path must short-circuit; got status=%d headers=%v body=%s",
			status, headers, body)
	}
}

func TestBuildThrottleResponse_ErrorReturnsZero(t *testing.T) {
	// RateError means the rate-checker itself failed; the gateway
	// must NOT auto-throttle (that's a fail-open call) — refuse to
	// fabricate a throttle response.
	d := RateDecision{Status: RateError}
	status, _, _ := BuildThrottleResponse(d, "")
	if status != 0 {
		t.Fatalf("error must short-circuit; got status=%d", status)
	}
}

func TestBuildThrottleResponse_RetryAfterCeiling(t *testing.T) {
	// 1ms must round up to 1s, not 0 (RFC 6585: clients treat 0 as
	// "no advice", which would be misleading).
	d := RateDecision{Status: RateThrottle, RetryAfter: 1 * time.Millisecond}
	_, headers, _ := BuildThrottleResponse(d, "")
	if headers["Retry-After"] != "1" {
		t.Fatalf("expected Retry-After=1 (ceiling of 1ms), got %q",
			headers["Retry-After"])
	}
}

func TestBuildThrottleResponse_NegativeRetryAfterClamped(t *testing.T) {
	d := RateDecision{Status: RateThrottle, RetryAfter: -5 * time.Second}
	_, headers, body := BuildThrottleResponse(d, "")
	if headers["Retry-After"] != "0" {
		t.Fatalf("expected Retry-After=0, got %q", headers["Retry-After"])
	}
	if want := `{"error":"rate_limited","retry_after_ms":0,"reason":"rate_limited"}`; string(body) != want {
		t.Fatalf("body mismatch: got %s", body)
	}
}

func TestBuildThrottleResponse_ReasonEscaped(t *testing.T) {
	// Adversarial: an operator-supplied reason carrying control
	// characters / quote must be escaped so we don't break the
	// JSON envelope.
	d := RateDecision{Status: RateThrottle, RetryAfter: 1 * time.Second}
	_, _, body := BuildThrottleResponse(d, `"evil\nreason`)
	want := `{"error":"rate_limited","retry_after_ms":1000,"reason":"\"evil\\nreason"}`
	if string(body) != want {
		t.Fatalf("escape mismatch: got %s\nwant %s", body, want)
	}
}
