package middleware

import (
	"context"
	"fmt"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
)

// ContextKeyUserID is the Gin context key that holds the authenticated user's
// primary key (string UUID or opaque ID). Set by the Authenticate middleware
// after JWT verification. Absent on anonymous requests.
const ContextKeyUserID = "auth.user_id"

// ContextKeyTierID is the Gin context key that holds the authenticated user's
// tier_id (int64). Set by the Authenticate middleware alongside ContextKeyUserID.
// Absent on anonymous requests.
const ContextKeyTierID = "auth.tier_id"

// TierQuotaCounterTTL is the Redis key TTL for tier quota counters. 26 hours
// (not 24) provides a grace window at day boundaries so late-night requests
// on one calendar day do not collide with the counter for the next day.
const TierQuotaCounterTTL = 26 * time.Hour

// TierStore is the minimal database interface required by TierQuota.
// Production: backed by pgx querying the tiers table (migration 012).
// Tests: in-memory stub.
type TierStore interface {
	// DailyRequestCap returns the daily_request_cap for the given tier_id.
	// A nil return means no cap -- all requests are allowed.
	// An error causes the middleware to fail open (pass-through).
	DailyRequestCap(ctx context.Context, tierID int64) (*int64, error)
}

// TierQuotaCounter is the minimal Redis interface required by TierQuota.
// Tests: in-memory stub.
type TierQuotaCounter interface {
	// Incr atomically increments the counter at key and returns the new value.
	Incr(ctx context.Context, key string) (int64, error)
	// Expire sets the TTL on key. Called only when count==1 (new key).
	// Errors are silently swallowed; the quota is a built-but-dormant feature.
	Expire(ctx context.Context, key string, ttl time.Duration) error
}

// TierQuotaCfg is the minimal config surface TierQuota reads. Satisfied by
// *config.Config; extracted as an interface so tests can stub it without
// importing the full config package.
type TierQuotaCfg interface {
	TierEnforcementEnabled() bool
}

// TierQuota returns a Gin middleware that enforces per-tier daily request
// quotas.
//
// Behaviour:
//   - When cfg.TierEnforcementEnabled() == false (the default): this is a
//     pure no-op; it calls c.Next() immediately without touching Redis or the DB.
//     This is the built-but-dormant state for Phase 9; Phase 20 flips the flag.
//   - When enabled: derives user_id and tier_id from the Gin context (set by
//     the Authenticate middleware). If either is absent the middleware fails
//     open (c.Next()) to preserve availability.
//   - Looks up the daily_request_cap for the tier via TierStore. cap == nil
//     means unlimited -- c.Next() is called immediately.
//   - Increments the Redis counter tier:<tier_id>:<user_id>:<utc_yyyymmdd>.
//     Sets a 26-hour TTL on first creation (count == 1). If the new count
//     exceeds the cap, aborts with 429 (empty body, per denylist pattern).
//   - Any Redis or DB error causes fail-open (c.Next()).
//
// Placement: must be placed AFTER the Authenticate middleware (which sets
// ContextKeyUserID and ContextKeyTierID) and BEFORE the handler.
//
// Body contract: the response body is intentionally empty on 429, consistent
// with DenylistCheck.
func TierQuota(cfg TierQuotaCfg, counter TierQuotaCounter, store TierStore) gin.HandlerFunc {
	return func(c *gin.Context) {
		// Dormant: flag off -> no-op pass-through.
		if !cfg.TierEnforcementEnabled() {
			c.Next()
			return
		}

		// Derive user_id and tier_id from context (set by Authenticate middleware).
		userID := c.GetString(ContextKeyUserID)
		if userID == "" {
			// Anonymous or pre-auth route -- fail open.
			c.Next()
			return
		}
		tierIDRaw, exists := c.Get(ContextKeyTierID)
		if !exists {
			c.Next()
			return
		}
		tierID, ok := tierIDRaw.(int64)
		if !ok {
			c.Next()
			return
		}

		// Consult the TierStore for this tier's daily cap.
		cap, err := store.DailyRequestCap(c.Request.Context(), tierID)
		if err != nil {
			// DB unavailable -- fail open.
			c.Next()
			return
		}
		if cap == nil {
			// No cap defined -- unlimited, pass through.
			c.Next()
			return
		}

		// Build the Redis key and increment the counter.
		date := time.Now().UTC().Format("20060102")
		key := fmt.Sprintf("tier:%d:%s:%s", tierID, userID, date)

		count, err := counter.Incr(c.Request.Context(), key)
		if err != nil {
			// Redis unavailable -- fail open.
			c.Next()
			return
		}
		// Set TTL only on first increment (new key) to avoid resetting the
		// expiry on every request. Errors silently ignored (dormant feature).
		if count == 1 {
			_ = counter.Expire(c.Request.Context(), key, TierQuotaCounterTTL)
		}

		// Enforce the cap.
		if count > *cap {
			c.Status(http.StatusTooManyRequests)
			c.Abort()
			return
		}

		c.Next()
	}
}
