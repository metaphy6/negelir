// middleware.go provides the Gin middleware for §9.8 RED metrics observation.
package metrics

import (
	"fmt"
	"time"

	"github.com/gin-gonic/gin"
)

// Observe returns a Gin middleware that records the §9.8 RED metrics for
// every matched request:
//
//   - api_requests_total — incremented twice (exact status + class status).
//   - api_request_duration_seconds_bucket — one observation per request.
//   - api_inflight_rpcs — gauged per route (inc before Next, dec after).
//   - api_cache_hit_ratio — updated per route after the request completes.
//
// Route label is always c.FullPath() — the matched OpenAPI pattern such as
// "/v1/matches/:id" — NEVER the substituted URL. Requests to unmatched
// routes (c.FullPath() == "") are passed through without observation so
// the route label stays bounded.
//
// Cache status is read from the ContextKeyCacheStatus Gin context key
// (default "n/a"). Degraded flag is read from ContextKeyDegraded (default
// "false"). Upstream middleware and handlers set these keys before or
// during handler execution; the Observe middleware reads them after c.Next().
func Observe(m *Metrics) gin.HandlerFunc {
	return func(c *gin.Context) {
		route := c.FullPath()
		if route == "" {
			// Unmatched route — skip to avoid an unbounded "" label.
			c.Next()
			return
		}

		method := c.Request.Method

		// Increment inflight before dispatching to the handler chain.
		m.InflightRPCs.WithLabelValues(route).Inc()
		start := time.Now()

		c.Next()

		// Decrement inflight after the full handler chain returns.
		m.InflightRPCs.WithLabelValues(route).Dec()

		duration := time.Since(start).Seconds()
		code := c.Writer.Status()

		// Cache and degraded labels — read from context keys set by upstream
		// middleware or handlers. Defaults: "n/a" and "false" respectively.
		cacheStatus := c.GetString(ContextKeyCacheStatus)
		if cacheStatus == "" {
			cacheStatus = "n/a"
		}
		degradedFlag := c.GetString(ContextKeyDegraded)
		if degradedFlag == "" {
			degradedFlag = "false"
		}

		// Emit the exact status code and the status class as two separate
		// label values on the same counter, as required by §9.8:
		// "status code class + exact alongside exact".
		exactStatus := fmt.Sprintf("%d", code)
		classStatus := fmt.Sprintf("%dxx", code/100)

		m.RequestsTotal.WithLabelValues(route, exactStatus, method, cacheStatus, degradedFlag).Inc()
		m.RequestsTotal.WithLabelValues(route, classStatus, method, cacheStatus, degradedFlag).Inc()

		m.RequestDuration.WithLabelValues(route, method).Observe(duration)

		// Update the computed cache hit ratio gauge.
		m.UpdateCacheHitRatio(route, cacheStatus)
	}
}
