// Package metrics registers all Prometheus metric families for the Negelir API
// server (§9.8 RED metrics) and provides:
//
//   - Metrics — holder for the 7 metric families.
//   - New(reg) — registers all metrics with the given Prometheus registry.
//   - EstimateCardinality(routeCount) — worst-case time-series count.
//   - ValidateCardinality(routeCount, maxSeries) — boot-time cardinality gate.
//
// The metrics endpoint is served on a SEPARATE port (cfg.TelemetryMetricsPort,
// default :9091) by the cmd/api/main.go startup code. It is NOT reachable
// through the public API port.
package metrics

import (
	"fmt"
	"sync"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

// Context key constants used by the Observe middleware and by upstream
// middleware/handlers to annotate each request with cache and degraded state.
const (
	// ContextKeyCacheStatus is the Gin context key under which the cache status
	// for a cacheable request is stored. Allowed values: "hit", "stale",
	// "miss", "n/a" (default when the route is not cache-aware).
	ContextKeyCacheStatus = "metrics.cache_status"

	// ContextKeyDegraded is the Gin context key under which the degraded flag
	// is stored. Allowed values: "true", "false" (default).
	ContextKeyDegraded = "metrics.degraded"
)

// DurationBuckets are the histogram boundaries for api_request_duration_seconds
// and related timing metrics: 1 ms to 2500 ms, as specified by §9.17.5.
// Finer resolution at the low end (1 ms, 5 ms) is required to distinguish
// the ≤1 ms healthz/version SLO from the ≤5 ms leagues/match SLO; the
// 200 ms bucket aligns with the §9.17.5 predictions cache-miss p50 budget.
var DurationBuckets = []float64{
	0.001, 0.005, 0.010, 0.025, 0.050, 0.100, 0.200, 0.500, 1.000, 2.500,
}

// cardinality estimate multipliers for the boot-time gate.
const (
	estimatedStatusValues   = 8 // 3 common exact codes + 5 classes (1xx through 5xx)
	estimatedMethodValues   = 3 // GET, POST, DELETE
	estimatedCacheValues    = 4 // hit, stale, miss, n/a
	estimatedDegradedValues = 2 // true, false
)

// Metrics holds the 7 registered Prometheus metric families for §9.8.
type Metrics struct {
	// api_requests_total{route,status,method,cache,degraded}
	// Incremented twice per request: once with the exact HTTP status code
	// (e.g. "200") and once with the status class (e.g. "2xx").
	RequestsTotal *prometheus.CounterVec

	// api_request_duration_seconds_bucket{route,method} — 10 ms to 2500 ms.
	RequestDuration *prometheus.HistogramVec

	// api_inflight_rpcs{route} — current number of requests being processed.
	InflightRPCs *prometheus.GaugeVec

	// api_cache_hit_ratio{route} — computed gauge (not a counter); holds the
	// lifetime hit fraction for cacheable requests on this route.
	CacheHitRatio *prometheus.GaugeVec

	// api_jwt_verify_duration_seconds — histogram of JWT RS256 verify latency.
	JWTVerifyDuration prometheus.Histogram

	// api_sec_gate_duration_seconds — histogram of security-gate latency.
	SecGateDuration prometheus.Histogram

	// api_idempotency_replays_total{result} — idempotency cache replay events.
	IdempotencyReplays *prometheus.CounterVec

	// api_alloc_per_request_bytes — histogram of runtime allocation delta
	// (runtime.MemStats.Mallocs * mean-object-size approximation) per request,
	// sampled at cfg.api_alloc_sample_rate (§9.17.10). Buckets cover 1 KiB to
	// 512 KiB; the 50 KiB boundary aligns with the regression-alert threshold.
	AllocPerRequest prometheus.Histogram

	// Internal ratio tracking for CacheHitRatio computation.
	ratioMu    sync.Mutex
	ratioHits  map[string]int64
	ratioTotal map[string]int64
}

// New creates and registers all §9.8 metric families with reg.
// Use prometheus.NewRegistry() for an isolated registry (recommended for
// the dedicated :9091 metrics endpoint so Go runtime metrics are not exposed).
func New(reg prometheus.Registerer) *Metrics {
	m := &Metrics{
		ratioHits:  make(map[string]int64),
		ratioTotal: make(map[string]int64),
	}

	m.RequestsTotal = promauto.With(reg).NewCounterVec(
		prometheus.CounterOpts{
			Name: "api_requests_total",
			Help: "Total API requests by route, status (exact and class), method, cache, degraded.",
		},
		[]string{"route", "status", "method", "cache", "degraded"},
	)

	m.RequestDuration = promauto.With(reg).NewHistogramVec(
		prometheus.HistogramOpts{
			Name:    "api_request_duration_seconds",
			Help:    "API request latency in seconds by route and method (1ms..2500ms buckets, \u00a79.17.5).",
			Buckets: DurationBuckets,
		},
		[]string{"route", "method"},
	)

	m.InflightRPCs = promauto.With(reg).NewGaugeVec(
		prometheus.GaugeOpts{
			Name: "api_inflight_rpcs",
			Help: "Number of API requests currently being processed by route.",
		},
		[]string{"route"},
	)

	m.CacheHitRatio = promauto.With(reg).NewGaugeVec(
		prometheus.GaugeOpts{
			Name: "api_cache_hit_ratio",
			Help: "Lifetime cache hit ratio per route; 0 when no cacheable requests seen.",
		},
		[]string{"route"},
	)

	m.JWTVerifyDuration = promauto.With(reg).NewHistogram(
		prometheus.HistogramOpts{
			Name:    "api_jwt_verify_duration_seconds",
			Help:    "Duration of JWT RS256 verification operations in seconds.",
			Buckets: DurationBuckets,
		},
	)

	m.SecGateDuration = promauto.With(reg).NewHistogram(
		prometheus.HistogramOpts{
			Name:    "api_sec_gate_duration_seconds",
			Help:    "Duration of combined security gate checks in seconds.",
			Buckets: DurationBuckets,
		},
	)

	m.IdempotencyReplays = promauto.With(reg).NewCounterVec(
		prometheus.CounterOpts{
			Name: "api_idempotency_replays_total",
			Help: "Total idempotency-key replay events by result (hit, inflight).",
		},
		[]string{"result"},
	)

	// §9.17.10 — allocation tracking histogram.
	// Buckets: 1 KiB → 512 KiB; 50 KiB aligns with the regression-alert threshold.
	m.AllocPerRequest = promauto.With(reg).NewHistogram(
		prometheus.HistogramOpts{
			Name: "api_alloc_per_request_bytes",
			Help: "Allocation delta (bytes) sampled for 1-in-N requests via runtime.ReadMemStats (§9.17.10).",
			Buckets: []float64{
				1 << 10,  // 1 KiB
				4 << 10,  // 4 KiB
				16 << 10, // 16 KiB
				32 << 10, // 32 KiB
				50 << 10, // 50 KiB — regression-alert threshold
				128 << 10, // 128 KiB
				256 << 10, // 256 KiB
				512 << 10, // 512 KiB
			},
		},
	)

	return m
}

// UpdateCacheHitRatio updates the CacheHitRatio gauge for route based on
// the cache status of the current request.
//
// Only "hit", "stale", and "miss" count towards the denominator; "n/a" is
// excluded so the gauge reflects cache-aware routes only.
func (m *Metrics) UpdateCacheHitRatio(route, cacheStatus string) {
	if route == "" || cacheStatus == "n/a" {
		return
	}
	m.ratioMu.Lock()
	defer m.ratioMu.Unlock()
	m.ratioTotal[route]++
	if cacheStatus == "hit" {
		m.ratioHits[route]++
	}
	ratio := float64(m.ratioHits[route]) / float64(m.ratioTotal[route])
	m.CacheHitRatio.WithLabelValues(route).Set(ratio)
}

// EstimateCardinality returns the worst-case number of time series that
// api_requests_total would produce for the given number of registered routes.
//
// Formula: routeCount x status(8) x method(3) x cache(4) x degraded(2).
func EstimateCardinality(routeCount int) int {
	return routeCount *
		estimatedStatusValues *
		estimatedMethodValues *
		estimatedCacheValues *
		estimatedDegradedValues
}

// ValidateCardinality is the boot-time gate: it returns an error if the
// worst-case time series count for routeCount routes would exceed maxSeries.
// Call this in main() after all routes are registered but before the server
// starts accepting traffic.
func ValidateCardinality(routeCount, maxSeries int) error {
	estimate := EstimateCardinality(routeCount)
	if estimate > maxSeries {
		return fmt.Errorf(
			"metrics cardinality estimate %d "+
				"(routes=%d x status=%d x method=%d x cache=%d x degraded=%d) "+
				"exceeds NEGELIR_TELEMETRY_MAX_SERIES=%d; "+
				"reduce route count or raise the cap",
			estimate,
			routeCount, estimatedStatusValues, estimatedMethodValues,
			estimatedCacheValues, estimatedDegradedValues,
			maxSeries,
		)
	}
	return nil
}
