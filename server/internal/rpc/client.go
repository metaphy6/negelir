package rpc

import "context"

// ApprovedTopic is the Redis Stream key the API gateway consumes to receive
// completed predictions (§9.3 forward contract). The API MUST read this topic
// only — never predict.final (an intermediate swarm-internal topic).
const ApprovedTopic = "predict.approved.v1"

// PredictorRPCClient issues predict.request.v1 RPCs to the swarm bus and
// waits for the predict.approved.v1 reply on the per-pod reply topic (§9.3).
// The concrete implementation uses Redis Streams + XREAD BLOCK; tests inject
// a stub.
type PredictorRPCClient interface {
	// Predict publishes predict.request.v1 and blocks until predict.approved.v1
	// arrives on the per-pod reply topic, or the context deadline is exceeded.
	// Returns (nil, err) when unavailable; caller should 503 consensus_window_blown.
	Predict(ctx context.Context, matchID, marketSet, requestID string) (*PredictionResult, error)
}

// PredictionResult carries the fields decoded from a predict.approved.v1 message.
type PredictionResult struct {
	// PredictionID is the UUIDv7 request_id echoed in the approved envelope.
	PredictionID string
	// ProducedAt is the ISO-8601 UTC produced_at timestamp from the envelope.
	ProducedAt string
	// Body is the JSON prediction payload returned verbatim to the HTTP client.
	Body string
}
