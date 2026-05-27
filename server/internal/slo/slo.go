// Package slo implements the Phase 9 §9.8 SLO definition and multi-window
// multi-burn-rate alerting (Google SRE Workbook recipe).
//
// SLO commitments (binding for §19 GA gate):
//
//   - Availability  >= 99.5 %  (error budget = 0.5 %)
//   - p95 cache-hit <= 250 ms
//   - p95 cache-miss (prediction) <= 800 ms
//   - Error rate    <= 0.5 %
//
// Burn-rate alert formula (per window):
//
//	burn_rate = error_fraction / ErrorBudget
//
//	warn     when burn_rate > cfg.APISLOBurnThreshold         (default 2.0)
//	critical when burn_rate > cfg.APISLOBurnThreshold x 3.0  (default 6.0)
//
// Two windows are evaluated on every check cycle:
//
//	short_window = APISLOBurnWindowS / 12  (300 s at the default 3600 s)
//	long_window  = APISLOBurnWindowS       (3600 s at the default)
//
// Either window exceeding the threshold fires the alert. Alerts are published
// as sec.alert.v1{kind=api_slo_burn, severity=warn|critical} via AlertFunc.
package slo

import (
	"context"
	"time"
)

// SLO commitments -- constants, not operator-configurable, so the §19 GA gate
// cannot be silently weakened via an env var.
const (
	// AvailabilityTarget is the minimum acceptable availability fraction (99.5 %).
	AvailabilityTarget = 0.995

	// ErrorBudget is the fraction of requests that may fail within the SLO
	// (1 - AvailabilityTarget = 0.005, i.e. 0.5 %).
	ErrorBudget = 1.0 - AvailabilityTarget

	// P95CacheHitMaxMs is the p95 latency ceiling for cache-hit reads (ms).
	P95CacheHitMaxMs = 250.0

	// P95CacheMissMaxMs is the p95 latency ceiling for cache-miss predictions (ms).
	P95CacheMissMaxMs = 800.0
)

// AlertFunc is called when a burn-rate threshold is exceeded.
// kind is always "api_slo_burn"; severity is "warn" or "critical".
type AlertFunc func(ctx context.Context, kind, severity string)

// RateFunc samples the error fraction for approximately the last windowSeconds
// of traffic. It returns (fraction, true) when there is sufficient data to
// produce a meaningful rate. It returns (0, false) when the window contains
// too few requests, so the check is skipped rather than alerting on noise.
type RateFunc func(windowSeconds int) (errorFraction float64, ok bool)

// CheckBurnRate performs a single two-window burn-rate evaluation and fires
// alertFn when a threshold is exceeded. It is the synchronous core of
// BurnRateMonitor and is exposed for direct use in tests.
//
// Parameters:
//   - ctx           -- passed through to alertFn unchanged.
//   - shortWindowS  -- short evaluation window in seconds (approx burnWindowS/12).
//   - longWindowS   -- long evaluation window in seconds  (approx burnWindowS).
//   - burnThreshold -- warn fires when burn_rate > this; critical fires at 3x.
//   - rateFn        -- samples error fraction; check is skipped when ok==false.
//   - alertFn       -- publisher for sec.alert.v1 events.
//
// The worst burn rate across both windows determines the severity. alertFn is
// called at most once per CheckBurnRate invocation.
func CheckBurnRate(
	ctx context.Context,
	shortWindowS, longWindowS int,
	burnThreshold float64,
	rateFn RateFunc,
	alertFn AlertFunc,
) {
	criticalThreshold := burnThreshold * 3.0

	var maxBurn float64
	hasData := false

	for _, windowS := range []int{shortWindowS, longWindowS} {
		fraction, ok := rateFn(windowS)
		if !ok {
			continue
		}
		burn := fraction / ErrorBudget
		if burn > maxBurn {
			maxBurn = burn
		}
		hasData = true
	}

	if !hasData {
		return
	}

	switch {
	case maxBurn > criticalThreshold:
		alertFn(ctx, "api_slo_burn", "critical")
	case maxBurn > burnThreshold:
		alertFn(ctx, "api_slo_burn", "warn")
	}
}

// BurnRateMonitor starts a background goroutine that calls CheckBurnRate every
// burnWindowS seconds until ctx is cancelled.
//
//   - short evaluation window: burnWindowS / 12 (300 s at the default 3600 s).
//   - long evaluation window:  burnWindowS.
//
// alertFn and rateFn must not be nil. The goroutine stops cleanly when ctx is
// cancelled; no channel or WaitGroup is required from the caller.
func BurnRateMonitor(
	ctx context.Context,
	burnWindowS int,
	burnThreshold float64,
	rateFn RateFunc,
	alertFn AlertFunc,
) {
	shortWindowS := burnWindowS / 12
	if shortWindowS < 1 {
		shortWindowS = 1
	}

	go func() {
		ticker := time.NewTicker(time.Duration(burnWindowS) * time.Second)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				CheckBurnRate(ctx, shortWindowS, burnWindowS, burnThreshold, rateFn, alertFn)
			}
		}
	}()
}
