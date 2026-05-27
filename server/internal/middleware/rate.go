package middleware

import (
	"context"
	"net/http"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/metaphy6/negelir/server/internal/sec"
)

// RateLimiter returns a Gin middleware that enforces two-tier rate limiting:
//
//  1. Secondary (in-process) GCRA bucket — checked first against the IP subject.
//     Throttle → 503 Service Unavailable + Retry-After: 1 (brownout hint).
//     This tier is fail-open: it never denies, only throttles.
//
//  2. Primary Redis/Lua bucket — checked when secondary allows.
//     Two subjects are checked: the JTI/auth subject and the IP subject.
//     Lower-of-two wins: the stricter decision (lower remaining / denied > throttle > allow)
//     is enforced. For anonymous requests both subjects are identical (one check only).
//     Throttle → 429 Too Many Requests + real Retry-After.
//     Denied  → 403 Forbidden.
//
// All responses (allow and throttle/deny) include:
//   - X-RateLimit-Remaining: min(jti_remaining, ip_remaining)
//   - X-RateLimit-Reset: Unix epoch seconds when the bucket next refills
//
// `secondary` is the in-process SecondaryBucket (constructed at boot).
// `primary` is the RateChecker backed by Redis EVALSHA (also boot-time).
// `costs` is the compiled EndpointCostMap.
// `capacity` and `refillPerS` are the primary bucket parameters derived
// from the authenticated tier; callers should pass the pre-auth values
// before the JWT is verified.
func RateLimiter(
	secondary *sec.SecondaryBucket,
	primary sec.RateChecker,
	costs *sec.EndpointCostMap,
	capacity int,
	refillPerS float64,
	redisTimeoutMs int,
) gin.HandlerFunc {
	return func(c *gin.Context) {
		// Derive IP subject (always from the XFF middleware).
		subjectIPRaw, _ := c.Get(ContextKeyRateSubject)
		subjectIP, _ := subjectIPRaw.(string)
		if subjectIP == "" {
			subjectIP = c.RemoteIP()
		}

		// Derive JTI/auth subject (set by the Authenticate middleware after JWT
		// verification). Falls back to the IP subject for anonymous requests so
		// the two checks collapse to one.
		subjectJTI := c.GetString(ContextKeySubjectID)
		if subjectJTI == "" {
			subjectJTI = subjectIP
		}

		cost, _ := costs.CostFor(c.FullPath())

		// ── Tier 1: in-process secondary bucket (IP subject only) ───────
		secDec, err := secondary.Check(c.Request.Context(), subjectIP, 0, 0, cost)
		if err == nil && secDec.Status == sec.RateThrottle {
			status, headers, body := sec.BuildSecondaryThrottleResponse(secDec)
			writeRateResponse(c, status, headers, body)
			return
		}

		// ── Tier 2: Redis/Lua primary bucket (dual-subject) ─────────────
		rCtx, cancel := context.WithTimeout(c.Request.Context(), time.Duration(redisTimeoutMs)*time.Millisecond)
		defer cancel()

		// Check JTI (or anon==IP) bucket.
		jtiDec, err := primary.Check(rCtx, subjectJTI, capacity, refillPerS, cost)
		if err != nil {
			// Redis unreachable — secondary already guards; fail open.
			c.Next()
			return
		}

		// Check IP bucket only when it differs from the JTI subject.
		ipDec := jtiDec
		if subjectJTI != subjectIP {
			ipDec, err = primary.Check(rCtx, subjectIP, capacity, refillPerS, cost)
			if err != nil {
				// Redis unreachable for second check — fail open.
				c.Next()
				return
			}
		}

		// Lower-of-two wins: pick the stricter decision.
		winner := mergePrimaryDecisions(jtiDec, ipDec)

		if winner.Status != sec.RateAllow {
			status, headers, body := sec.BuildThrottleResponse(winner, "")
			if status == 0 {
				c.Next()
				return
			}
			// Augment the throttle response with X-RateLimit headers.
			if headers == nil {
				headers = map[string]string{}
			}
			headers["X-RateLimit-Remaining"] = rateLimitRemainingStr(winner.Remaining)
			headers["X-RateLimit-Reset"] = rateLimitResetStr(winner.RetryAfter)
			writeRateResponse(c, status, headers, body)
			return
		}

		// Both subjects allow: set headers before the handler writes.
		minRemaining := jtiDec.Remaining
		if ipDec.Remaining < minRemaining {
			minRemaining = ipDec.Remaining
		}
		c.Header("X-RateLimit-Remaining", rateLimitRemainingStr(minRemaining))
		c.Header("X-RateLimit-Reset", strconv.FormatInt(time.Now().Unix(), 10))

		c.Next()
	}
}

