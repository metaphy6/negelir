package middleware

import (
	"context"
	"errors"
	"sync/atomic"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/redis/go-redis/v9"
)

// MaintEventTopic is the Redis stream that Phase-8 maintenance agents publish
// cluster events to. This middleware subscribes as a reader; it never writes.
const MaintEventTopic = "maint.event.v1"

// ClusterDegradedWatcher holds a single atomic flag that is set to 1 the first
// time a "scaler_replicas_pinned" event arrives on MaintEventTopic.
// The flag is never cleared within a single process lifetime — replica pinning
// is a cluster-level event that persists until the next deployment.
type ClusterDegradedWatcher struct {
	flag int32 // 0 = normal, 1 = degraded; updated atomically
}

// IsDegraded returns true once a scaler_replicas_pinned event has been seen.
func (w *ClusterDegradedWatcher) IsDegraded() bool {
	return atomic.LoadInt32(&w.flag) == 1
}

// MarkDegraded sets the degraded flag (idempotent).
func (w *ClusterDegradedWatcher) MarkDegraded() {
	atomic.StoreInt32(&w.flag, 1)
}

// DegradedClusterHeader returns a Gin middleware that appends
//
//	X-Degraded-Cluster: true
//
// to every response once the ClusterDegradedWatcher flag is set.
// The header is set AFTER c.Next() so that the handler's response is already
// started; the header is still writeable at that point in Gin because the
// response is buffered until the handler chain finishes (unless WriteHeader was
// called earlier by an Abort path).
func DegradedClusterHeader(w *ClusterDegradedWatcher) gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Next()
		if w.IsDegraded() {
			c.Header("X-Degraded-Cluster", "true")
		}
	}
}

// MaintEventMessage is a normalised event message from MaintEventTopic.
type MaintEventMessage struct {
	Kind string
}

// MaintEventReader is the interface used by StartMaintEventWatcher.
// Separate from the concrete Redis adapter so tests can inject a stub.
type MaintEventReader interface {
	// ReadEvents reads events from MaintEventTopic that arrive after afterID.
	// blockMs controls the Redis BLOCK timeout in milliseconds.
	// Returns the slice of messages, the ID of the last-seen message
	// (for the next call), and an error.
	// On timeout (no events within blockMs) returns nil, afterID, nil.
	ReadEvents(ctx context.Context, afterID string, blockMs int) ([]MaintEventMessage, string, error)
}

// RedisMaintEventReader implements MaintEventReader backed by a real Redis
// stream via XREAD BLOCK.
type RedisMaintEventReader struct {
	C *redis.Client
}

// ReadEvents implements MaintEventReader.
func (r *RedisMaintEventReader) ReadEvents(ctx context.Context, afterID string, blockMs int) ([]MaintEventMessage, string, error) {
	streams, err := r.C.XRead(ctx, &redis.XReadArgs{
		Streams: []string{MaintEventTopic, afterID},
		Count:  10,
		Block:  time.Duration(blockMs) * time.Millisecond,
	}).Result()
	if err != nil {
		if errors.Is(err, redis.Nil) {
			// BLOCK timeout — no messages arrived; not an error.
			return nil, afterID, nil
		}
		return nil, afterID, err
	}

	var msgs []MaintEventMessage
	lastID := afterID
	for _, stream := range streams {
		for _, msg := range stream.Messages {
			lastID = msg.ID
			kind, _ := msg.Values["kind"].(string)
			msgs = append(msgs, MaintEventMessage{Kind: kind})
		}
	}
	return msgs, lastID, nil
}

// StartMaintEventWatcher starts a background goroutine that reads MaintEventTopic
// and sets the ClusterDegradedWatcher flag when a
// "scaler_replicas_pinned" event is received.
//
// The goroutine exits when ctx is cancelled.  Call this from cmd/api init after
// building the Redis client and watcher — it runs for the lifetime of the
// server process.
func StartMaintEventWatcher(ctx context.Context, reader MaintEventReader, watcher *ClusterDegradedWatcher) {
	go func() {
		afterID := "0" // read from the beginning on startup; only new events matter
		for {
			select {
			case <-ctx.Done():
				return
			default:
			}

			msgs, nextID, err := reader.ReadEvents(ctx, afterID, 5000)
			if err != nil {
				// Log and back off briefly; do not crash — watcher is best-effort.
				time.Sleep(500 * time.Millisecond)
				continue
			}
			afterID = nextID
			for _, msg := range msgs {
				if msg.Kind == "scaler_replicas_pinned" {
					watcher.MarkDegraded()
				}
			}
		}
	}()
}
