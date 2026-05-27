package api_test

// §9.15 Phase 12 forward-contract: chaos catalogue stubs.
//
// These stubs enumerate the chaos tests that Phase 12 must implement.
// They are present now so the catalogue is visible in CI (t.Skip, not compile
// errors) and so Phase 12 cannot silently skip any scenario.
//
// Named entries mirror the Phase 12 chaos catalogue:
//   chaos-api-redis-flap
//   chaos-api-pg-drop
//   chaos-api-bus-flood
//   chaos-api-jwt-key-purge-mid-request
//   chaos-api-half-replica-kill
//
// Contract: each entry uses t.Skip("Phase 12: <name>") so it shows up
// in `go test -v -list .` and in CI skip counts, never as a failure.

import "testing"

// TestChaos_RedisFlap — chaos-api-redis-flap
//
// Contract (Phase 12):
//   - Force Redis unavailable mid-request (connection drop / timeout).
//   - Assert API returns HTTP 503 (cache-miss fallback or unavailable), NOT
//     a 5xx panic (500 / 502 unhandled exception).
//   - Assert no goroutine panic is written to structured logs.
func TestChaos_RedisFlap(t *testing.T) {
	t.Skip("Phase 12: chaos-api-redis-flap — implement in Phase 12")
}

// TestChaos_PgDrop — chaos-api-pg-drop
//
// Contract (Phase 12):
//   - Kill the Postgres connection pool mid-request.
//   - Assert readyz probe returns 5xx (health degrades).
//   - Assert livez probe stays 200 (process itself is alive).
//   - Assert no unhandled panic is written to structured logs.
func TestChaos_PgDrop(t *testing.T) {
	t.Skip("Phase 12: chaos-api-pg-drop — implement in Phase 12")
}

// TestChaos_BusFlood — chaos-api-bus-flood
//
// Contract (Phase 12):
//   - Flood the message bus topic beyond the configured backpressure threshold.
//   - Assert API engages backpressure mode (429 or Retry-After header).
//   - Assert downstream consumers are not starved (bus head-of-line blocking
//     guard: old messages must not block new low-latency paths).
func TestChaos_BusFlood(t *testing.T) {
	t.Skip("Phase 12: chaos-api-bus-flood — implement in Phase 12")
}

// TestChaos_JWTKeyPurgeMidRequest — chaos-api-jwt-key-purge-mid-request
//
// Contract (Phase 12):
//   - Retire / purge a JWT signing key (kid) while a request bearing a token
//     signed by that key is in-flight.
//   - Assert the in-flight request completes successfully (retired kid tokens
//     remain valid until the claim exp; key rotation does not revoke existing
//     tokens).
//   - Assert subsequent requests with the old kid after its grace window are
//     rejected with 401.
func TestChaos_JWTKeyPurgeMidRequest(t *testing.T) {
	t.Skip("Phase 12: chaos-api-jwt-key-purge-mid-request — implement in Phase 12")
}

// TestChaos_HalfReplicaKill — chaos-api-half-replica-kill
//
// Contract (Phase 12):
//   - In a replicas:3 deployment, kill floor(N/2) replicas simultaneously.
//   - Assert remaining N-1 replicas continue serving requests (no quorum loss).
//   - Assert reply-stream reaper sweeps orphaned in-flight streams left by the
//     killed replicas (no leaked goroutines / dangling response channels).
func TestChaos_HalfReplicaKill(t *testing.T) {
	t.Skip("Phase 12: chaos-api-half-replica-kill — implement in Phase 12")
}