// mergePrimaryDecisions returns the stricter of two primary bucket decisions.
// Priority: denied > throttle > allow. Within the same status, lower remaining wins.
func mergePrimaryDecisions(a, b sec.RateDecision) sec.RateDecision {
	aRank := primaryDecisionRank(a.Status)
	bRank := primaryDecisionRank(b.Status)
	if bRank > aRank {
		return b
	}
	if aRank > bRank {
		return a
	}
	// Same status: pick the one with lower remaining (more restricted).
	if b.Remaining < a.Remaining {
		return b
	}
	return a
}

// primaryDecisionRank assigns a severity rank to a RateStatus for merging.
func primaryDecisionRank(s sec.RateStatus) int {
	switch s {
	case sec.RateAllow:
		return 0
	case sec.RateThrottle:
		return 1
	case sec.RateDenied:
		return 2
	default:
		return 0
	}
}

// rateLimitRemainingStr formats the remaining token count as an integer string,
// flooring to zero on negative values.
func rateLimitRemainingStr(r float64) string {
	if r < 0 {
		r = 0
	}
	return strconv.FormatInt(int64(r), 10)
}

// rateLimitResetStr returns the Unix epoch second at which the bucket next
// refills, derived from the decision's RetryAfter duration (ceiling to seconds,
// per RFC 6585 conventions). For an allow decision (RetryAfter == 0) this
// returns the current epoch (the bucket is already ready).
func rateLimitResetStr(retryAfter time.Duration) string {
	ms := retryAfter.Milliseconds()
	if ms < 0 {
		ms = 0
	}
	s := ms / 1000
	if ms%1000 != 0 {
		s++ // ceiling
	}
	return strconv.FormatInt(time.Now().Unix()+s, 10)
}

func writeRateResponse(c *gin.Context, status int, headers map[string]string, body []byte) {
	for k, v := range headers {
		c.Header(k, v)
	}
	c.Data(status, "application/json; charset=utf-8", body)
	c.Abort()
}

// noopRateChecker is a fail-open primary checker used when Redis is
// unavailable at construction time (test / mocksrv mode).
type noopRateChecker struct{}

func (noopRateChecker) Check(_ context.Context, _ string, _ int, _ float64, _ int) (sec.RateDecision, error) {
	return sec.RateDecision{Status: sec.RateAllow, UsedTier: "noop"}, nil
}

// NoopRateChecker returns a RateChecker that always allows — used in
// tests and mocksrv where there is no Redis.
func NoopRateChecker() sec.RateChecker { return noopRateChecker{} }

// RateLimiterSimple is a convenience constructor that builds a
// RateLimiter using the pre-auth capacity/refill from config. Post-auth
// tier promotion is out of scope for this bullet.
func RateLimiterSimple(
	secondary *sec.SecondaryBucket,
	primary sec.RateChecker,
	costs *sec.EndpointCostMap,
	preAuthCapacity int,
	preAuthRefillPerS float64,
	redisTimeoutMs int,
) gin.HandlerFunc {
	return RateLimiter(secondary, primary, costs, preAuthCapacity, preAuthRefillPerS, redisTimeoutMs)
}

// Ensure http package is used (StatusServiceUnavailable documents
// that 503 is intentional and not a typo).
var _ = http.StatusServiceUnavailable
