// Package ratelimit provides §9.17.9 adaptive-shedding components that sit on
// top of the §9.7 fixed token-bucket rate limiters.
//
// # AdaptiveController
//
// Tracks the fraction of 5xx responses over a 30-second sliding window.
// When the error rate exceeds AdaptiveCfg.AdaptiveErrorRateThreshold, the
// controller enters "shed mode":
//   - ShedMultiplier() returns AdaptiveCfg.AdaptiveShedFactor (e.g. 0.5).
//   - The rate middleware multiplies the refillPerS argument by this factor
//     before calling the primary Redis bucket, effectively halving the allowed
//     request rate until error pressure subsides.
//   - A sec.alert.v1{kind=api_adaptive_shed_engaged} alert fires.
//
// After AdaptiveCfg.AdaptiveShedDuration the multiplier is restored gradually
// (x1.1 per 10 s) until it reaches 1.0, at which point
// sec.alert.v1{kind=api_adaptive_shed_lifted} fires.
//
// # AdaptiveRateChecker
//
// A transparent wrapper over any sec.RateChecker that applies the
// AdaptiveController's current multiplier to the refillPerS argument.
// Drop it in as the primary checker in the RateLimiter middleware instead of
// the plain RedisRateChecker.
package ratelimit

import (
	"context"
	"sync"
	"time"

	"github.com/metaphy6/negelir/server/internal/sec"
)

// AdaptiveCfg is the minimal config surface the AdaptiveController reads.
// *config.Config satisfies this interface via the §9.17.9 methods added to
// server/internal/config.
type AdaptiveCfg interface {
	AdaptiveErrorRateThreshold() float64
	AdaptiveShedFactor() float64
	AdaptiveShedDuration() time.Duration
}

// AlertFunc is the sec.alert.v1 emission callback injected from cmd/api.
// kind is one of "api_adaptive_shed_engaged", "api_adaptive_shed_lifted".
// severity is "warn" for both adaptive shed events.
type AlertFunc func(ctx context.Context, kind, severity string)

const adaptiveWindowSize = 30 // seconds in the sliding window

// windowBucket holds request counts for a single wall-clock second.
type windowBucket struct {
	ts     int64 // Unix second this bucket was written
	total  int64 // all responses recorded in this second
	errors int64 // 5xx responses recorded in this second
}

// AdaptiveController measures the 5xx error rate over a 30 s sliding window
// and adjusts the refill-rate multiplier accordingly.
//
// Concurrency: RecordResponse, Evaluate, ShedMultiplier, Start, and Stop are
// all safe for concurrent use. The background goroutine started by Start calls
// Evaluate every second.
type AdaptiveController struct {
	mu         sync.Mutex
	buckets    [adaptiveWindowSize]windowBucket
	multiplier float64
	shedActive bool
	shedUntil  time.Time // end of forced shed window
	restoreAt  time.Time // next x1.1 step; zero = not yet in restore phase

	cfg   AdaptiveCfg
	alert AlertFunc
	now   func() time.Time

	stop chan struct{}
	wg   sync.WaitGroup
}

// NewAdaptiveController builds a production controller using time.Now.
func NewAdaptiveController(cfg AdaptiveCfg, alert AlertFunc) *AdaptiveController {
	return newAdaptiveController(cfg, alert, time.Now)
}

// newAdaptiveController is the internal constructor with clock injection for
// deterministic unit tests (unexported so tests in package ratelimit can use it).
func newAdaptiveController(cfg AdaptiveCfg, alert AlertFunc, now func() time.Time) *AdaptiveController {
	return &AdaptiveController{
		cfg:        cfg,
		alert:      alert,
		now:        now,
		multiplier: 1.0,
		stop:       make(chan struct{}),
	}
}

// RecordResponse records one completed response. statusCode >= 500 increments
// the 5xx counter in the current second's window bucket.
// Thread-safe; called after every request by RecordAdaptiveFeedback.
func (a *AdaptiveController) RecordResponse(statusCode int) {
	nowSec := a.now().Unix()
	idx := int(nowSec % adaptiveWindowSize)

	a.mu.Lock()
	defer a.mu.Unlock()

	b := &a.buckets[idx]
	if b.ts != nowSec {
		// Stale bucket from a previous cycle — reset for the current second.
		b.ts = nowSec
		b.total = 0
		b.errors = 0
	}
	b.total++
	if statusCode >= 500 {
		b.errors++
	}
}

