package errors

import (
	"encoding/json"
	"fmt"
	"net/http"

	"github.com/gin-gonic/gin"
)

// Code is the application-level error code string used in RFC 7807 bodies.
// Every code is declared here; no other package may invent an error code
// string -- the boundary AST scan in codes_test.go enforces this.
type Code string

// Closed enum -- mirrors §9.1 HTTP error taxonomy.
const (
	// 400
	CodeInvalidRequest Code = "invalid_request"
	CodeInvalidCursor  Code = "invalid_cursor"

	// 401
	CodeUnauthenticated Code = "unauthenticated"
	CodeTokenExpired    Code = "token_expired"
	CodeTokenRevoked    Code = "token_revoked"

	// 403
	CodeForbidden    Code = "forbidden"
	CodeTierRequired Code = "tier_required"

	// 404
	CodeNotFound     Code = "not_found"
	CodeMatchRetired Code = "match_retired"

	// 409
	CodeConflict                              Code = "conflict"
	CodeCursorFilterDrift                     Code = "cursor_filter_drift"
	CodeIdempotencyKeyReplayWithDifferentBody Code = "idempotency_key_replay_with_different_body"

	// 410
	CodeGone Code = "gone"

	// 413
	CodePayloadTooLarge Code = "payload_too_large"

	// 415
	CodeUnsupportedMediaType Code = "unsupported_media_type"

	// 422
	CodeUnprocessable Code = "unprocessable"
	CodeQAQuarantined Code = "qa_quarantined"
	
	// 426
	CodeUpgradeRequired Code = "upgrade_required"

	// 425
	CodeTooEarly Code = "too_early"

	// 429
	CodeRateLimited       Code = "rate_limited"
	CodeTierQuotaExceeded Code = "tier_quota_exceeded"
	CodeDenylisted        Code = "denylisted"

	// 499 -- audit-only, never sent to client
	CodeClientDisconnected Code = "client_disconnected"

	// 500
	CodeInternal Code = "internal"

	// 502
	CodeUpstreamConsensusFailure Code = "upstream_consensus_failure"

	// 503
	CodeServiceUnavailable   Code = "service_unavailable"
	CodeBusUnreachable       Code = "bus_unreachable"
	CodeConsensusWindowBlown Code = "consensus_window_blown"

	// 504
	CodeRPCTimeout Code = "rpc_timeout"
)

// HTTPStatus maps each Code to its canonical HTTP status integer.
// This is the single authority for status->code assignment; handlers
// must not hardcode numeric status values alongside error strings.
var HTTPStatus = map[Code]int{
	CodeInvalidRequest:                        http.StatusBadRequest,
	CodeInvalidCursor:                         http.StatusBadRequest,
	CodeUnauthenticated:                       http.StatusUnauthorized,
	CodeTokenExpired:                          http.StatusUnauthorized,
	CodeTokenRevoked:                          http.StatusUnauthorized,
	CodeForbidden:                             http.StatusForbidden,
	CodeTierRequired:                          http.StatusForbidden,
	CodeNotFound:                              http.StatusNotFound,
	CodeMatchRetired:                          http.StatusNotFound,
	CodeConflict:                              http.StatusConflict,
	CodeCursorFilterDrift:                     http.StatusConflict,
	CodeIdempotencyKeyReplayWithDifferentBody: http.StatusConflict,
	CodeGone:                                  http.StatusGone,
	CodePayloadTooLarge:                       http.StatusRequestEntityTooLarge,
	CodeUnsupportedMediaType:                  http.StatusUnsupportedMediaType,
	CodeUnprocessable:                         http.StatusUnprocessableEntity,
	CodeQAQuarantined:                         http.StatusUnprocessableEntity,
	CodeUpgradeRequired:                      http.StatusUpgradeRequired,
	CodeTooEarly:                              425,
	CodeRateLimited:                           http.StatusTooManyRequests,
	CodeTierQuotaExceeded:                     http.StatusTooManyRequests,
	CodeDenylisted:                            http.StatusTooManyRequests,
	CodeClientDisconnected:                    499,
	CodeInternal:                              http.StatusInternalServerError,
	CodeUpstreamConsensusFailure:              http.StatusBadGateway,
	CodeServiceUnavailable:                    http.StatusServiceUnavailable,
	CodeBusUnreachable:                        http.StatusServiceUnavailable,
	CodeConsensusWindowBlown:                  http.StatusServiceUnavailable,
	CodeRPCTimeout:                            http.StatusGatewayTimeout,
}

