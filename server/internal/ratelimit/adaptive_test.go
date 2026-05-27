package ratelimit

import (
	"context"
	"sync"
	"testing"
	"time"

	"github.com/metaphy6/negelir/server/internal/sec"
)

// stubAdaptiveCfg is a test double for AdaptiveCfg.
type stubAdaptiveCfg struct {
	threshold     float64
	shedFactor    float64
	shedDurationS int
}

func (s *stubAdaptiveCfg) AdaptiveErrorRateThreshold() float64 { return s.threshold }
func (s *stubAdaptiveCfg) AdaptiveShedFactor() float64         { return s.shedFactor }
func (s *stubAdaptiveCfg) AdaptiveShedDuration() time.Duration {
	return time.Duration(s.shedDurationS) * time.Second
}

// TestAdaptiveShedEngagesOnErrorBurst is the §9.17.9 proof test.
//
// Synthesises a 5xx burst against a controller whose threshold is 2%.
// After 7 normal + 3 error responses (30% error rate), Evaluate() must:
//   - halve the multiplier to 0.5 (AdaptiveShedFactor),
//   - fire an api_adaptive_shed_engaged alert.
//
// Then advances the mock clock past shedUntil and verifies the gradual
// restoration path (x1.1 per 10 s, alert lifted once multiplier >= 1.0).
func TestAdaptiveShedEngagesOnErrorBurst(t *testing.T) {
	t.Parallel()

	baseTime := time.Unix(1_000_000, 0)
	now := baseTime
	mockNow := func() time.Time { return now }

	cfg := &stubAdaptiveCfg{
		threshold:     0.02, // 2%
		shedFactor:    0.5,
		shedDurationS: 60,
	}

	var (
		alertMu    sync.Mutex
		alertKinds []string
	)
	alert := func(_ context.Context, kind, _ string) {
		alertMu.Lock()
		defer alertMu.Unlock()
		alertKinds = append(alertKinds, kind)
	}

	ctrl := newAdaptiveController(cfg, alert, mockNow)

	// Phase 1: inject 30% error burst.
	for i := 0; i < 7; i++ {
		ctrl.RecordResponse(200)
	}
	for i := 0; i < 3; i++ {
		ctrl.RecordResponse(503) // 3/10 = 30% >> 2% threshold
	}

	// Evaluate should engage shedding.
	ctrl.Evaluate()

	if got := ctrl.ShedMultiplier(); got != cfg.shedFactor {
		t.Fatalf("shed_factor: want %.2f, got %.2f", cfg.shedFactor, got)
	}

	alertMu.Lock()
	firstKind := ""
	if len(alertKinds) > 0 {
		firstKind = alertKinds[0]
	}
	alertMu.Unlock()

	if firstKind != "api_adaptive_shed_engaged" {
		t.Fatalf("alert: want api_adaptive_shed_engaged, got %q", firstKind)
	}

	// Phase 2: multiplier stays at shed_factor during shed window.
	now = now.Add(30 * time.Second) // still inside shedUntil (60 s window)
	ctrl.Evaluate()
	if got := ctrl.ShedMultiplier(); got != cfg.shedFactor {
		t.Fatalf("mid-shed multiplier: want %.2f, got %.2f", cfg.shedFactor, got)
	}

	// Phase 3: advance past shedUntil and drive the restore phase.
	now = now.Add(35 * time.Second) // 65 s total: past shedUntil=60 s
	ctrl.Evaluate()                 // sets restoreAt = now+10 s

	// Multiplier still at shed_factor; restore step not due yet.
	if got := ctrl.ShedMultiplier(); got != cfg.shedFactor {
		t.Fatalf("post-shedUntil (before restoreAt) multiplier: want %.2f, got %.2f",
			cfg.shedFactor, got)
	}

	now = now.Add(11 * time.Second) // past restoreAt
	ctrl.Evaluate()                 // applies x1.1

	if got := ctrl.ShedMultiplier(); got <= cfg.shedFactor {
		t.Fatalf("after one restore step: want > %.2f, got %.2f", cfg.shedFactor, got)
	}

	// Phase 4: drive restore steps until shed is fully lifted.
	for i := 0; i < 20; i++ {
		now = now.Add(11 * time.Second)
		ctrl.Evaluate()
		if ctrl.ShedMultiplier() >= 1.0 {
			break
		}
	}

	if got := ctrl.ShedMultiplier(); got != 1.0 {
		t.Fatalf("fully restored: want 1.0, got %.4f", got)
	}

	alertMu.Lock()
	var liftedFound bool
	for _, k := range alertKinds {
		if k == "api_adaptive_shed_lifted" {
			liftedFound = true
		}
	}
	alertMu.Unlock()

	if !liftedFound {
		t.Fatalf("alert api_adaptive_shed_lifted never fired; alerts: %v", alertKinds)
	}
}

// TestAdaptiveController_NoShedBelowThreshold verifies a low error rate leaves
// the multiplier at 1.0 and fires no alerts.
func TestAdaptiveController_NoShedBelowThreshold(t *testing.T) {
	t.Parallel()

	now := time.Unix(2_000_000, 0)
	cfg := &stubAdaptiveCfg{threshold: 0.02, shedFactor: 0.5, shedDurationS: 60}

	var fired bool
	ctrl := newAdaptiveController(cfg, func(_ context.Context, _, _ string) { fired = true }, func() time.Time { return now })

	// 999 successes + 1 error = 0.1% — well below 2%.
	for i := 0; i < 999; i++ {
		ctrl.RecordResponse(200)
	}
	ctrl.RecordResponse(500)
	ctrl.Evaluate()

	if got := ctrl.ShedMultiplier(); got != 1.0 {
		t.Fatalf("low error rate: want 1.0, got %.4f", got)
	}
	if fired {
		t.Fatal("no alert must fire below threshold")
	}
}

// TestAdaptiveRateChecker_ScalesRefillRate verifies that AdaptiveRateChecker
// passes refillPerS * ShedMultiplier() to the inner checker.
func TestAdaptiveRateChecker_ScalesRefillRate(t *testing.T) {
	t.Parallel()

	now := time.Unix(3_000_000, 0)
	cfg := &stubAdaptiveCfg{threshold: 0.01, shedFactor: 0.5, shedDurationS: 60}
	ctrl := newAdaptiveController(cfg, nil, func() time.Time { return now })

	// Force shedding with a 100% error rate.
	ctrl.RecordResponse(500)
	ctrl.Evaluate()

	var capturedRefill float64
	stub := &captureRateChecker{
		onCheck: func(_ string, _ int, refill float64, _ int) {
			capturedRefill = refill
		},
	}
	checker := &AdaptiveRateChecker{Inner: stub, Controller: ctrl}
	_, _ = checker.Check(context.Background(), "subject", 100, 10.0, 1)

	wantRefill := 10.0 * 0.5
	if capturedRefill != wantRefill {
		t.Fatalf("scaled refill: want %.2f, got %.2f", wantRefill, capturedRefill)
	}
}

// captureRateChecker implements sec.RateChecker and captures call arguments.
type captureRateChecker struct {
	onCheck func(subject string, capacity int, refillPerS float64, cost int)
}

func (c *captureRateChecker) Check(
	_ context.Context,
	subject string,
	capacity int,
	refillPerS float64,
	cost int,
) (sec.RateDecision, error) {
	if c.onCheck != nil {
		c.onCheck(subject, capacity, refillPerS, cost)
	}
	return sec.RateDecision{Status: sec.RateAllow}, nil
}
