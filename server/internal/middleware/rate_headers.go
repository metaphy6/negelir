package middleware

import "github.com/gin-gonic/gin"

// RateHeaders returns a Gin middleware that ensures X-RateLimit-Remaining
// and X-RateLimit-Reset response headers reach the client.
//
// The upstream RateLimiter middleware sets these headers directly:
//   - On allowed requests: via c.Header() before calling c.Next().
//   - On throttled/denied requests: inside the BuildThrottleResponse headers map.
//
// RateHeaders is therefore a structural passthrough in the chain — it exists
// to document the concern's position (after TierQuota, before AuditEmitter)
// and to serve as the extension point if per-response override logic is ever
// needed (e.g. overriding headers from a downstream cache hit).
func RateHeaders() gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Next()
	}
}
