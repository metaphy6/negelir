package middleware

import (
	"context"
	"net"
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/metaphy6/negelir/server/internal/sec"
	"github.com/redis/go-redis/v9"
)

// ContextKeyDenylisted is the Gin context key set to true when the request
// subject is found in the Redis denylist. The audit emitter reads this flag
// to include `denylisted: true` in the api.request.v1 bus row.
const ContextKeyDenylisted = "sec.denylisted"

// DenylistKeyPrefix is the Redis key prefix for the denylist. The full key
// is "sec:denylist:<subject_key>" written by the Lua sec_denylist_mutate v1.1.0
// script. The Go middleware is read-only: it never writes or deletes the key.
const DenylistKeyPrefix = "sec:denylist:"

// DenylistCappedKey is the Redis key that signals subnet-mode escape is active
// (§7.3 cap flag). When this key has a non-empty value, rate-limit subject keys
// are collapsed to /24 (IPv4) or /64 (IPv6) and X-RateLimit-Mode: subnet is set.
const DenylistCappedKey = "sec:denylist:capped"

// DenylistReader is the minimal Redis GET surface the denylist middleware
// requires. *redis.Client satisfies this interface via RedisDenylist.
type DenylistReader interface {
	// Get returns the stored value and nil on a hit, or ("", redis.Nil) on a
	// miss, or ("", <err>) on a Redis communication fault.
	Get(ctx context.Context, key string) (string, error)
}

// RedisDenylist adapts a *redis.Client to DenylistReader.
type RedisDenylist struct{ C *redis.Client }

// Get delegates to the underlying Redis client.
func (r *RedisDenylist) Get(ctx context.Context, key string) (string, error) {
	return r.C.Get(ctx, key).Result()
}

// DenylistCheck returns a Gin middleware that implements the §9.7 denylist
// short-circuit:
//
//   - Derives the subject key from the Gin context (ContextKeyRateSubject set
//     by the XFF middleware). Falls back to c.RemoteIP() for chains that lack
//     the XFF middleware.
//   - Does a Redis GET of "sec:denylist:<subject_key>".
//   - On a hit (non-empty value, no error): sets ContextKeyDenylisted = true,
//     returns 429 with an empty body, and aborts the chain.
//   - On a miss (redis.Nil or empty value) or any Redis error: fails open and
//     calls c.Next(). Availability is preserved over false negatives.
//
// Placement: this middleware MUST be placed at the TOP of the chain (before
// the rate limiter, authentication, and every handler) so denylisted subjects
// never touch business logic.
//
// Body contract: the response body is intentionally empty. The caller must
// NOT call c.JSON; only c.Status(429) + c.Abort() are issued. This satisfies
// the §9.7 "no body content" requirement.
//
// Audit contract: ContextKeyDenylisted is set BEFORE Abort() so any
// after-handler (e.g. the AuditEmitter) that runs on the way back up the
// chain can read the flag and include `denylisted: true` in the
// api.request.v1 bus row.
func DenylistCheck(rdr DenylistReader) gin.HandlerFunc {
	return func(c *gin.Context) {
		subjectRaw, _ := c.Get(ContextKeyRateSubject)
		subject, _ := subjectRaw.(string)
		if subject == "" {
			subject = c.RemoteIP()
		}

		key := DenylistKeyPrefix + subject
		val, err := rdr.Get(c.Request.Context(), key)
		if err == nil && val != "" {
			// Subject is denylisted: flag the context and return 429, empty body.
			c.Set(ContextKeyDenylisted, true)
			c.Status(http.StatusTooManyRequests)
			c.Abort()
			return
		}
		// Key absent or Redis error → fail open.
		c.Next()
	}
}

// SubnetModeEscape returns a Gin middleware that enforces the §9.7 subnet-mode
// escape: when the sec:denylist:capped flag is set in Redis, the request's
// rate-limit subject key is collapsed to /24 (IPv4) or /64 (IPv6) so the
// rate-limiter buckets entire subnets rather than individual IPs. The response
// header X-RateLimit-Mode: subnet is set so client telemetry can attribute
// throttling correctly.
//
// Placement: place AFTER the XFF middleware (which sets ContextKeyClientIP)
// and BEFORE the rate-limiter (which reads ContextKeyRateSubject).
//
// Fail-open: any Redis error or missing cap flag leaves ContextKeyRateSubject
// unchanged and omits the header. Availability is preserved over correctness
// under Redis faults.
func SubnetModeEscape(rdr DenylistReader) gin.HandlerFunc {
	return func(c *gin.Context) {
		val, err := rdr.Get(c.Request.Context(), DenylistCappedKey)
		if err == nil && val != "" {
			// Cap flag is set: collapse subject to /24 (IPv4) or /64 (IPv6).
			ipRaw, _ := c.Get(ContextKeyClientIP)
			ip, _ := ipRaw.(net.IP)
			if ip == nil {
				// Fall back to TCP peer address when XFF middleware is absent.
				ip = net.ParseIP(c.RemoteIP())
			}
			if ip != nil {
				subnetSubject := sec.SubjectKey(ip, 24, 64)
				c.Set(ContextKeyRateSubject, subnetSubject)
			}
			c.Header("X-RateLimit-Mode", "subnet")
		}
		c.Next()
	}
}
