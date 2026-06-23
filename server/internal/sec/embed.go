package sec

import _ "embed"

// Embedded copies of the canonical security assets. The single source
// of truth lives outside this package (see file headers below); the
// `embedded_parity_test.go` integrity test asserts byte-for-byte
// equality so a drift between the canonical asset and the embedded
// copy is a build-blocking failure.
//
// We embed instead of reading from disk at runtime because:
//   * the Go binary is shipped as a single artifact (no sidecar files
//     to forget on a `kubectl rollout`);
//   * `go embed` happens at compile time, so a missing file fails the
//     build immediately, not at first request;
//   * Lua scripts in particular MUST land with their `-- SHA256:`
//     header intact — embedding closes the door on a deploy that
//     ships a stale on-disk copy alongside a current binary.

// Canonical: infra/redis/lua/sec_rate_check.lua
//
//go:embed embedded/sec_rate_check.lua
var EmbeddedRateCheckLua string

// Canonical: infra/redis/lua/sec_denylist_mutate.lua
//
//go:embed embedded/sec_denylist_mutate.lua
var EmbeddedDenylistMutateLua string

// Canonical: infra/redis/lua/sec_denylist_decimate.lua
//
//go:embed embedded/sec_denylist_decimate.lua
var EmbeddedDecimateLua string

// Canonical: swarm/sdk/schemas/qa.request.v1.json
//
//go:embed embedded/qa.request.v1.json
var EmbeddedQARequestV1Schema []byte

// Canonical: common/security/injection_patterns.yaml
//
//go:embed embedded/injection_patterns.yaml
var EmbeddedInjectionPatternsYAML []byte

// Canonical: common/security/endpoint_costs.yaml
//
//go:embed embedded/endpoint_costs.yaml
var EmbeddedEndpointCostsYAML []byte
