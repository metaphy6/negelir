// Package api is the Phase 9 API gateway — the outermost request-handling
// layer of the Go REST server.
//
// Responsibilities:
//   - Route registration and versioned router setup (/v1/...)
//   - Request-ID (UUIDv7) minting and echo
//   - Body-size enforcement (http.MaxBytesReader before handler dispatch)
//   - Fan-in of every accepted request onto the api.request.v1 bus topic
//   - Fan-out of every response onto the api.response.v1 bus topic
//
// This package is the SOLE producer of api.request.v1 and api.response.v1.
// It delegates security gating to server/internal/sec (Phase 7, consumed not
// re-implemented), authentication to server/internal/auth, authorization to
// server/internal/authz, and business logic to server/internal/handlers.
package api
