// Package sec implements the Phase 7 in-process defense layer that
// guards the Go API gateway BEFORE any handler is reached.
//
// The package owns:
//
//   - Length cap + UTF-8 sanitizer (NFC + control / zero-width strip)
//     mirroring `swarm/agents/sec/input.py::sanitize_text`. The
//     mirror is byte-for-byte deliberate so the Python escalation
//     agent never sees text that the gateway claimed it sanitized.
//
//   - Deterministic injection-pattern engine compiled from
//     `common/security/injection_patterns.yaml`. Patterns use the
//     RE2 portable subset (no backrefs, no lookbehinds) so the same
//     YAML loads in Go and in Python without an extra translation
//     layer. The file is the single source of truth; the Go side
//     embeds a copy that an integrity test asserts is byte-identical.
//
//   - GCRA token-bucket enforcement via Redis Lua scripts
//     (`infra/redis/lua/sec_rate_check.lua`). The Lua script handles
//     the denylist short-circuit + bucket math in a single round-trip;
//     this package handles SCRIPT LOAD lifecycle, NOSCRIPT recovery,
//     and the secondary in-process bucket fail-open path.
//
//   - X-Forwarded-For derivation that walks right-to-left and skips
//     trusted-proxy CIDRs, and IPv6 prefix bucketing (default /64) to
//     stop attackers from spraying 2^64 buckets from a single
//     allocation.
//
//   - Per-endpoint weighted token cost from
//     `common/security/endpoint_costs.yaml`. The mapping must be
//     total over the gateway router; an integrity test asserts every
//     registered route resolves to either an explicit entry or the
//     intentional `default_cost` fallback.
//
// Doctrine recap (binding, ROADMAP §7 + design/SECURITY.md):
//
//  1. Fail-open is the default. A defense surface that goes down
//     must NOT block the happy path. Each fail-open path emits a
//     debounced `sec.alert.v1{kind=...degraded, severity=warn}`.
//
//  2. Password fields bypass NFC/lowercase normalization. Doing
//     otherwise would silently break bcrypt verification for any
//     password containing combining characters or dotted-i.
//
//  3. Defense-in-depth. The in-process tier is line ONE; the Python
//     escalation agent is line TWO. Both apply the same sanitizer.
//
//  4. The on-the-wire `qa.request.v1` envelope is the contract
//     between the gateway and the Python NLP layer. The Go side and
//     the Python side both load the schema from
//     `swarm/sdk/schemas/qa.request.v1.json` (Go via embed); a
//     parity test asserts the embedded copy matches the canonical
//     source byte-for-byte.
package sec
