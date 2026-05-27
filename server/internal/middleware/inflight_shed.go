package middleware

import (
	"context"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	aperrors "github.com/metaphy6/negelir/server/internal/errors"
)

// InflightShedAlertFunc is the sec.alert.v1 callback injected from cmd/api.
// kind is "api_inflight_pressure_shed"; severity is "warn".
type InflightShedAlertFunc func(ctx context.Context, kind, severity string)

// InflightShedderCfg is the minimal config surface InflightShedder reads.
// *config.Config satisfies this via PriorityTierFloor().
type InflightShedderCfg interface {
	PriorityTierFloor() int64
}

// InflightShedder tracks the current number of in-flight requests and sheds
// low-priority requests when the ratio (inflight / maxConcurrent) has been
// above 0.85 for more than 5 seconds.
//
// Built-but-dormant default: cfg.APIPriorityTierFloor defaults to 0.  No
// authenticated user has tier_id < 0, so the shed branch is never taken until
// Phase 20 raises the floor to a value > 0 (e.g. 2 to protect tier 2+ users).
//
// Shed response: HTTP 503 + X-Shed-Reason: inflight_pressure + Retry-After: 5.
type InflightShedder struct {
	count         int64        // updated via sync; use mu-protected helpers below
	maxConcurrent int64
	floor         int64 // requests with tier_id < floor are shed under pressure

	mu            sync.Mutex
	countVal      int64 // actual counter (mu-protected)
	pressureStart time.Time

	now   func() time.Time
	alert InflightShedAlertFunc
}

// NewInflightShedder builds a production InflightShedder.
func NewInflightShedder(maxConcurrent int, cfg InflightShedderCfg, alert InflightShedAlertFunc) *InflightShedder {
	return newInflightShedder(maxConcurrent, cfg, alert, time.Now)
}

// newInflightShedder is the internal constructor with clock injection.
func newInflightShedder(maxConcurrent int, cfg InflightShedderCfg, alert InflightShedAlertFunc, now func() time.Time) *InflightShedder {
	floor := int64(0)
	if cfg != nil {
		floor = cfg.PriorityTierFloor()
	}
	return &InflightShedder{
		maxConcurrent: int64(maxConcurrent),
		floor:         floor,
		now:           now,
		alert:         alert,
	}
}

// incr increments the in-flight counter and returns the new value.
func (s *InflightShedder) incr() int64 {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.countVal++
	return s.countVal
}

// decr decrements the in-flight counter.
func (s *InflightShedder) decr() {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.countVal > 0 {
		s.countVal--
	}
}

// currentCount returns the current in-flight count.
func (s *InflightShedder) currentCount() int64 {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.countVal
}

// shouldShed returns true when pressure has exceeded the threshold for > 5 s
// AND the request carries a tier_id below the shed floor.
func (s *InflightShedder) shouldShed(tierID int64) bool {
	if s.maxConcurrent <= 0 {
		return false
	}
	s.mu.Lock()
	defer s.mu.Unlock()

	now := s.now()
	ratio := float64(s.countVal) / float64(s.maxConcurrent)

	if ratio > 0.85 {
		if s.pressureStart.IsZero() {
			s.pressureStart = now
		}
		if now.Sub(s.pressureStart) > 5*time.Second && tierID < s.floor {
			if s.alert != nil {
				s.alert(context.Background(), "api_inflight_pressure_shed", "warn")
			}
			return true
		}
	} else {
		s.pressureStart = time.Time{} // ratio recovered
	}
	return false
}

// CurrentInflight returns the in-flight count for observability.
func (s *InflightShedder) CurrentInflight() int64 {
	return s.currentCount()
}

// InflightPressureShed returns a Gin middleware that enforces inflight-aware
// shedding. Register AFTER the Authenticate middleware (so ContextKeyTierID is
// populated) and BEFORE the handler chain.
func InflightPressureShed(s *InflightShedder) gin.HandlerFunc {
	return func(c *gin.Context) {
		// tier_id is set by Authenticate as int64 in context.
		var tierID int64
		if raw, exists := c.Get(ContextKeyTierID); exists {
			if v, ok := raw.(int64); ok {
				tierID = v
			}
		}

		if s.shouldShed(tierID) {
			c.Header("X-Shed-Reason", "inflight_pressure")
			aperrors.RespondWithRetryAfter(c, aperrors.CodeServiceUnavailable,
				"inflight pressure: cluster is overloaded, retry in 5 s", 5)
			c.Abort()
			return
		}

		s.incr()
		defer s.decr()
		c.Next()
	}
}
