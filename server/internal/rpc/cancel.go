package rpc

import (
	"context"
)

// CancelTopic is the Redis Stream key for predict.cancel.v1 messages.
//
// Single-producer / single-consumer contract (§9.3):
//   - Producer: api.gateway.v1 (this package, WatchAndCancel only)
//   - Consumer: consensus.v1
//
// This constant is the authoritative string; the AST boundary test in
// cancel_test.go enforces that no other package in the server tree
// references the literal "predict.cancel.v1".
const CancelTopic = "predict.cancel.v1"

// CancelMessage is the payload published to predict.cancel.v1.
type CancelMessage struct {
	// RequestID is the UUIDv7 request_id minted at the API gateway (§9.3).
	// consensus.v1 uses it to look up the in-flight row and mark it cancelled.
	RequestID string `json:"request_id"`
}

// CancelPublisher publishes predict.cancel.v1 messages to the bus.
//
// Single producer contract: only api.gateway.v1 (via WatchAndCancel) calls
// PublishCancel.  The implementation is injected at startup so the handler
// is unit-testable without a live Redis/bus.
type CancelPublisher interface {
	PublishCancel(ctx context.Context, msg CancelMessage) error
}

// WatchAndCancel monitors clientCtx for client disconnection and, when the
// client disconnects before the RPC is complete, publishes
// predict.cancel.v1{request_id} to the bus via pub.
//
// Idempotency / race contract (§9.3):
//
//	If rpcDone is already closed when clientCtx.Done() fires — meaning the
//	RPC completed (predict.final received or timeout expired) at the same
//	instant the client disconnected — the cancel is dropped silently.
//	No alert is raised; this race is expected and not pathological.
//
// Usage: call in a goroutine alongside the XREAD wait:
//
//	done := make(chan struct{})
//	go func() { defer close(done); waitForReply(...) }()
//	go WatchAndCancel(c.Request.Context(), done, requestID, pub)
//
// The publish uses context.Background() because clientCtx is already
// cancelled at publish time; the message must still reach the bus.
func WatchAndCancel(clientCtx context.Context, rpcDone <-chan struct{}, requestID string, pub CancelPublisher) {
	select {
	case <-rpcDone:
		// RPC completed first — cancellation would be a no-op at consensus.v1;
		// drop without alerting (§9.3 idempotency contract).
		return
	case <-clientCtx.Done():
		// Client disconnected. Guard against the simultaneous-completion race:
		// if rpcDone is also ready, prefer the "completed" path.
		select {
		case <-rpcDone:
			return
		default:
		}
		// Publish cancel. Use context.Background() — clientCtx is already
		// cancelled and cannot carry the publish.
		_ = pub.PublishCancel(context.Background(), CancelMessage{RequestID: requestID})
	}
}
