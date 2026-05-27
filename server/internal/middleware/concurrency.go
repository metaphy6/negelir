package middleware

import (
	"net/http"

	"github.com/gin-gonic/gin"
)

// ConcurrencyLimit returns a Gin middleware that enforces a cap on the number
// of concurrently in-flight requests. A buffered channel acts as a counting
// semaphore: a non-blocking send acquires a slot; a deferred receive releases
// it when the handler chain returns.
//
// When all slots are occupied the middleware immediately returns HTTP 503 with
// header X-Overflow: true and does not call c.Next(). There is no queuing or
// wait — callers should retry with a brief back-off.
//
// The semaphore channel is allocated once when the middleware is constructed
// and shared across all requests for the lifetime of the server. maxRequests
// must be > 0; pass 0 to disable the cap entirely (no-op pass-through).
//
// Phase 9 §9.9 connection caps.
func ConcurrencyLimit(maxRequests int) gin.HandlerFunc {
	if maxRequests <= 0 {
		// Disabled — no-op pass-through.
		return func(c *gin.Context) { c.Next() }
	}
	sem := make(chan struct{}, maxRequests)
	return func(c *gin.Context) {
		select {
		case sem <- struct{}{}:
			// Slot acquired — release it when the handler chain returns.
			defer func() { <-sem }()
			c.Next()
		default:
			// All slots occupied — shed immediately.
			c.Header("X-Overflow", "true")
			c.AbortWithStatus(http.StatusServiceUnavailable)
		}
	}
}