// AllCodes is the exhaustive registry -- the boundary test uses this set to
// verify that no handler emits a code that is not declared here.
var AllCodes = func() map[Code]struct{} {
	m := make(map[Code]struct{}, len(HTTPStatus))
	for c := range HTTPStatus {
		m[c] = struct{}{}
	}
	return m
}()

// titles holds the default human-readable title for each Code.
var titles = map[Code]string{
	CodeInvalidRequest:                        "Invalid request",
	CodeInvalidCursor:                         "Invalid pagination cursor",
	CodeUnauthenticated:                       "Unauthenticated",
	CodeTokenExpired:                          "Token expired",
	CodeTokenRevoked:                          "Token revoked",
	CodeForbidden:                             "Forbidden",
	CodeTierRequired:                          "Subscription tier required",
	CodeNotFound:                              "Not found",
	CodeMatchRetired:                          "Match retired",
	CodeConflict:                              "Conflict",
	CodeCursorFilterDrift:                     "Cursor filter drift",
	CodeIdempotencyKeyReplayWithDifferentBody: "Idempotency key replay with different body",
	CodeGone:                                  "Resource gone",
	CodePayloadTooLarge:                       "Payload too large",
	CodeUnsupportedMediaType:                  "Unsupported media type",
	CodeUnprocessable:                         "Unprocessable entity",
	CodeQAQuarantined:                         "Q&A input quarantined",
	CodeUpgradeRequired:                      "Upgrade required",
	CodeTooEarly:                              "Too early - consensus warming",
	CodeRateLimited:                           "Rate limited",
	CodeTierQuotaExceeded:                     "Tier quota exceeded",
	CodeDenylisted:                            "Denylisted",
	CodeClientDisconnected:                    "Client disconnected",
	CodeInternal:                              "Internal server error",
	CodeUpstreamConsensusFailure:              "Upstream consensus failure",
	CodeServiceUnavailable:                    "Service unavailable",
	CodeBusUnreachable:                        "Bus unreachable",
	CodeConsensusWindowBlown:                  "Consensus window blown",
	CodeRPCTimeout:                            "RPC timeout",
}

const problemBase = "https://negelir.io/problems/"

// Problem is the RFC 7807 response body (application/problem+json).
type Problem struct {
	Type     string `json:"type"`
	Title    string `json:"title"`
	Status   int    `json:"status"`
	Detail   string `json:"detail,omitempty"`
	Instance string `json:"instance,omitempty"`
}

// NewProblem builds a Problem for the given Code. detail and instance are
// optional; pass empty string to omit them from the serialised body.
func NewProblem(code Code, detail, instance string) Problem {
	status := HTTPStatus[code]
	t := titles[code]
	if t == "" {
		t = string(code)
	}
	return Problem{
		Type:     problemBase + string(code),
		Title:    t,
		Status:   status,
		Detail:   detail,
		Instance: instance,
	}
}

// Fixed Retry-After values (seconds) for the three 503 sub-codes per §9.3
// contract. The service_unavailable value is dynamic (computed from
// cfg.api_request_timeout_ms); callers must supply it via RespondWithRetryAfter.
const (
	RetryAfterBusUnreachable       = 5
	RetryAfterConsensusWindowBlown = 10
)

// RetryAfterForTimeout returns the Retry-After value in seconds for a
// service_unavailable 503 caused by an RPC timeout, per §9.3:
//
//	ceil(api_request_timeout_ms / 1000) + 1
func RetryAfterForTimeout(requestTimeoutMs int) int {
	secs := requestTimeoutMs / 1000
	if requestTimeoutMs%1000 != 0 {
		secs++
	}
	return secs + 1
}

// Respond writes an RFC 7807 application/problem+json response to c.
// It reads the request_id from the Gin context (set by the RequestID
// middleware) and populates the instance field automatically.
// The caller must call c.Abort() if further middleware chain execution
// should be stopped.
func Respond(c *gin.Context, code Code, detail string) {
	instance := c.GetString("request_id")
	p := NewProblem(code, detail, instance)
	b, _ := json.Marshal(p)
	c.Data(HTTPStatus[code], "application/problem+json", b)
}

// RespondWithRetryAfter is identical to Respond but also sets the
// Retry-After header to retryAfterSecs. Use this for every 503 response
// per the §9.3 503 + Retry-After contract.
func RespondWithRetryAfter(c *gin.Context, code Code, detail string, retryAfterSecs int) {
	c.Header("Retry-After", fmt.Sprintf("%d", retryAfterSecs))
	Respond(c, code, detail)
}
