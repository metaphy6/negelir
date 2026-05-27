// Package handlers contains the Phase 9 HTTP handler functions wired to the
// Gin router by server/internal/api.
//
// Handler map (mirrors §9.1 route table):
//   - healthz / readyz / version
//   - leagues + fixtures catalog
//   - match detail + ETag/If-None-Match conditional GET
//   - predictions (RPC path through server/internal/rpc)
//   - Q&A POST /v1/qa (Phase 10 NLP path, 202/200 depending on cache)
//   - auth register / login / refresh / logout
//   - me GET + PATCH
//   - me/quota (dormant until Phase 20)
//
// Every handler returns Content-Type application/json or
// application/problem+json (RFC 7807); no other content type is legal.
// All error codes come exclusively from server/internal/errors.
package handlers