// ShedMultiplier returns the current refill-rate multiplier.
// Returns 1.0 normally, AdaptiveCfg.AdaptiveShedFactor() while shedding,
// and a value between the two during gradual restoration.
func (a *AdaptiveController) ShedMultiplier() float64 {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.multiplier
}

// Evaluate samples the error rate and updates shed state. Called every second
// by the background goroutine; also exported so tests can drive the controller
// deterministically without a real ticker.
func (a *AdaptiveController) Evaluate() {
	a.mu.Lock()
	defer a.mu.Unlock()

	now := a.now()
	rate := a.errorRateLocked()
	threshold := a.cfg.AdaptiveErrorRateThreshold()

	if !a.shedActive {
		if rate > threshold {
			// Engage shedding.
			a.shedActive = true
			a.multiplier = a.cfg.AdaptiveShedFactor()
			a.shedUntil = now.Add(a.cfg.AdaptiveShedDuration())
			a.restoreAt = time.Time{} // set once shedUntil passes
			if a.alert != nil {
				a.alert(context.Background(), "api_adaptive_shed_engaged", "warn")
			}
		}
		return
	}

	// Shedding is active — are we still in the forced shed window?
	if now.Before(a.shedUntil) {
		return
	}

	// Post-shed window: restore gradually (x1.1 per 10 s).
	if a.restoreAt.IsZero() {
		// First evaluation after shedUntil — schedule first restore step.
		a.restoreAt = now.Add(10 * time.Second)
		return
	}

	if now.Before(a.restoreAt) {
		return // restore step not due yet
	}

	// Apply one restoration step.
	a.multiplier *= 1.1
	a.restoreAt = now.Add(10 * time.Second)

	if a.multiplier >= 1.0 {
		a.multiplier = 1.0
		a.shedActive = false
		a.restoreAt = time.Time{}
		if a.alert != nil {
			a.alert(context.Background(), "api_adaptive_shed_lifted", "warn")
		}
	}
}

// errorRateLocked computes the 5xx fraction over the current sliding window.
// Must be called with a.mu held.
func (a *AdaptiveController) errorRateLocked() float64 {
	nowSec := a.now().Unix()
	cutoff := nowSec - adaptiveWindowSize + 1

	var total, errors int64
	for _, b := range a.buckets {
		if b.ts >= cutoff && b.ts <= nowSec {
			total += b.total
			errors += b.errors
		}
	}
	if total == 0 {
		return 0
	}
	return float64(errors) / float64(total)
}

// Start launches the background ticker that calls Evaluate every second.
// The goroutine exits when ctx is cancelled or Stop is called.
func (a *AdaptiveController) Start(ctx context.Context) {
	a.wg.Add(1)
	go func() {
		defer a.wg.Done()
		ticker := time.NewTicker(time.Second)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-a.stop:
				return
			case <-ticker.C:
				a.Evaluate()
			}
		}
	}()
}

// Stop shuts down the background goroutine and blocks until it exits.
func (a *AdaptiveController) Stop() {
	close(a.stop)
	a.wg.Wait()
}

// AdaptiveRateChecker wraps any sec.RateChecker and scales refillPerS by the
// AdaptiveController's current ShedMultiplier before delegating. Drop it in as
// the primary checker in the RateLimiter middleware to apply adaptive shedding
// transparently.
type AdaptiveRateChecker struct {
	Inner      sec.RateChecker
	Controller *AdaptiveController
}

// Check implements sec.RateChecker.
func (a *AdaptiveRateChecker) Check(
	ctx context.Context,
	subject string,
	capacity int,
	refillPerS float64,
	cost int,
) (sec.RateDecision, error) {
	mult := a.Controller.ShedMultiplier()
	return a.Inner.Check(ctx, subject, capacity, refillPerS*mult, cost)
}
