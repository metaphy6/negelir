// Package errors defines the closed enum of application-level error codes
// used by every Phase 9 handler and middleware.
//
// Every HTTP error emitted by server/internal/handlers or
// server/internal/middleware MUST use a code from this package. Ad-hoc
// gin.H{"error": "..."} strings outside this package are rejected by the
// boundary AST scan.
//
// The error body format follows RFC 7807 (application/problem+json):
//
//	{
//	  "type":     "https://negelir.io/problems/<code>",
//	  "title":    "<human-readable title>",
//	  "status":   <HTTP status int>,
//	  "detail":   "<optional per-request detail>",
//	  "instance": "<X-Request-ID>"
//	}
//
// Code taxonomy (mirrors §9.1 closed enum):
//
//	400 invalid_request | invalid_cursor
//	401 unauthenticated | token_expired | token_revoked
//	403 forbidden | tier_required
//	404 not_found | match_retired
//	409 conflict | cursor_filter_drift | idempotency_key_replay_with_different_body
//	410 gone
//	413 payload_too_large
//	415 unsupported_media_type
//	422 unprocessable | qa_quarantined
//	425 too_early
//	429 rate_limited | tier_quota_exceeded | denylisted
//	499 client_disconnected
//	500 internal
//	502 upstream_consensus_failure
//	503 service_unavailable | bus_unreachable | consensus_window_blown
//	504 rpc_timeout
package errors
