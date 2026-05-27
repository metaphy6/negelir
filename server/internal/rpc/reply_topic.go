// Package rpc — reply_topic.go
//
// Per-pod reply_to topic namespace for Phase 9 §9.3 RPC pattern.
//
// Topic format: api.reply.<pod_instance_id>.<request_short_uuid>
//
// Each predict.request.v1 message includes a reply_to field pointing at one
// of these streams. The API creates the stream (via XADD), waits for the
// single response message (XREAD BLOCK), then deletes the stream. The Reaper
// sweeps any stream in the api.reply.* namespace that was never consumed
// (pod crash / timeout race), so leaked streams do not accumulate in Redis.
//
// Boundary contract (§9.3):
//
//	The API is the SOLE writer and consumer of any api.reply.* stream.
//	No swarm agent, predictor, or other component reads or writes to these
//	streams directly. The AST scan in reply_topic_test.go + the boundary
//	test enforce this invariant at CI time.
package rpc

import (
	"context"
	"fmt"
	"strings"
	"time"
)

const replyTopicPrefix = "api.reply."

// ReplyTopic returns the Redis Stream key for a per-request reply channel.
//
// Format: api.reply.<podInstanceID>.<requestShortUUID>
// Both arguments must be non-empty; callers are responsible for passing
// a stable pod identity (e.g. hostname) and a per-request short UUID
// (first 8 hex chars of the UUIDv7 request_id is sufficient).
func ReplyTopic(podInstanceID, requestShortUUID string) string {
	return replyTopicPrefix + podInstanceID + "." + requestShortUUID
}

// IsReplyTopic reports whether key belongs to the api.reply.* namespace.
// Used by the reaper and boundary tests.
func IsReplyTopic(key string) bool {
	return strings.HasPrefix(key, replyTopicPrefix)
}

// ReplyTopicPrefix returns the static prefix shared by all reply streams.
// Exported so callers can pass it to Redis SCAN MATCH patterns.
func ReplyTopicPrefix() string { return replyTopicPrefix }

// RedisReaper is the interface the Reaper needs from Redis.
// Using an interface keeps the Reaper unit-testable without a live Redis.
type RedisReaper interface {
	// ScanReplyStreams calls fn for every Redis key matching
	// "api.reply.*". fn receives the key name and the stream's
	// idle duration (time since last entry was added / stream created).
	// Iteration stops if fn returns a non-nil error.
	ScanReplyStreams(ctx context.Context, fn func(key string, idle time.Duration) error) error

	// DelStream deletes the Redis Stream at key.
	DelStream(ctx context.Context, key string) error
}

// Reaper sweeps stale api.reply.* streams on a fixed interval.
//
// A stream is considered stale when its idle duration exceeds staleAfter.
// staleAfter should be set to cfg.api_request_timeout_ms + a small buffer
// (e.g. 5 s) so that streams from in-flight requests are never deleted.
//
// The Reaper must be started in its own goroutine via Run; it exits cleanly
// when ctx is cancelled.
type Reaper struct {
	redis      RedisReaper
	interval   time.Duration
	staleAfter time.Duration
}

// NewReaper creates a Reaper.
//
//   - interval   - how often to sweep (cfg.api_reply_reaper_s, default 60s).
//   - staleAfter - streams idle longer than this are deleted.
//     Recommended: cfg.api_request_timeout_ms + 5s.
func NewReaper(redis RedisReaper, interval, staleAfter time.Duration) *Reaper {
	return &Reaper{redis: redis, interval: interval, staleAfter: staleAfter}
}

// Run starts the reaper loop. It blocks until ctx is cancelled.
// Intended to be called in a goroutine:
//
//	go reaper.Run(ctx)
func (r *Reaper) Run(ctx context.Context) {
	ticker := time.NewTicker(r.interval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			_ = r.SweepOnce(ctx) // errors are non-fatal; next tick retries
		}
	}
}

// SweepOnce performs one reaper pass. Returns the first error encountered, if any,
// but always attempts to delete all eligible streams (does not short-circuit).
// Exported so tests can trigger a sweep without waiting for the ticker interval.
func (r *Reaper) SweepOnce(ctx context.Context) error {
	var firstErr error
	err := r.redis.ScanReplyStreams(ctx, func(key string, idle time.Duration) error {
		if idle < r.staleAfter {
			return nil
		}
		if delErr := r.redis.DelStream(ctx, key); delErr != nil {
			if firstErr == nil {
				firstErr = fmt.Errorf("reaper: del %q: %w", key, delErr)
			}
		}
		return nil
	})
	if err != nil {
		return fmt.Errorf("reaper: scan: %w", err)
	}
	return firstErr
}
