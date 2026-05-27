// Package resilience implements the Phase 9 §9.17.4 resilience primitives:
// circuit breakers (sony/gobreaker), bulkheads (semaphore), hedged RPC,
// singleflight cache-miss collapse, and retry budgets (token bucket).
//
// All state-change events are surfaced via AlertFunc so the operator's
// sec.alert.v1 pipeline receives breaker_opened / breaker_half_open /
// breaker_closed notifications (severity=warn, debounced 60 s at the
// alert router level, not here — this package just emits).
package resilience

import (
	"context"
	"time"

	"github.com/sony/gobreaker"
)

// UpstreamKind identifies the upstream covered by a circuit breaker or bulkhead.
type UpstreamKind string

const (
	UpstreamPG         UpstreamKind = "pg"
	UpstreamRedisCache UpstreamKind = "redis_cache"
	UpstreamRedisBus   UpstreamKind = "redis_bus"
	UpstreamSwarmRPC   UpstreamKind = "swarm_rpc"
)

// AlertFunc is the sec.alert.v1 emission callback injected from cmd/api.
// kind is one of "breaker_opened", "breaker_half_open", "breaker_closed",
// "api_panic". severity is "warn" or "critical".
type AlertFunc func(ctx context.Context, kind, severity string)

// BreakerConfig holds the tunable knobs for all circuit breakers.
// Values map directly to the cfg.api_breaker_* env knobs (§9.17.4).
type BreakerConfig struct {
	FailRatio   float64       // fraction of failures that trips the breaker (default 0.5)
	Window      time.Duration // rolling window for counting requests (default 10s)
	MinRequests uint32        // minimum calls before the breaker can trip (default 20)
	OpenDelay   time.Duration // how long to stay open before probing (default 15s)
}

// Breakers holds one gobreaker.CircuitBreaker per upstream.
// Construct with NewBreakers; use Execute to run a call through a breaker.
type Breakers struct {
	pg         *gobreaker.CircuitBreaker
	redisCache *gobreaker.CircuitBreaker
	redisBus   *gobreaker.CircuitBreaker
	swarmRPC   *gobreaker.CircuitBreaker
}

// NewBreakers constructs one circuit breaker per upstream with the given config.
// onChange is called on every state transition (possibly from a goroutine);
// it must be non-blocking. Pass nil to disable state-change callbacks.
func NewBreakers(cfg BreakerConfig, onChange AlertFunc) *Breakers {
	build := func(kind UpstreamKind) *gobreaker.CircuitBreaker {
		k := kind
		return gobreaker.NewCircuitBreaker(gobreaker.Settings{
			Name:        string(kind),
			MaxRequests: 1, // half-open: one probe before deciding
			Interval:    cfg.Window,
			Timeout:     cfg.OpenDelay,
			ReadyToTrip: func(counts gobreaker.Counts) bool {
				if counts.Requests < cfg.MinRequests {
					return false
				}
				return float64(counts.TotalFailures)/float64(counts.Requests) >= cfg.FailRatio
			},
			OnStateChange: func(_ string, _ gobreaker.State, to gobreaker.State) {
				if onChange == nil {
					return
				}
				onChange(context.Background(), breakerAlertKind(k, to), "warn")
			},
		})
	}
	return &Breakers{
		pg:         build(UpstreamPG),
		redisCache: build(UpstreamRedisCache),
		redisBus:   build(UpstreamRedisBus),
		swarmRPC:   build(UpstreamSwarmRPC),
	}
}

// Execute runs fn through the named upstream's circuit breaker.
// Returns gobreaker.ErrOpenState when the breaker is open.
// Returns fn's error when the breaker is closed or half-open.
func (b *Breakers) Execute(upstream UpstreamKind, fn func() (interface{}, error)) (interface{}, error) {
	cb := b.get(upstream)
	if cb == nil {
		return fn()
	}
	return cb.Execute(fn)
}

// State returns the current breaker state for testing / health checks.
func (b *Breakers) State(upstream UpstreamKind) gobreaker.State {
	cb := b.get(upstream)
	if cb == nil {
		return gobreaker.StateClosed
	}
	return cb.State()
}

func (b *Breakers) get(upstream UpstreamKind) *gobreaker.CircuitBreaker {
	switch upstream {
	case UpstreamPG:
		return b.pg
	case UpstreamRedisCache:
		return b.redisCache
	case UpstreamRedisBus:
		return b.redisBus
	case UpstreamSwarmRPC:
		return b.swarmRPC
	}
	return nil
}

// breakerAlertKind maps a gobreaker state to the sec.alert.v1 kind string.
// Per §9.17.4 spec the kind is breaker_opened / breaker_half_open / breaker_closed
// (no upstream prefix — the upstream name is carried in the gobreaker Name field
// which the caller may log separately).
func breakerAlertKind(_ UpstreamKind, to gobreaker.State) string {
	switch to {
	case gobreaker.StateOpen:
		return "breaker_opened"
	case gobreaker.StateHalfOpen:
		return "breaker_half_open"
	case gobreaker.StateClosed:
		return "breaker_closed"
	}
	return "breaker_closed"
}
