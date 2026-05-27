// alloc_tracker.go — §9.17.10 allocation-tracking middleware.
//
// ObserveAlloc returns a net/http middleware that measures the runtime
// allocation delta (bytes) for a sampled fraction of requests and records the
// observation to the api_alloc_per_request_bytes histogram. When the p99 of
// the histogram exceeds the 50 KiB regression threshold the middleware emits a
// sec.alert.v1{kind=api_alloc_regression, severity=warn} event via the
// provided alertFn (nil-safe — if alertFn is nil the histogram is updated but
// no alert is fired).
//
// Sampling is controlled by sampleRate (cfg.api_alloc_sample_rate, default
// 0.001). Set to 0 to disable entirely. Set to 1 to sample every request
// (useful in tests and benchmarks).
//
// Implementation notes:
//   - We snapshot runtime.MemStats.TotalAlloc (cumulative bytes allocated by
//     the runtime since process start) BEFORE and AFTER the downstream handler.
//     The delta is the allocation made on the goroutine stack + heap during
//     that handler call. This is a lower-bound approximation: cross-goroutine
//     allocations (e.g. async SWR refresh) are excluded.
//   - runtime.ReadMemStats triggers a STW pause. At sampleRate=0.001 the
//     expected pause overhead is < 1% CPU under any realistic load.
//   - The alert threshold is the fixed p99 boundary of 50 KiB (51200 bytes)
//     defined by §9.17.10. The middleware checks the current observation (not
//     a running quantile) because Prometheus p99 is computed by the scrape
//     consumer; emitting an alert on every individual observation that exceeds
//     the threshold is intentionally conservative and self-deduplicating via
//     the alertFn debounce contract.
package metrics

import (
	"math/rand/v2"
	"net/http"
	"runtime"
)

// allocRegressionThresholdBytes is the §9.17.10 p99 regression ceiling.
const allocRegressionThresholdBytes = 50 << 10 // 50 KiB

// AlertFunc is the callback invoked when an allocation regression is detected.
// kind is always "api_alloc_regression"; severity is "warn". Implementations
// must be non-blocking (the middleware does not wait for the alert to be
// delivered).
type AlertFunc func(kind, severity string)

// ObserveAlloc returns a net/http middleware that instruments allocation
// deltas for a random fraction (sampleRate) of requests.
//
// m.AllocPerRequest must be non-nil (i.e. New() must have been called).
// alertFn may be nil — the histogram is still updated but no alert is fired.
func ObserveAlloc(m *Metrics, sampleRate float64, alertFn AlertFunc) func(http.Handler) http.Handler {
	if sampleRate <= 0 {
		// Disabled — return a pass-through middleware.
		return func(next http.Handler) http.Handler { return next }
	}
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			// Fast path: skip unsampled requests without reading MemStats.
			if rand.Float64() >= sampleRate {
				next.ServeHTTP(w, r)
				return
			}

			var before, after runtime.MemStats
			runtime.ReadMemStats(&before)
			next.ServeHTTP(w, r)
			runtime.ReadMemStats(&after)

			// TotalAlloc is monotonically increasing; delta = bytes allocated
			// during this handler call.
			var delta uint64
			if after.TotalAlloc >= before.TotalAlloc {
				delta = after.TotalAlloc - before.TotalAlloc
			}

			m.AllocPerRequest.Observe(float64(delta))

			if delta > allocRegressionThresholdBytes && alertFn != nil {
				alertFn("api_alloc_regression", "warn")
			}
		})
	}
}
