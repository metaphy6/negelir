// Package rpc implements Phase 9 swarm RPC: publishing predict.request.v1 bus
// messages and waiting for the corresponding predict.approved.v1 reply.
//
// Responsibilities:
//   - Publish predict.request.v1 with a UUIDv7 request_id (minted by the API,
//     never by the swarm) and a reply_to topic keyed per request_id
//   - Block up to cfg.api_request_timeout_ms for a predict.approved.v1 reply
//     (NEVER raw predict.final — see Phase 9.0 §6 forward contract)
//   - Return 503 + Retry-After when the consensus window blows; serve cached
//     result from Redis when available
//   - Maintain reply_to waiters keyed in Redis (stateless replicas safe)
//
// This package never imports torch, cuda, or any ML dependency.
package rpc
