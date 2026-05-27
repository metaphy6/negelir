// Package config is the Go server's single source of truth for tunables.
//
// Mirrors the Python pattern in ai/common/config.py: every field is loaded
// from an env var with a documented default, and Validate() catches obvious
// misconfiguration (bad ports, negative timeouts, missing URLs).
//
// Sync with .env.example is enforced by sync_test.go.
package config

import (
	"errors"
	"fmt"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
)

// Config holds every env-driven knob the Go middleware server reads.
//
// The `env` and `default` struct tags are the *contract* used by the
// sync_test.go parity check against .env.example. Keep them in sync.
type Config struct {
	// Connection strings (overrides; if empty, derived from POSTGRES_* / REDIS_*).
	DatabaseURL string `env:"DATABASE_URL"      default:""`
	RedisURL    string `env:"REDIS_URL"         default:""`

	// Shared with Python (ai/common/config.py) — marked `# shared` in .env.example.
	PostgresHost     string `env:"POSTGRES_HOST"     default:"postgres"`
	PostgresPort     string `env:"POSTGRES_PORT"     default:"5432"`
	PostgresDB       string `env:"POSTGRES_DB"       default:"negelir"`
	PostgresUser     string `env:"POSTGRES_USER"     default:"negelir"`
	PostgresPassword string `env:"POSTGRES_PASSWORD" default:""`
	RedisHost        string `env:"REDIS_HOST"        default:"redis"`
	RedisPort        string `env:"REDIS_PORT"        default:"6379"`

	// Go-only knobs.
	Port                     string `env:"SERVER_PORT"               default:"8080"`
	DBMaxConns               int    `env:"DB_MAX_CONNS"              default:"10"`
	DBConnectTimeoutSec      int    `env:"DB_CONNECT_TIMEOUT_SEC"    default:"5"`
	DBPingTimeoutSec         int    `env:"DB_PING_TIMEOUT_SEC"       default:"5"`
	DBRetryDelaySec          int    `env:"DB_RETRY_DELAY_SEC"        default:"3"`
	RedisRetryDelaySec       int    `env:"REDIS_RETRY_DELAY_SEC"     default:"2"`
	HTTPReadTimeoutSec       int    `env:"HTTP_READ_TIMEOUT_SEC"     default:"10"`
	HTTPWriteTimeoutSec      int    `env:"HTTP_WRITE_TIMEOUT_SEC"    default:"30"`
	HTTPHandlerTimeoutSec    int    `env:"HTTP_HANDLER_TIMEOUT_SEC"  default:"25"`
	HTTPShutdownTimeoutSec   int    `env:"HTTP_SHUTDOWN_TIMEOUT_SEC" default:"5"`
	CacheMatchesTTLSec       int    `env:"CACHE_MATCHES_TTL_SEC"     default:"300"`
	CacheTeamsTTLSec         int    `env:"CACHE_TEAMS_TTL_SEC"       default:"600"`

	// Shared with Python (ai/common/config.py) — used by `swarmctl` to
	// compute the dead-after-3-missed-heartbeats marker. Marked `# shared`
	// in .env.example.
	SwarmHeartbeatSec int `env:"SWARM_HEARTBEAT_SEC" default:"5"`

	// Phase 7 §7.1 / §7.3 — defense-agent knobs SHARED with the Python
	// `sec.*` agents (ai/swarm/agents/sec/). The Go gateway runs the
	// in-process tier (length cap, deterministic rules, GCRA bucket via
	// EVALSHA, denylist short-circuit); the Python agents own the
	// escalation classifier + denylist mutation + burst detection. Both
	// sides MUST read the same env var so a single operator knob lands
	// on both surfaces. All marked `# shared` in .env.example.
	SecInputMaxLen               int     `env:"NEGELIR_SEC_INPUT_MAX_LEN"               default:"8192"`
	SecInputGatewayMaxLatencyMs  int     `env:"NEGELIR_SEC_INPUT_GATEWAY_MAX_LATENCY_MS" default:"10"`
	SecInputPatternReloadSec     int     `env:"NEGELIR_SEC_INPUT_PATTERN_RELOAD_S"      default:"30"`
	SecQuarantinePayloadMaxBytes int     `env:"NEGELIR_SEC_QUARANTINE_PAYLOAD_MAX_BYTES" default:"65536"`
	SecRatePreAuthCapacity       int     `env:"NEGELIR_SEC_RATE_PRE_AUTH_CAPACITY"      default:"30"`
	SecRatePreAuthRefillPerS     float64 `env:"NEGELIR_SEC_RATE_PRE_AUTH_REFILL_PER_S"  default:"0.5"`
	SecRatePostAuthCapacity      int     `env:"NEGELIR_SEC_RATE_POST_AUTH_CAPACITY"     default:"600"`
	SecRatePostAuthRefillPerS    float64 `env:"NEGELIR_SEC_RATE_POST_AUTH_REFILL_PER_S" default:"5.0"`
	SecRateBucketIdleTTLSec      int     `env:"NEGELIR_SEC_RATE_BUCKET_IDLE_TTL_S"      default:"3600"`
	SecRateIPv4Prefix            int     `env:"NEGELIR_SEC_RATE_IPV4_PREFIX"            default:"32"`
	SecRateIPv6Prefix            int     `env:"NEGELIR_SEC_RATE_IPV6_PREFIX"            default:"64"`
	SecRateTrustedProxies        string  `env:"NEGELIR_SEC_RATE_TRUSTED_PROXIES"        default:""`
	SecRateRedisTimeoutMs        int     `env:"NEGELIR_SEC_RATE_REDIS_TIMEOUT_MS"       default:"50"`
	SecRateSecondaryCapacity     int     `env:"NEGELIR_SEC_RATE_SECONDARY_CAPACITY"     default:"300"`
	SecRateSecondaryRefillPerS   float64 `env:"NEGELIR_SEC_RATE_SECONDARY_REFILL_PER_S" default:"5.0"`
	SecRateDefaultCost           int     `env:"NEGELIR_SEC_RATE_DEFAULT_COST"           default:"1"`
	SecDenylistMaxEntries        int     `env:"NEGELIR_SEC_DENYLIST_MAX_ENTRIES"        default:"250000"`

	// Phase 9 §9.0 SLA budget — enforced by Validate() so the operator
	// cannot configure an API timeout shorter than the full prediction path.
	// §3.3 contract: APIRequestTimeoutMs ≥ ConsensusWindowMs +
	// APIConsensusOverheadMs + ProofreaderQuorumWindowMs.
	// ConsensusWindowMs, APIConsensusOverheadMs, and ProofreaderQuorumWindowMs
	// are shared with the Python AI pipeline (marked `# shared` in .env.example).
	APIRequestTimeoutMs     int `env:"NEGELIR_API_REQUEST_TIMEOUT_MS"        default:"2500"`
	ConsensusWindowMs       int `env:"NEGELIR_CONSENSUS_WINDOW_MS"           default:"750"`
	APIConsensusOverheadMs  int `env:"NEGELIR_API_CONSENSUS_OVERHEAD_MS"     default:"200"`
	ProofreaderQuorumWindowMs int `env:"NEGELIR_PROOFREADER_QUORUM_WINDOW_MS" default:"200"`

	// Phase 9 §9.1 — time discipline. The only legal value is "iso8601_utc".
	// Validator rejects anything else; leaves room for a future "rfc9557"
	// extension behind a flag without allowing operator typos.
	APITimeFormat string `env:"NEGELIR_API_TIME_FORMAT" default:"iso8601_utc"`

	// Phase 9 §9.1 — cursor TTL. How long (in seconds) an encrypted
	// pagination cursor remains valid. Default 1800 s (30 min).
	// Cursors sealed after this duration unseal with ErrInvalidCursor.
	APICursorTTLSec int `env:"NEGELIR_API_CURSOR_TTL_S" default:"1800"`

	// Phase 9 §9.1 — body-size cap (bcrypt-bomb / RAM-exhaustion defense).
	// Applied via http.MaxBytesReader before handler dispatch. Sub-caps are
	// validated to not exceed the global cap.
	APIRequestMaxBytes int `env:"NEGELIR_API_REQUEST_MAX_BYTES" default:"65536"`
	QAInputMaxBytes    int `env:"NEGELIR_QA_INPUT_MAX_BYTES"    default:"4096"`
	AuthLoginMaxBytes  int `env:"NEGELIR_AUTH_LOGIN_MAX_BYTES"  default:"4096"`

	// Phase 9 §9.2 — bcrypt cost knob. Must be in [10, 14]; default 12 matches
	// OWASP 2024 floor. The startup probe refuses boot if cost < 10 or if a
	// test hash completes in under 100 ms (see auth.ProbeBcryptCost).
	APIBcryptCost int `env:"NEGELIR_API_BCRYPT_COST" default:"12"`

	// Phase 9 §9.2 — JWT RS256 key-store directory.
	// Private key files (<kid>.priv.pem) live here at mode 0400.
	// The DB (jwt_keys table, migration 014) is the source of truth; disk is
	// the key-material store. Default is relative to the working directory
	// (inside the container it maps to /app/data/api/jwt_keys).
	APIJWTKeyDir string `env:"NEGELIR_API_JWT_KEY_DIR" default:"data/api/jwt_keys"`

	// Phase 9 §9.2 — how often (seconds) each replica polls the keystore dir
	// for newly written key files. The poll is an optimisation; the DB is the
	// authoritative key-status source. Default 10 s.
	APIJWTKeyPollSec int `env:"NEGELIR_API_JWT_KEY_POLL_S" default:"10"`

	// Phase 9 §9.2 — grace period (seconds) after a key is retired before its
	// private key file is zeroized and removed. Must be ≥ cfg.api_access_ttl_s
	// + 60s so all issued tokens can complete validation before the key is
	// purged. Default 960 s (900 s access-token TTL + 60 s buffer).
	APIJWTRetiredGraceSec int `env:"NEGELIR_API_JWT_RETIRED_GRACE_S" default:"960"`

	// Phase 9 §9.14 — clock-skew tolerance for JWT `exp` / `nbf` validation.
	// Tokens whose `exp` is in the past by at most this many seconds are still
	// accepted (covers minor clock drift between the issuer and the verifier).
	// SECURITY: must be kept small; OWASP recommends ≤ 60 s. Default 30 s.
	// Values > 300 s are rejected by Validate() as operationally dangerous.
	APIJWTClockSkewS int `env:"NEGELIR_API_JWT_CLOCK_SKEW_S" default:"30"`

	// Phase 9 §9.2 — token shape.
	// Access JWT TTL in seconds; exp claim = now + this value. Default 900 s (15 min).
	APIAccessTTLSec int `env:"NEGELIR_API_ACCESS_TTL_S" default:"900"`
	// Refresh token TTL in seconds; the Redis key expires after this duration.
	// Default 2592000 s (30 days).
	APIRefreshTTLSec int `env:"NEGELIR_API_REFRESH_TTL_S" default:"2592000"`
	// Grace window (seconds) for single-use refresh token replay: within this
	// window the superseded token is accepted once (idempotency for network
	// retries). After the window, a replay → 401 + sec.alert.v1. Default 30 s.
	APIRefreshReplayGraceSec int `env:"NEGELIR_API_REFRESH_REPLAY_GRACE_S" default:"30"`

	// Phase 9 §9.2 — access-token revocation deny-set cap.
	// Maximum JTIs held in auth:rev:idx at any time. Oldest entries are evicted
	// (LRU) when the cap is exceeded. Operator alerted at 80% via
	// sec.alert.v1{kind=jti_revocation_set_pressure}. Default 10000.
	APIRevocationSetMax int `env:"NEGELIR_API_REVOCATION_SET_MAX" default:"10000"`

	// Phase 9 §9.2 — self-registration flag. When false (the default), POST
	// /v1/auth/register returns 403 forbidden unconditionally. Set true to
	// open registration. See also APIRegisterCapPerSubnetPerH.
	APISelfRegistrationEnabled bool `env:"NEGELIR_API_SELF_REGISTRATION_ENABLED" default:"false"`
	// Phase 9 §9.2 — per-/24 subnet registration cap per hour. When self-
	// registration is enabled, no more than this many registrations are accepted
	// from any single /24 (IPv4) or /64 (IPv6) subnet in a sliding 1-hour window
	// (tracked in Redis). Prevents mass-account-spray. Default 20.
	APIRegisterCapPerSubnetPerH int `env:"NEGELIR_API_REGISTER_CAP_PER_SUBNET_PER_H" default:"20"`

	// Phase 9 §9.2 — mTLS to internal services.
	// When true, the API dials Redis, Postgres, and the bus with a client cert
	// signed by the Phase 2 internal CA.  The boot probe checks each connection
	// before the public listener opens; a handshake failure causes a hard boot
	// refusal (no silent plaintext fallback).
	// Default false (dev/test); set true in production.
	APIMTLSEnabled bool   `env:"NEGELIR_API_MTLS_ENABLED" default:"false"`
	// Directory holding the API's mTLS cert bundle:
	//   ca.crt              — Phase 2 internal CA copy
	//   client_{redis,pg,bus}.{crt,key}  — per-service client certs (keys 0400)
	// Default: data/api/tls
	APITLSDir      string `env:"NEGELIR_API_TLS_DIR" default:"data/api/tls"`

	// Phase 9 §9.3 — idempotency-key cache TTL (seconds). Redis key
	// idem:<sha256(subjectID|method|path|Idempotency-Key-header)> holds the
	// stored response for this duration. Default 86400 s (24 h).
	APIIdempotencyTTLS int `env:"NEGELIR_API_IDEMPOTENCY_TTL_S" default:"86400"`

	// Phase 9 §9.3 — inflight wait timeout (ms). When a second request arrives
	// for the same Idempotency-Key while the first is still processing, the
	// second blocks on a Redis pubsub channel for this duration before returning
	// 425 too_early. Default 1500 ms.
	APIIdempotencyInflightWaitMs int `env:"NEGELIR_API_IDEMPOTENCY_INFLIGHT_WAIT_MS" default:"1500"`

	// Phase 9 §9.3 — per-pod reply_to stream reaper interval (seconds).
	// The API reaper sweeps stale api.reply.* Redis Streams that were created
	// for predict.request RPCs that never received a reply (pod crash, timeout
	// race, etc.). Streams are deleted if they are older than
	// cfg.api_request_timeout_ms and still present. Default 60 s.
	APIReplyReaperSec int `env:"NEGELIR_API_REPLY_REAPER_S" default:"60"`

	// Phase 9 §9.3 — transit jitter budget (ms). Additional slack added to the
	// timeout-budget inequality to absorb network and scheduling jitter between
	// the API pod and the bus/consensus layer. Must be ≥ 0. Default 100 ms.
	// Validate() enforces:
	//   APIRequestTimeoutMs ≥ ConsensusWindowMs + ProofreaderQuorumWindowMs +
	//                         APIConsensusOverheadMs + APITransitJitterMs
	APITransitJitterMs int `env:"NEGELIR_API_TRANSIT_JITTER_MS" default:"100"`

	// Phase 9 §9.7 — burst budget. Per-subject token-bucket capacity (max
	// tokens accumulated while the client is idle). Default 60 tokens.
	// api_burst_refill_per_s: tokens added per second. Default 2.0.
	// These drive the in-process SecondaryBucket (the GCRA fallback tier).
	APIBurstCapacity   int     `env:"NEGELIR_API_BURST_CAPACITY"    default:"60"`
	APIBurstRefillPerS float64 `env:"NEGELIR_API_BURST_REFILL_PER_S" default:"2.0"`

	// Phase 9 §9.7 — tier quota enforcement flag. Built-but-dormant (Phase 20
	// activates it for paying tiers). When false (the default), the TierQuota
	// middleware is a no-op pass-through and neither Redis nor the tiers table
	// is consulted. Set true to enforce per-tier daily_request_cap.
	APITierEnforcementEnabled bool `env:"NEGELIR_API_TIER_ENFORCEMENT_ENABLED" default:"false"`

	// Phase 9 §9.9 — backpressure threshold for the predict.request.v1 stream.
	// The §8.x scaler sets Redis key api:backpressure:on (TTL 30 s) when
	// XLEN(predict.request.v1) exceeds this value. The API reads that flag to
	// engage cache-only mode; it never reads XLEN directly. Default 5000.
	APIPredictRequestBacklogHigh int `env:"NEGELIR_API_PREDICT_REQUEST_BACKLOG_HIGH" default:"5000"`

	// Phase 9 §9.9 — connection cap / concurrency semaphore.
	// Maximum number of concurrently in-flight requests the API pod will serve.
	// Enforced by ConcurrencyLimit middleware (buffered-channel semaphore):
	// a non-blocking acquire succeeds when a slot is free; overflow → 503
	// immediately with X-Overflow: true. Default 5000.
	APIMaxConcurrentRequests int `env:"NEGELIR_API_MAX_CONCURRENT_REQUESTS" default:"5000"`

	// Phase 9 §9.9 — response-side backpressure. When the client's TCP send
	// buffer is full and the handler has been waiting longer than this value
	// (milliseconds) for the write to drain, the SlowClientAbort middleware
	// detects the context cancellation and records status=499 client_disconnected
	// in the access log before aborting the handler. The http.Server WriteTimeout
	// (HTTP_WRITE_TIMEOUT_SEC) is the hard OS-level cutoff; this middleware sets
	// the semantic error code so the access log captures the disconnect.
	// Default 5000 ms (5 s) — matching nginx's upstream response timeout default.
	APIResponseWriteTimeoutMs int `env:"NEGELIR_API_RESPONSE_WRITE_TIMEOUT_MS" default:"5000"`

	// Phase 9 §9.3 — stale-while-revalidate (SWR) cache knobs for the predictions endpoint.
	// A cache entry younger than APICacheStaleAfterS is served as a fresh HIT
	// (X-Cache: hit). Between APICacheStaleAfterS and APICacheMaxAgeS it is
	// served as stale (X-Cache: stale) while an async predict.request refresh
	// is triggered. Older than APICacheMaxAgeS (or absent) → cache miss, RPC
	// is issued. Defaults: stale_after=30 s, max_age=300 s.
	APICacheStaleAfterS int `env:"NEGELIR_API_CACHE_STALE_AFTER_S" default:"30"`
	APICacheMaxAgeS     int `env:"NEGELIR_API_CACHE_MAX_AGE_S"     default:"300"`

	// Phase 9 §9.3 — pod-level cap on concurrent SWR async refreshes.
	// A Redis SETNX gate (swr_lock:<match_id>:<market_set>) limits to 1
	// inflight refresh per unique (match_id, market_set). This counter caps
	// the total number of such goroutines across the pod. Default 64.
	APISWRInflightMax int `env:"NEGELIR_API_SWR_INFLIGHT_MAX" default:"64"`

	// Phase 9 §9.15 / Phase 11 (compute) boundary — the API binary is always
	// built cpu_only; cgo CUDA paths are excluded via the build tag. The only
	// valid value at v1 is "cpu_only". Validate() rejects any other value so
	// the operator cannot accidentally enable a CUDA path that does not exist
	// in the binary. Phase 11 may extend this allowlist to "gpu_optional".
	ComputeClass string `env:"NEGELIR_COMPUTE_CLASS" default:"cpu_only"`

	// Phase 9 §9.8 — RED metrics. The Prometheus /metrics endpoint is served
	// on a SEPARATE internal-only port (never the public API port) to prevent
	// accidental exposure. Default :9091.
	// Validate() rejects the value if it collides with cfg.Port.
	TelemetryMetricsPort string `env:"NEGELIR_TELEMETRY_METRICS_PORT" default:"9091"`

	// Phase 9 §9.8 — cardinality cap. The boot validator computes the
	// worst-case series count for api_requests_total and refuses to start if
	// it would exceed this value. Default 10000 (the 30-route spec example
	// produces 5760, which is well below the cap).
	TelemetryMaxSeries int `env:"NEGELIR_TELEMETRY_MAX_SERIES" default:"10000"`

	// Phase 9 §9.8 — structured access log sampling. Percentage of 2xx
	// responses written to the JSON access log on os.Stderr. Range [0, 100].
	// 4xx / 5xx are always logged regardless of this value.
	// Default 10 (prod-safe); override to 100 in dev / test environments.
	APILogSamplePct int `env:"NEGELIR_API_LOG_SAMPLE_PCT" default:"10"`

	// Phase 9 §9.8 — OTLP gRPC trace export endpoint.
	// Format: "host:port" (no scheme). When empty (the default) the entire
	// tracing subsystem is a deliberate no-op: no goroutines, no connections,
	// no stdout-JSON trace dump. When set, spans are exported via OTLP gRPC to
	// an OTel Collector sidecar (or any compatible backend).
	// Example: "otelcol:4317"
	TelemetryOTLPEndpoint string `env:"NEGELIR_TELEMETRY_OTLP_ENDPOINT" default:""`

	// Phase 9 §9.8 — SLO burn-rate alert knobs. BurnWindowS is both the long
	// evaluation window and the check interval (seconds). The short window is
	// BurnWindowS/12 (e.g., 300 s for the default 3600 s window). BurnThreshold
	// is the error-budget-consumption multiple at which a warn alert fires via
	// sec.alert.v1{kind=api_slo_burn}; critical fires at 3× the threshold.
	// Defaults: window=3600 s (1 h), threshold=2.0.
	APISLOBurnWindowS   int     `env:"NEGELIR_API_SLO_BURN_WINDOW_S"   default:"3600"`
	APISLOBurnThreshold float64 `env:"NEGELIR_API_SLO_BURN_THRESHOLD"  default:"2.0"`

	// Phase 9 §9.11 — deprecation window (days). Minimum number of days between
	// when a route is marked deprecated (x-deprecated-on) and when the API
	// returns 410 Gone (x-sunset-on or derived from this value). Must be ≥ 1.
	// Default 90 days (the §9.11 contract minimum). The DeprecationHeaders
	// middleware (server/internal/middleware/deprecation.go) uses this as the
	// fallback when x-sunset-on is absent from the OpenAPI spec operation.
	APIDeprecationWindowDays int `env:"NEGELIR_API_DEPRECATION_WINDOW_DAYS" default:"90"`

	// Phase 9 §9.11 — schema-version stamp. Stamped on every JSON response as
	// meta.schema_version via SchemaVersionMiddleware. Increments additively
	// with each server minor version (per chart.json). Client SDKs key cache
	// invalidation on this value. Must be ≥ 1. Default 1.
	APISchemaVersion int `env:"NEGELIR_API_SCHEMA_VERSION" default:"1"`

	// Phase 9 §9.12 — §9.12 knob inventory additions.
	// Maximum number of days ahead a fixture query may request. Requests
	// outside this window are rejected with 400 fixture_window_exceeded.
	APIFixtureWindowMaxDays int `env:"NEGELIR_API_FIXTURE_WINDOW_MAX_DAYS" default:"14"`
	// Comma-separated list of market codes the API accepts (case-insensitive).
	// Requests containing any other code are rejected with 400 unknown_market.
	APIAllowedMarkets string `env:"NEGELIR_API_ALLOWED_MARKETS" default:"ms,au_2.5,btts,ah_home,modal_score"`
	// Comma-separated list of trusted reverse-proxy CIDRs or IP addresses
	// from which X-Forwarded-For is accepted. Empty = no trusted proxies
	// (client IP is taken directly from RemoteAddr).
	APITrustedProxies string `env:"NEGELIR_API_TRUSTED_PROXIES" default:""`

	// Phase 9 §9.17.1 — Go runtime tuning (refuse-to-start gates).

	// GOMEMLIMIT: mebibytes cap passed to debug.SetMemoryLimit at boot.
	// 0 = derive from cgroup memory.max at 80%; refuse boot if cgroup is
	// unreadable AND this value is 0 (prevents unbounded heap).
	APIGoMemLimitMiB int `env:"NEGELIR_API_GO_MEM_LIMIT_MIB" default:"0"`

	// GOGC: GC target percentage. Default 50 (half of Go's default 100)
	// because JSON encode + Redis pipeline creates many short-lived objects.
	// Passed to runtime/debug.SetGCPercent at boot.
	APIGoGCPercent int `env:"NEGELIR_API_GO_GC_PERCENT" default:"50"`

	// HTTP server timeout knobs (§9.17.1) — Slowloris / idle-connection defense.
	// These supersede the legacy HTTP_READ_TIMEOUT_SEC / HTTP_WRITE_TIMEOUT_SEC
	// knobs for the public listener; the legacy knobs remain for backward compat.
	APIReadHeaderTimeoutMs int `env:"NEGELIR_API_READ_HEADER_TIMEOUT_MS" default:"5000"`
	APIReadTimeoutMs       int `env:"NEGELIR_API_READ_TIMEOUT_MS"        default:"10000"`
	// WriteTimeout must exceed api_request_timeout_ms + api_response_write_timeout_ms;
	// Validate() enforces this invariant.
	APIWriteTimeoutMs int `env:"NEGELIR_API_WRITE_TIMEOUT_MS" default:"15000"`
	APIIdleTimeoutMs  int `env:"NEGELIR_API_IDLE_TIMEOUT_MS"  default:"60000"`

	// SIGTERM → server.Shutdown grace period (seconds). K8s preStop hook
	// should sleep 5 s to bridge endpoint-removal lag before SIGTERM arrives.
	APIShutdownGraceS int `env:"NEGELIR_API_SHUTDOWN_GRACE_S" default:"30"`

	// In-mesh H2C listener port. H2C (HTTP/2 cleartext) is enabled ONLY on
	// this listener (in-cluster sidecar, behind mTLS) — never on the public
	// API port. 0 = disabled.
	APIInMeshPort string `env:"NEGELIR_API_IN_MESH_PORT" default:"8082"`

	// Phase 9 §9.17.3 — Connection pool sizing.

	// PostgreSQL pgxpool knobs.
	// APIPGPoolMaxConns: maximum open connections per pod. Default 25.
	// Boot validator refuses if the formula (cgroup_cpu*4 vs pg_max_connections*0.25/replicas)
	// would push the cluster past 80% of pg_max_connections — operator must set
	// NEGELIR_PG_MAX_CONNECTIONS to enable that check.
	APIPGPoolMaxConns int `env:"NEGELIR_API_PG_POOL_MAX_CONNS" default:"25"`

	// Read replica routing — built but dormant (empty = disabled).
	// When set, GET requests are routed to the replica pool; POST/PATCH/DELETE
	// always use the primary. Replica lag is checked via pg_last_wal_replay_lsn
	// every APIPGReplicaLagCheckS seconds; lag > APIPGReplicaLagMaxMs causes
	// fallback to primary and emits sec.alert.v1{kind=pg_replica_lag_high}.
	APIPGReplicaURL       string `env:"NEGELIR_API_PG_REPLICA_URL"          default:""`
	APIPGReplicaLagCheckS int    `env:"NEGELIR_API_PG_REPLICA_LAG_CHECK_S"  default:"10"`
	APIPGReplicaLagMaxMs  int    `env:"NEGELIR_API_PG_REPLICA_LAG_MAX_MS"   default:"500"`

	// Redis pool knobs — two distinct clients with different SLOs.
	// cacheClient: PoolSize=APIRedisCachePoolSize (default 50), MinIdleConns=10,
	//   PoolTimeout=100ms (fail fast → MISS). MaxRetries=0 (resilience layer owns retries).
	// busClient: PoolSize=APIRedisBusPoolSize (default 20), ReadTimeout=request_timeout+500ms
	//   (XREAD BLOCK budget). MaxRetries=0.
	APIRedisCachePoolSize int `env:"NEGELIR_API_REDIS_CACHE_POOL_SIZE" default:"50"`
	APIRedisBusPoolSize   int `env:"NEGELIR_API_REDIS_BUS_POOL_SIZE"   default:"20"`

	// Phase 9 §9.17.4 — Resilience: circuit breakers, bulkheads, hedging, retry budgets.

	// Circuit breaker knobs (sony/gobreaker). One breaker per upstream:
	// pg, redis_cache, redis_bus, swarm_rpc.
	// APIBreakerFailRatio: failure fraction that trips the breaker. Default 0.5.
	APIBreakerFailRatio float64 `env:"NEGELIR_API_BREAKER_FAIL_RATIO" default:"0.5"`
	// APIBreakerWindowS: rolling window in seconds for counting requests. Default 10.
	APIBreakerWindowS int `env:"NEGELIR_API_BREAKER_WINDOW_S" default:"10"`
	// APIBreakerMinRequests: minimum call count before the breaker may trip. Default 20.
	APIBreakerMinRequests int `env:"NEGELIR_API_BREAKER_MIN_REQUESTS" default:"20"`
	// APIBreakerOpenS: seconds the breaker stays open before admitting one probe. Default 15.
	APIBreakerOpenS int `env:"NEGELIR_API_BREAKER_OPEN_S" default:"15"`

	// Hedged RPC knobs (cache-miss path only).
	// APIHedgeAfterMs: ms after the primary RPC before issuing a hedge. Default 200.
	APIHedgeAfterMs int `env:"NEGELIR_API_HEDGE_AFTER_MS" default:"200"`
	// APIHedgingEnabled: master switch for hedged RPC. Default true.
	APIHedgingEnabled bool `env:"NEGELIR_API_HEDGING_ENABLED" default:"true"`
	// APIHedgeBudgetPct: max percentage of recent RPCs that may be hedged. Default 10.
	APIHedgeBudgetPct int `env:"NEGELIR_API_HEDGE_BUDGET_PCT" default:"10"`

	// Retry budget (token bucket per upstream).
	// APIRetryBudgetPerS: tokens per second refill rate. Default 10.
	APIRetryBudgetPerS float64 `env:"NEGELIR_API_RETRY_BUDGET_PER_S" default:"10"`
	// APIRetryBudgetCapacity: burst capacity (max tokens). Default 50.
	APIRetryBudgetCapacity int `env:"NEGELIR_API_RETRY_BUDGET_CAPACITY" default:"50"`

	// Phase 9 §9.17.5 — k6 bench target.
	// APIBenchTargetRPS: target RPS for `make api.bench` (k6 constant-arrival-rate).
	// Default 200. The k6 script reads NEGELIR_API_BENCH_TARGET_RPS at runtime.
	APIBenchTargetRPS int `env:"NEGELIR_API_BENCH_TARGET_RPS" default:"200"`

	// ── Phase 9 §9.17.6 — In-process L0 LRU cache ──────────────────────────
	// APIL0CacheMaxEntries: max number of entries in the per-pod L0 LRU cache.
	// Default 10000.
	APIL0CacheMaxEntries int `env:"NEGELIR_API_L0_CACHE_MAX_ENTRIES" default:"10000"`
	// APIL0CacheMaxBytes: soft byte-usage cap for the L0 cache (64 MiB default).
	APIL0CacheMaxBytes int `env:"NEGELIR_API_L0_CACHE_MAX_BYTES" default:"67108864"`
	// APIL0MaxTTLS: per-entry TTL cap in seconds; effective TTL = min(L1 TTL, this).
	// Default 5.
	APIL0MaxTTLS int `env:"NEGELIR_API_L0_MAX_TTL_S" default:"5"`
	// APINegativeCacheS: TTL in seconds for 404/410 negative-cache entries.
	// Default 10.
	APINegativeCacheS int `env:"NEGELIR_API_NEGATIVE_CACHE_S" default:"10"`
	// APIL0RefreshMaxWaitMs: max milliseconds a stampede-waiting goroutine blocks
	// before falling through to a direct fetch. Default 200.
	APIL0RefreshMaxWaitMs int `env:"NEGELIR_API_L0_REFRESH_MAX_WAIT_MS" default:"200"`
	// APIL0InvalidationLagMaxMs: SLO target for keyspace-notification eviction lag
	// in milliseconds. Violations emit a sec.alert.v1 event. Default 500.
	APIL0InvalidationLagMaxMs int `env:"NEGELIR_API_L0_INVALIDATION_LAG_MAX_MS" default:"500"`

	// Phase 9 §9.17.7 — Audit pipeline performance.
	// APIAuditBatchMax: max rows per Redis pipeline flush. Default 64.
	APIAuditBatchMax int `env:"NEGELIR_API_AUDIT_BATCH_MAX" default:"64"`
	// APIAuditBatchMaxMs: max milliseconds to accumulate before flush. Default 10.
	APIAuditBatchMaxMs int `env:"NEGELIR_API_AUDIT_BATCH_MAX_MS" default:"10"`
	// APIAuditChanCap: bounded channel capacity for the audit shipper. Default 4096.
	APIAuditChanCap int `env:"NEGELIR_API_AUDIT_CHAN_CAP" default:"4096"`
	// APIAuditSamplePctUnderPressure: 2xx sample percentage when channel >80% full
	// for >5s. 4xx/5xx and sec-relevant events always bypass sampling. Default 10.
	APIAuditSamplePctUnderPressure int `env:"NEGELIR_API_AUDIT_SAMPLE_PCT_UNDER_PRESSURE" default:"10"`

	// Phase 9 §9.17.8 — TCP_USER_TIMEOUT (Linux only).
	// Sets the TCP_USER_TIMEOUT socket option on every accepted connection.
	// 0 = kernel default (no user-space timeout). Default 20000 ms (20 s).
	APITCPUserTimeoutMs int `env:"NEGELIR_API_TCP_USER_TIMEOUT_MS" default:"20000"`

	// Phase 9 §9.17.9 — Backpressure feedback loops.
	// APIAdaptiveErrorRateThreshold: fraction of requests (0–1) that must be
	// 5xx over the 30 s sliding window before the adaptive controller engages
	// shedding. Default 0.02 (2%).
	APIAdaptiveErrorRateThreshold float64 `env:"NEGELIR_API_ADAPTIVE_ERROR_RATE_THRESHOLD" default:"0.02"`
	// APIAdaptiveShedFactor: multiplier applied to all subject-key bucket
	// refill rates when adaptive shedding is engaged. Default 0.5 (halves
	// the refill rate). Must be in (0, 1]; Validate() rejects 0 or > 1.
	APIAdaptiveShedFactor float64 `env:"NEGELIR_API_ADAPTIVE_SHED_FACTOR" default:"0.5"`
	// APIAdaptiveShedDurationS: seconds to hold the reduced refill rate after
	// the error rate first exceeds APIAdaptiveErrorRateThreshold. Default 60.
	APIAdaptiveShedDurationS int `env:"NEGELIR_API_ADAPTIVE_SHED_DURATION_S" default:"60"`
	// APIPriorityTierFloor: tier_id floor for inflight-pressure shedding.
	// Requests whose tier_id < this value are immediately returned 503 when
	// the inflight ratio (api_inflight_rpcs / api_max_concurrent_requests)
	// exceeds 0.85 for > 5 s. Default 0 (dormant — all tier_ids are ≥ 0, so
	// no request is shed until §20 raises this value above 0).
	APIPriorityTierFloor int `env:"NEGELIR_API_PRIORITY_TIER_FLOOR" default:"0"`

	// Phase 9 §9.17.10 — Observability for performance.

	// APIPprofEnabledDev: enables the /debug/pprof/* handlers on the internal
	// metrics port (:9091) in dev environments. Default true. Operators may
	// also enable pprof on a live pod for 1 h via Redis key api:pprof:<pod>
	// (set by `make api.pprof-enable POD=...`). The public listener NEVER
	// exposes pprof regardless of this flag.
	APIPprofEnabledDev bool `env:"NEGELIR_API_PPROF_ENABLED_DEV" default:"true"`

	// APIPprofEnabledProd: master switch for pprof on the metrics port in
	// production environments. Default false. Set true only when an operator
	// explicitly opts in; prefer the short-lived Redis-key path instead.
	APIPprofEnabledProd bool `env:"NEGELIR_API_PPROF_ENABLED_PROD" default:"false"`

	// APIAllocSampleRate: fraction of requests for which the allocation-delta
	// middleware runs runtime.ReadMemStats before and after ServeHTTP. Default
	// 0.001 (1 in 1000). Must be in [0, 1]; Validate() rejects values outside
	// this range. Set 0 to disable allocation tracking entirely.
	APIAllocSampleRate float64 `env:"NEGELIR_API_ALLOC_SAMPLE_RATE" default:"0.001"`

	// APIPprofDir: base directory for continuous CPU profile files.
	// Files are written to APIPprofDir/<hostname>/<utc>.pprof.gz.
	// Default: data/api/profiles
	APIPprofDir string `env:"NEGELIR_API_PPROF_DIR" default:"data/api/profiles"`
}

// Duration helpers — keep callers free of `time.Duration(x) * time.Second`.

func secondsToDuration(s int) time.Duration { return time.Duration(s) * time.Second }

func (c *Config) DBConnectTimeout() time.Duration    { return secondsToDuration(c.DBConnectTimeoutSec) }
func (c *Config) DBPingTimeout() time.Duration       { return secondsToDuration(c.DBPingTimeoutSec) }
func (c *Config) DBRetryDelay() time.Duration        { return secondsToDuration(c.DBRetryDelaySec) }
func (c *Config) RedisRetryDelay() time.Duration     { return secondsToDuration(c.RedisRetryDelaySec) }
func (c *Config) HTTPReadTimeout() time.Duration     { return secondsToDuration(c.HTTPReadTimeoutSec) }
func (c *Config) HTTPWriteTimeout() time.Duration    { return secondsToDuration(c.HTTPWriteTimeoutSec) }
func (c *Config) HTTPHandlerTimeout() time.Duration  { return secondsToDuration(c.HTTPHandlerTimeoutSec) }
func (c *Config) HTTPShutdownTimeout() time.Duration { return secondsToDuration(c.HTTPShutdownTimeoutSec) }
func (c *Config) MatchesCacheTTL() time.Duration          { return secondsToDuration(c.CacheMatchesTTLSec) }
func (c *Config) TeamsCacheTTL() time.Duration            { return secondsToDuration(c.CacheTeamsTTLSec) }
func (c *Config) AccessTTL() time.Duration                { return secondsToDuration(c.APIAccessTTLSec) }
func (c *Config) RefreshTTL() time.Duration               { return secondsToDuration(c.APIRefreshTTLSec) }
func (c *Config) RefreshReplayGrace() time.Duration       { return secondsToDuration(c.APIRefreshReplayGraceSec) }
func (c *Config) JWTClockSkew() time.Duration              { return secondsToDuration(c.APIJWTClockSkewS) }
func (c *Config) RevocationSetMax() int64                 { return int64(c.APIRevocationSetMax) }
func (c *Config) ReplyReaperInterval() time.Duration      { return secondsToDuration(c.APIReplyReaperSec) }
func (c *Config) IdempotencyTTL() time.Duration            { return secondsToDuration(c.APIIdempotencyTTLS) }
func (c *Config) IdempotencyInflightWait() time.Duration   { return time.Duration(c.APIIdempotencyInflightWaitMs) * time.Millisecond }
func (c *Config) TierEnforcementEnabled() bool             { return c.APITierEnforcementEnabled }
func (c *Config) ResponseWriteTimeout() time.Duration      { return time.Duration(c.APIResponseWriteTimeoutMs) * time.Millisecond }

// §9.17.1 duration helpers.
func (c *Config) ReadHeaderTimeout() time.Duration { return time.Duration(c.APIReadHeaderTimeoutMs) * time.Millisecond }
func (c *Config) ReadTimeout() time.Duration       { return time.Duration(c.APIReadTimeoutMs) * time.Millisecond }
func (c *Config) WriteTimeout() time.Duration      { return time.Duration(c.APIWriteTimeoutMs) * time.Millisecond }
func (c *Config) IdleTimeout() time.Duration       { return time.Duration(c.APIIdleTimeoutMs) * time.Millisecond }
func (c *Config) ShutdownGrace() time.Duration     { return secondsToDuration(c.APIShutdownGraceS) }

// §9.17.8 — TCP_USER_TIMEOUT duration helper.
func (c *Config) TCPUserTimeout() time.Duration { return time.Duration(c.APITCPUserTimeoutMs) * time.Millisecond }

// §9.17.9 — Adaptive shedding helpers.
func (c *Config) AdaptiveErrorRateThreshold() float64 { return c.APIAdaptiveErrorRateThreshold }
func (c *Config) AdaptiveShedFactor() float64         { return c.APIAdaptiveShedFactor }
func (c *Config) AdaptiveShedDuration() time.Duration { return secondsToDuration(c.APIAdaptiveShedDurationS) }
func (c *Config) PriorityTierFloor() int64            { return int64(c.APIPriorityTierFloor) }

// §9.17.10 — Observability for performance helpers.

// PprofEnabled reports whether pprof should be served on the metrics port.
// It returns true when APIPprofEnabledDev is set (non-prod build) or when
// APIPprofEnabledProd is set. The short-lived Redis-key path is checked at
// runtime by the metrics server handler, not here.
func (c *Config) PprofEnabled() bool {
	return c.APIPprofEnabledDev || c.APIPprofEnabledProd
}

// AllocSampleRate returns the fraction of requests sampled for allocation
// tracking (0 = disabled, 1 = every request).
func (c *Config) AllocSampleRate() float64 { return c.APIAllocSampleRate }

// §9.17.6 — In-process L0 LRU cache duration helpers.
func (c *Config) L0MaxTTL() time.Duration             { return secondsToDuration(c.APIL0MaxTTLS) }
func (c *Config) NegativeCacheTTL() time.Duration     { return secondsToDuration(c.APINegativeCacheS) }
func (c *Config) L0RefreshMaxWait() time.Duration     { return time.Duration(c.APIL0RefreshMaxWaitMs) * time.Millisecond }
func (c *Config) L0InvalidationLagMax() time.Duration { return time.Duration(c.APIL0InvalidationLagMaxMs) * time.Millisecond }

// §9.17.7 — Audit pipeline duration helper.
func (c *Config) AuditBatchMaxDuration() time.Duration { return time.Duration(c.APIAuditBatchMaxMs) * time.Millisecond }

// EffectiveDatabaseURL returns DATABASE_URL when set, else builds one from
// the POSTGRES_* fields. Mirrors defaultDatabaseURL() in the legacy main.go.
func (c *Config) EffectiveDatabaseURL() string {
	if c.DatabaseURL != "" {
		return c.DatabaseURL
	}
	return fmt.Sprintf(
		"postgres://%s:%s@%s:%s/%s?sslmode=disable",
		c.PostgresUser, c.PostgresPassword,
		c.PostgresHost, c.PostgresPort, c.PostgresDB,
	)
}

// EffectiveRedisURL returns REDIS_URL when set, else `host:port`.
func (c *Config) EffectiveRedisURL() string {
	if c.RedisURL != "" {
		return c.RedisURL
	}
	return fmt.Sprintf("%s:%s", c.RedisHost, c.RedisPort)
}

// Load reads every Config field from os.Getenv, applying the `default` tag
// when the env var is empty. Returns the loaded config and the result of
// Validate() and ValidateBoot(); callers should fail fast on a non-nil error.
func Load() (*Config, error) {
	cfg := &Config{}
	if err := bindEnv(cfg); err != nil {
		return nil, fmt.Errorf("config.Load: %w", err)
	}
	if err := cfg.Validate(); err != nil {
		return nil, err
	}
	return cfg, ValidateBoot(cfg)
}

// Validate returns the first detected misconfiguration error, or nil.
func (c *Config) Validate() error {
	if err := validatePort(c.Port, "SERVER_PORT"); err != nil {
		return err
	}
	if err := validatePort(c.PostgresPort, "POSTGRES_PORT"); err != nil {
		return err
	}
	if err := validatePort(c.RedisPort, "REDIS_PORT"); err != nil {
		return err
	}
	if c.DBMaxConns <= 0 {
		return fmt.Errorf("DB_MAX_CONNS=%d must be a positive integer", c.DBMaxConns)
	}
	for name, sec := range map[string]int{
		"DB_CONNECT_TIMEOUT_SEC":    c.DBConnectTimeoutSec,
		"DB_PING_TIMEOUT_SEC":       c.DBPingTimeoutSec,
		"DB_RETRY_DELAY_SEC":        c.DBRetryDelaySec,
		"REDIS_RETRY_DELAY_SEC":     c.RedisRetryDelaySec,
		"HTTP_READ_TIMEOUT_SEC":     c.HTTPReadTimeoutSec,
		"HTTP_WRITE_TIMEOUT_SEC":    c.HTTPWriteTimeoutSec,
		"HTTP_HANDLER_TIMEOUT_SEC":  c.HTTPHandlerTimeoutSec,
		"HTTP_SHUTDOWN_TIMEOUT_SEC": c.HTTPShutdownTimeoutSec,
		"CACHE_MATCHES_TTL_SEC":     c.CacheMatchesTTLSec,
		"CACHE_TEAMS_TTL_SEC":       c.CacheTeamsTTLSec,
		"SWARM_HEARTBEAT_SEC":       c.SwarmHeartbeatSec,
	} {
		if sec <= 0 {
			return fmt.Errorf("%s=%d must be a positive integer (seconds)", name, sec)
		}
	}
	// §9.3 — transit jitter budget must be non-negative.
	if c.APITransitJitterMs < 0 {
		return fmt.Errorf("NEGELIR_API_TRANSIT_JITTER_MS=%d must be ≥ 0", c.APITransitJitterMs)
	}
	// §9.0 §3.3 — API request timeout must cover the full prediction path including
	// transit jitter: APIRequestTimeoutMs ≥ consensus_window_ms +
	// proofreader_quorum_window_ms + api_consensus_overhead_ms + api_transit_jitter_ms.
	minTimeoutMs := c.ConsensusWindowMs + c.ProofreaderQuorumWindowMs + c.APIConsensusOverheadMs + c.APITransitJitterMs
	if c.APIRequestTimeoutMs < minTimeoutMs {
		return fmt.Errorf(
			"NEGELIR_API_REQUEST_TIMEOUT_MS=%d must be ≥ consensus_window_ms(%d) + proofreader_quorum_window_ms(%d) + api_consensus_overhead_ms(%d) + api_transit_jitter_ms(%d) = %d",
			c.APIRequestTimeoutMs,
			c.ConsensusWindowMs, c.ProofreaderQuorumWindowMs, c.APIConsensusOverheadMs, c.APITransitJitterMs,
			minTimeoutMs,
		)
	}
	// §9.1 — only "iso8601_utc" is a legal time-format value.
	if c.APITimeFormat != "iso8601_utc" {
		return fmt.Errorf(
			"NEGELIR_API_TIME_FORMAT=%q: only \"iso8601_utc\" is accepted (future values require an explicit feature flag)",
			c.APITimeFormat,
		)
	}
	// §9.1 — cursor TTL must be positive.
	if c.APICursorTTLSec <= 0 {
		return fmt.Errorf("NEGELIR_API_CURSOR_TTL_S=%d must be a positive integer (seconds)", c.APICursorTTLSec)
	}
	// §9.1 — body-size caps must be positive; sub-caps must not exceed the global cap.
	if c.APIRequestMaxBytes <= 0 {
		return fmt.Errorf("NEGELIR_API_REQUEST_MAX_BYTES=%d must be a positive integer (bytes)", c.APIRequestMaxBytes)
	}
	if c.QAInputMaxBytes <= 0 {
		return fmt.Errorf("NEGELIR_QA_INPUT_MAX_BYTES=%d must be a positive integer (bytes)", c.QAInputMaxBytes)
	}
	if c.AuthLoginMaxBytes <= 0 {
		return fmt.Errorf("NEGELIR_AUTH_LOGIN_MAX_BYTES=%d must be a positive integer (bytes)", c.AuthLoginMaxBytes)
	}
	if c.QAInputMaxBytes > c.APIRequestMaxBytes {
		return fmt.Errorf(
			"NEGELIR_QA_INPUT_MAX_BYTES=%d must not exceed NEGELIR_API_REQUEST_MAX_BYTES=%d",
			c.QAInputMaxBytes, c.APIRequestMaxBytes,
		)
	}
	if c.AuthLoginMaxBytes > c.APIRequestMaxBytes {
		return fmt.Errorf(
			"NEGELIR_AUTH_LOGIN_MAX_BYTES=%d must not exceed NEGELIR_API_REQUEST_MAX_BYTES=%d",
			c.AuthLoginMaxBytes, c.APIRequestMaxBytes,
		)
	}
	// §9.2 — bcrypt cost must be in [10, 14].
	if c.APIBcryptCost < 10 || c.APIBcryptCost > 14 {
		return fmt.Errorf(
			"NEGELIR_API_BCRYPT_COST=%d out of range [10, 14]",
			c.APIBcryptCost,
		)
	}
	// §9.2 — JWT key-store knobs.
	if c.APIJWTKeyDir == "" {
		return fmt.Errorf("NEGELIR_API_JWT_KEY_DIR must not be empty")
	}
	if c.APIJWTKeyPollSec <= 0 {
		return fmt.Errorf("NEGELIR_API_JWT_KEY_POLL_S=%d must be a positive integer (seconds)", c.APIJWTKeyPollSec)
	}
	if c.APIJWTRetiredGraceSec <= 0 {
		return fmt.Errorf("NEGELIR_API_JWT_RETIRED_GRACE_S=%d must be a positive integer (seconds)", c.APIJWTRetiredGraceSec)
	}
	// §9.14 — clock-skew tolerance: non-negative and capped at 300 s.
	if c.APIJWTClockSkewS < 0 {
		return fmt.Errorf("NEGELIR_API_JWT_CLOCK_SKEW_S=%d must be ≥ 0", c.APIJWTClockSkewS)
	}
	if c.APIJWTClockSkewS > 300 {
		return fmt.Errorf(
			"NEGELIR_API_JWT_CLOCK_SKEW_S=%d exceeds the 300-second safety cap (OWASP: keep ≤ 60 s)",
			c.APIJWTClockSkewS,
		)
	}
	// §9.2 — token shape knobs.
	if c.APIAccessTTLSec <= 0 {
		return fmt.Errorf("NEGELIR_API_ACCESS_TTL_S=%d must be a positive integer (seconds)", c.APIAccessTTLSec)
	}
	if c.APIRefreshTTLSec <= 0 {
		return fmt.Errorf("NEGELIR_API_REFRESH_TTL_S=%d must be a positive integer (seconds)", c.APIRefreshTTLSec)
	}
	if c.APIRefreshReplayGraceSec <= 0 {
		return fmt.Errorf("NEGELIR_API_REFRESH_REPLAY_GRACE_S=%d must be a positive integer (seconds)", c.APIRefreshReplayGraceSec)
	}
	if c.APIRevocationSetMax <= 0 {
		return fmt.Errorf("NEGELIR_API_REVOCATION_SET_MAX=%d must be a positive integer", c.APIRevocationSetMax)
	}
	// §9.2 — self-registration subnet cap must be positive.
	if c.APIRegisterCapPerSubnetPerH <= 0 {
		return fmt.Errorf("NEGELIR_API_REGISTER_CAP_PER_SUBNET_PER_H=%d must be a positive integer", c.APIRegisterCapPerSubnetPerH)
	}
	// §9.2 — mTLS: when enabled, TLS dir must be non-empty.
	if c.APIMTLSEnabled && c.APITLSDir == "" {
		return fmt.Errorf("NEGELIR_API_TLS_DIR must not be empty when NEGELIR_API_MTLS_ENABLED=true")
	}
	// §9.3 — idempotency cache TTL and inflight wait must be positive.
	if c.APIIdempotencyTTLS <= 0 {
		return fmt.Errorf("NEGELIR_API_IDEMPOTENCY_TTL_S=%d must be a positive integer (seconds)", c.APIIdempotencyTTLS)
	}
	if c.APIIdempotencyInflightWaitMs <= 0 {
		return fmt.Errorf("NEGELIR_API_IDEMPOTENCY_INFLIGHT_WAIT_MS=%d must be a positive integer (milliseconds)", c.APIIdempotencyInflightWaitMs)
	}
	// §9.3 — reply reaper interval must be positive.
	if c.APIReplyReaperSec <= 0 {
		return fmt.Errorf("NEGELIR_API_REPLY_REAPER_S=%d must be a positive integer (seconds)", c.APIReplyReaperSec)
	}
	// §9.7 — burst budget must be positive.
	if c.APIBurstCapacity <= 0 {
		return fmt.Errorf("NEGELIR_API_BURST_CAPACITY=%d must be a positive integer", c.APIBurstCapacity)
	}
	if c.APIBurstRefillPerS <= 0 {
		return fmt.Errorf("NEGELIR_API_BURST_REFILL_PER_S=%.4g must be a positive float", c.APIBurstRefillPerS)
	}
	// §9.9 — backpressure threshold must be positive.
	if c.APIPredictRequestBacklogHigh <= 0 {
		return fmt.Errorf("NEGELIR_API_PREDICT_REQUEST_BACKLOG_HIGH=%d must be a positive integer", c.APIPredictRequestBacklogHigh)
	}
	// §9.9 — concurrency semaphore must be positive.
	if c.APIMaxConcurrentRequests <= 0 {
		return fmt.Errorf("NEGELIR_API_MAX_CONCURRENT_REQUESTS=%d must be a positive integer", c.APIMaxConcurrentRequests)
	}
	// §9.9 — response write timeout must be positive.
	if c.APIResponseWriteTimeoutMs <= 0 {
		return fmt.Errorf("NEGELIR_API_RESPONSE_WRITE_TIMEOUT_MS=%d must be a positive integer (milliseconds)", c.APIResponseWriteTimeoutMs)
	}
	// §9.3 — SWR cache knobs must be positive; stale_after must be less than max_age.
	if c.APICacheStaleAfterS <= 0 {
		return fmt.Errorf("NEGELIR_API_CACHE_STALE_AFTER_S=%d must be a positive integer (seconds)", c.APICacheStaleAfterS)
	}
	if c.APICacheMaxAgeS <= 0 {
		return fmt.Errorf("NEGELIR_API_CACHE_MAX_AGE_S=%d must be a positive integer (seconds)", c.APICacheMaxAgeS)
	}
	if c.APICacheStaleAfterS >= c.APICacheMaxAgeS {
		return fmt.Errorf(
			"NEGELIR_API_CACHE_STALE_AFTER_S=%d must be less than NEGELIR_API_CACHE_MAX_AGE_S=%d",
			c.APICacheStaleAfterS, c.APICacheMaxAgeS,
		)
	}
	if c.APISWRInflightMax <= 0 {
		return fmt.Errorf("NEGELIR_API_SWR_INFLIGHT_MAX=%d must be a positive integer", c.APISWRInflightMax)
	}
	// §9.15 Phase 11 compute boundary — only "cpu_only" is valid in v1.
	if c.ComputeClass != "cpu_only" {
		return fmt.Errorf(
			"NEGELIR_COMPUTE_CLASS=%q: only \"cpu_only\" is accepted in v1 (Phase 11 will extend this)",
			c.ComputeClass,
		)
	}
	// §9.8 — metrics port must be valid and must not collide with the API port.
	if err := validatePort(c.TelemetryMetricsPort, "NEGELIR_TELEMETRY_METRICS_PORT"); err != nil {
		return err
	}
	if c.TelemetryMetricsPort == c.Port {
		return fmt.Errorf(
			"NEGELIR_TELEMETRY_METRICS_PORT=%s must not be the same as SERVER_PORT=%s",
			c.TelemetryMetricsPort, c.Port,
		)
	}
	// §9.8 — cardinality cap must be positive.
	if c.TelemetryMaxSeries <= 0 {
		return fmt.Errorf("NEGELIR_TELEMETRY_MAX_SERIES=%d must be a positive integer", c.TelemetryMaxSeries)
	}
	// §9.8 — log sampling percentage must be in [0, 100].
	if c.APILogSamplePct < 0 || c.APILogSamplePct > 100 {
		return fmt.Errorf("NEGELIR_API_LOG_SAMPLE_PCT=%d must be in [0, 100]", c.APILogSamplePct)
	}
	// DATABASE_URL override, when set, must parse and use a postgres scheme.
	if c.DatabaseURL != "" {
		u, err := url.Parse(c.DatabaseURL)
		if err != nil {
			return fmt.Errorf("DATABASE_URL=%q is not parseable: %w", c.DatabaseURL, err)
		}
		if u.Scheme != "postgres" && u.Scheme != "postgresql" {
			return fmt.Errorf("DATABASE_URL=%q must use postgres:// scheme (got %q)", c.DatabaseURL, u.Scheme)
		}
	}
	// §9.8 — SLO burn-rate alert knobs.
	if c.APISLOBurnWindowS <= 0 {
		return fmt.Errorf("NEGELIR_API_SLO_BURN_WINDOW_S=%d must be a positive integer (seconds)", c.APISLOBurnWindowS)
	}
	if c.APISLOBurnThreshold <= 0 {
		return fmt.Errorf("NEGELIR_API_SLO_BURN_THRESHOLD=%.4g must be a positive float", c.APISLOBurnThreshold)
	}
	// §9.11 — deprecation window must be at least 1 day.
	if c.APIDeprecationWindowDays < 1 {
		return fmt.Errorf("NEGELIR_API_DEPRECATION_WINDOW_DAYS=%d must be ≥ 1", c.APIDeprecationWindowDays)
	}
	// §9.11 — schema version must be a positive integer.
	if c.APISchemaVersion < 1 {
		return fmt.Errorf("NEGELIR_API_SCHEMA_VERSION=%d must be ≥ 1", c.APISchemaVersion)
	}
	// §9.17.1 — Go runtime tuning validators.
	if c.APIGoMemLimitMiB < 0 {
		return fmt.Errorf("NEGELIR_API_GO_MEM_LIMIT_MIB=%d must be ≥ 0 (0 = derive from cgroup)", c.APIGoMemLimitMiB)
	}
	if c.APIGoGCPercent < 1 || c.APIGoGCPercent > 1000 {
		return fmt.Errorf("NEGELIR_API_GO_GC_PERCENT=%d must be in [1, 1000]", c.APIGoGCPercent)
	}
	if c.APIReadHeaderTimeoutMs <= 0 {
		return fmt.Errorf("NEGELIR_API_READ_HEADER_TIMEOUT_MS=%d must be a positive integer (ms)", c.APIReadHeaderTimeoutMs)
	}
	if c.APIReadTimeoutMs <= 0 {
		return fmt.Errorf("NEGELIR_API_READ_TIMEOUT_MS=%d must be a positive integer (ms)", c.APIReadTimeoutMs)
	}
	if c.APIWriteTimeoutMs <= 0 {
		return fmt.Errorf("NEGELIR_API_WRITE_TIMEOUT_MS=%d must be a positive integer (ms)", c.APIWriteTimeoutMs)
	}
	// WriteTimeout must exceed request_timeout_ms + response_write_timeout_ms
	// to ensure the handler always completes before the TCP write deadline fires.
	minWriteMs := c.APIRequestTimeoutMs + c.APIResponseWriteTimeoutMs
	if c.APIWriteTimeoutMs <= minWriteMs {
		return fmt.Errorf(
			"NEGELIR_API_WRITE_TIMEOUT_MS=%d must exceed api_request_timeout_ms(%d)+api_response_write_timeout_ms(%d)=%d",
			c.APIWriteTimeoutMs, c.APIRequestTimeoutMs, c.APIResponseWriteTimeoutMs, minWriteMs,
		)
	}
	if c.APIIdleTimeoutMs <= 0 {
		return fmt.Errorf("NEGELIR_API_IDLE_TIMEOUT_MS=%d must be a positive integer (ms)", c.APIIdleTimeoutMs)
	}
	if c.APIShutdownGraceS <= 0 {
		return fmt.Errorf("NEGELIR_API_SHUTDOWN_GRACE_S=%d must be a positive integer (seconds)", c.APIShutdownGraceS)
	}
	// §9.17.3 — connection pool sizing validators.
	if c.APIPGPoolMaxConns <= 0 {
		return fmt.Errorf("NEGELIR_API_PG_POOL_MAX_CONNS=%d must be a positive integer", c.APIPGPoolMaxConns)
	}
	if c.APIPGReplicaURL != "" {
		if c.APIPGReplicaLagCheckS <= 0 {
			return fmt.Errorf("NEGELIR_API_PG_REPLICA_LAG_CHECK_S=%d must be a positive integer (seconds)", c.APIPGReplicaLagCheckS)
		}
		if c.APIPGReplicaLagMaxMs <= 0 {
			return fmt.Errorf("NEGELIR_API_PG_REPLICA_LAG_MAX_MS=%d must be a positive integer (milliseconds)", c.APIPGReplicaLagMaxMs)
		}
		u, err := url.Parse(c.APIPGReplicaURL)
		if err != nil {
			return fmt.Errorf("NEGELIR_API_PG_REPLICA_URL=%q is not parseable: %w", c.APIPGReplicaURL, err)
		}
		if u.Scheme != "postgres" && u.Scheme != "postgresql" {
			return fmt.Errorf("NEGELIR_API_PG_REPLICA_URL=%q must use postgres:// scheme (got %q)", c.APIPGReplicaURL, u.Scheme)
		}
	}
	if c.APIRedisCachePoolSize <= 0 {
		return fmt.Errorf("NEGELIR_API_REDIS_CACHE_POOL_SIZE=%d must be a positive integer", c.APIRedisCachePoolSize)
	}
	if c.APIRedisBusPoolSize <= 0 {
		return fmt.Errorf("NEGELIR_API_REDIS_BUS_POOL_SIZE=%d must be a positive integer", c.APIRedisBusPoolSize)
	}
	// §9.17.6 — In-process L0 LRU cache.
	if c.APIL0CacheMaxEntries <= 0 {
		return fmt.Errorf("NEGELIR_API_L0_CACHE_MAX_ENTRIES=%d must be a positive integer", c.APIL0CacheMaxEntries)
	}
	if c.APIL0CacheMaxBytes <= 0 {
		return fmt.Errorf("NEGELIR_API_L0_CACHE_MAX_BYTES=%d must be a positive integer (bytes)", c.APIL0CacheMaxBytes)
	}
	if c.APIL0MaxTTLS <= 0 {
		return fmt.Errorf("NEGELIR_API_L0_MAX_TTL_S=%d must be a positive integer (seconds)", c.APIL0MaxTTLS)
	}
	if c.APINegativeCacheS <= 0 {
		return fmt.Errorf("NEGELIR_API_NEGATIVE_CACHE_S=%d must be a positive integer (seconds)", c.APINegativeCacheS)
	}
	if c.APIL0RefreshMaxWaitMs <= 0 {
		return fmt.Errorf("NEGELIR_API_L0_REFRESH_MAX_WAIT_MS=%d must be a positive integer (ms)", c.APIL0RefreshMaxWaitMs)
	}
	if c.APIL0InvalidationLagMaxMs <= 0 {
		return fmt.Errorf("NEGELIR_API_L0_INVALIDATION_LAG_MAX_MS=%d must be a positive integer (ms)", c.APIL0InvalidationLagMaxMs)
	}
	return nil
}

func validatePort(raw string, name string) error {
	if raw == "" {
		return fmt.Errorf("%s is empty", name)
	}
	n, err := strconv.Atoi(raw)
	if err != nil {
		return fmt.Errorf("%s=%q is not numeric: %w", name, raw, err)
	}
	if n < 1 || n > 65535 {
		return fmt.Errorf("%s=%d outside [1, 65535]", name, n)
	}
	return nil
}

// ── Reflection-free env binder ────────────────────────────────────────────
//
// Kept stdlib-only on purpose (no caarlos0/env dep) — easier to audit and
// the field set is small enough that explicit registration is cheaper than
// pulling in a transitive dep tree.

type fieldSpec struct {
	name      string // env key
	dflt      string // default value
	stringDst *string
	intDst    *int
	floatDst  *float64
	boolDst   *bool
}

func (c *Config) specs() []fieldSpec {
	return []fieldSpec{
		{name: "DATABASE_URL", dflt: "", stringDst: &c.DatabaseURL},
		{name: "REDIS_URL", dflt: "", stringDst: &c.RedisURL},
		{name: "POSTGRES_HOST", dflt: "postgres", stringDst: &c.PostgresHost},
		{name: "POSTGRES_PORT", dflt: "5432", stringDst: &c.PostgresPort},
		{name: "POSTGRES_DB", dflt: "negelir", stringDst: &c.PostgresDB},
		{name: "POSTGRES_USER", dflt: "negelir", stringDst: &c.PostgresUser},
		{name: "POSTGRES_PASSWORD", dflt: "", stringDst: &c.PostgresPassword},
		{name: "REDIS_HOST", dflt: "redis", stringDst: &c.RedisHost},
		{name: "REDIS_PORT", dflt: "6379", stringDst: &c.RedisPort},
		{name: "SERVER_PORT", dflt: "8080", stringDst: &c.Port},
		{name: "DB_MAX_CONNS", dflt: "10", intDst: &c.DBMaxConns},
		{name: "DB_CONNECT_TIMEOUT_SEC", dflt: "5", intDst: &c.DBConnectTimeoutSec},
		{name: "DB_PING_TIMEOUT_SEC", dflt: "5", intDst: &c.DBPingTimeoutSec},
		{name: "DB_RETRY_DELAY_SEC", dflt: "3", intDst: &c.DBRetryDelaySec},
		{name: "REDIS_RETRY_DELAY_SEC", dflt: "2", intDst: &c.RedisRetryDelaySec},
		{name: "HTTP_READ_TIMEOUT_SEC", dflt: "10", intDst: &c.HTTPReadTimeoutSec},
		{name: "HTTP_WRITE_TIMEOUT_SEC", dflt: "30", intDst: &c.HTTPWriteTimeoutSec},
		{name: "HTTP_HANDLER_TIMEOUT_SEC", dflt: "25", intDst: &c.HTTPHandlerTimeoutSec},
		{name: "HTTP_SHUTDOWN_TIMEOUT_SEC", dflt: "5", intDst: &c.HTTPShutdownTimeoutSec},
		{name: "CACHE_MATCHES_TTL_SEC", dflt: "300", intDst: &c.CacheMatchesTTLSec},
		{name: "CACHE_TEAMS_TTL_SEC", dflt: "600", intDst: &c.CacheTeamsTTLSec},
		{name: "SWARM_HEARTBEAT_SEC", dflt: "5", intDst: &c.SwarmHeartbeatSec},

		// Phase 7 sec.* shared knobs.
		{name: "NEGELIR_SEC_INPUT_MAX_LEN", dflt: "8192", intDst: &c.SecInputMaxLen},
		{name: "NEGELIR_SEC_INPUT_GATEWAY_MAX_LATENCY_MS", dflt: "10", intDst: &c.SecInputGatewayMaxLatencyMs},
		{name: "NEGELIR_SEC_INPUT_PATTERN_RELOAD_S", dflt: "30", intDst: &c.SecInputPatternReloadSec},
		{name: "NEGELIR_SEC_QUARANTINE_PAYLOAD_MAX_BYTES", dflt: "65536", intDst: &c.SecQuarantinePayloadMaxBytes},
		{name: "NEGELIR_SEC_RATE_PRE_AUTH_CAPACITY", dflt: "30", intDst: &c.SecRatePreAuthCapacity},
		{name: "NEGELIR_SEC_RATE_PRE_AUTH_REFILL_PER_S", dflt: "0.5", floatDst: &c.SecRatePreAuthRefillPerS},
		{name: "NEGELIR_SEC_RATE_POST_AUTH_CAPACITY", dflt: "600", intDst: &c.SecRatePostAuthCapacity},
		{name: "NEGELIR_SEC_RATE_POST_AUTH_REFILL_PER_S", dflt: "5.0", floatDst: &c.SecRatePostAuthRefillPerS},
		{name: "NEGELIR_SEC_RATE_BUCKET_IDLE_TTL_S", dflt: "3600", intDst: &c.SecRateBucketIdleTTLSec},
		{name: "NEGELIR_SEC_RATE_IPV4_PREFIX", dflt: "32", intDst: &c.SecRateIPv4Prefix},
		{name: "NEGELIR_SEC_RATE_IPV6_PREFIX", dflt: "64", intDst: &c.SecRateIPv6Prefix},
		{name: "NEGELIR_SEC_RATE_TRUSTED_PROXIES", dflt: "", stringDst: &c.SecRateTrustedProxies},
		{name: "NEGELIR_SEC_RATE_REDIS_TIMEOUT_MS", dflt: "50", intDst: &c.SecRateRedisTimeoutMs},
		{name: "NEGELIR_SEC_RATE_SECONDARY_CAPACITY", dflt: "300", intDst: &c.SecRateSecondaryCapacity},
		{name: "NEGELIR_SEC_RATE_SECONDARY_REFILL_PER_S", dflt: "5.0", floatDst: &c.SecRateSecondaryRefillPerS},
		{name: "NEGELIR_SEC_RATE_DEFAULT_COST", dflt: "1", intDst: &c.SecRateDefaultCost},
		{name: "NEGELIR_SEC_DENYLIST_MAX_ENTRIES", dflt: "250000", intDst: &c.SecDenylistMaxEntries},

		// Phase 9 SLA budget (§9.0 §3.3).
		{name: "NEGELIR_API_REQUEST_TIMEOUT_MS", dflt: "2500", intDst: &c.APIRequestTimeoutMs},
		{name: "NEGELIR_CONSENSUS_WINDOW_MS", dflt: "750", intDst: &c.ConsensusWindowMs},
		{name: "NEGELIR_API_CONSENSUS_OVERHEAD_MS", dflt: "200", intDst: &c.APIConsensusOverheadMs},
		{name: "NEGELIR_PROOFREADER_QUORUM_WINDOW_MS", dflt: "200", intDst: &c.ProofreaderQuorumWindowMs},

		// Phase 9 §9.1 — time discipline.
		{name: "NEGELIR_API_TIME_FORMAT", dflt: "iso8601_utc", stringDst: &c.APITimeFormat},

		// Phase 9 §9.1 — cursor TTL.
		{name: "NEGELIR_API_CURSOR_TTL_S", dflt: "1800", intDst: &c.APICursorTTLSec},

		// Phase 9 §9.1 — body-size cap.
		{name: "NEGELIR_API_REQUEST_MAX_BYTES", dflt: "65536", intDst: &c.APIRequestMaxBytes},
		{name: "NEGELIR_QA_INPUT_MAX_BYTES", dflt: "4096", intDst: &c.QAInputMaxBytes},
		{name: "NEGELIR_AUTH_LOGIN_MAX_BYTES", dflt: "4096", intDst: &c.AuthLoginMaxBytes},

		// Phase 9 §9.2 — bcrypt cost.
		{name: "NEGELIR_API_BCRYPT_COST", dflt: "12", intDst: &c.APIBcryptCost},

		// Phase 9 §9.2 — JWT key-store knobs.
		{name: "NEGELIR_API_JWT_KEY_DIR", dflt: "data/api/jwt_keys", stringDst: &c.APIJWTKeyDir},
		{name: "NEGELIR_API_JWT_KEY_POLL_S", dflt: "10", intDst: &c.APIJWTKeyPollSec},
		{name: "NEGELIR_API_JWT_RETIRED_GRACE_S", dflt: "960", intDst: &c.APIJWTRetiredGraceSec},

		// Phase 9 §9.2 — token shape.
		{name: "NEGELIR_API_ACCESS_TTL_S", dflt: "900", intDst: &c.APIAccessTTLSec},
		{name: "NEGELIR_API_REFRESH_TTL_S", dflt: "2592000", intDst: &c.APIRefreshTTLSec},
		{name: "NEGELIR_API_REFRESH_REPLAY_GRACE_S", dflt: "30", intDst: &c.APIRefreshReplayGraceSec},
		{name: "NEGELIR_API_REVOCATION_SET_MAX", dflt: "10000", intDst: &c.APIRevocationSetMax},

		// Phase 9 §9.2 — self-registration.
		{name: "NEGELIR_API_SELF_REGISTRATION_ENABLED", dflt: "false", boolDst: &c.APISelfRegistrationEnabled},
		{name: "NEGELIR_API_REGISTER_CAP_PER_SUBNET_PER_H", dflt: "20", intDst: &c.APIRegisterCapPerSubnetPerH},

		// Phase 9 §9.2 — mTLS knobs.
		{name: "NEGELIR_API_MTLS_ENABLED", dflt: "false", boolDst: &c.APIMTLSEnabled},
		{name: "NEGELIR_API_TLS_DIR", dflt: "data/api/tls", stringDst: &c.APITLSDir},

		// Phase 9 §9.3 — idempotency-key cache.
		{name: "NEGELIR_API_IDEMPOTENCY_TTL_S", dflt: "86400", intDst: &c.APIIdempotencyTTLS},
		{name: "NEGELIR_API_IDEMPOTENCY_INFLIGHT_WAIT_MS", dflt: "1500", intDst: &c.APIIdempotencyInflightWaitMs},

		// Phase 9 §9.3 — reply_to stream reaper.
		{name: "NEGELIR_API_REPLY_REAPER_S", dflt: "60", intDst: &c.APIReplyReaperSec},

		// Phase 9 §9.3 — transit jitter budget for timeout-budget inequality.
		{name: "NEGELIR_API_TRANSIT_JITTER_MS", dflt: "100", intDst: &c.APITransitJitterMs},

		// Phase 9 §9.7 — burst budget (shared with Python AI layer).
		{name: "NEGELIR_API_BURST_CAPACITY",    dflt: "60",  intDst:   &c.APIBurstCapacity},
		{name: "NEGELIR_API_BURST_REFILL_PER_S", dflt: "2.0", floatDst: &c.APIBurstRefillPerS},

		// Phase 9 §9.7 — tier quota enforcement flag (built-but-dormant).
		{name: "NEGELIR_API_TIER_ENFORCEMENT_ENABLED", dflt: "false", boolDst: &c.APITierEnforcementEnabled},

		// Phase 9 §9.9 — backpressure threshold.
		{name: "NEGELIR_API_PREDICT_REQUEST_BACKLOG_HIGH", dflt: "5000", intDst: &c.APIPredictRequestBacklogHigh},

		// Phase 9 §9.9 — concurrency semaphore.
		{name: "NEGELIR_API_MAX_CONCURRENT_REQUESTS", dflt: "5000", intDst: &c.APIMaxConcurrentRequests},

		// Phase 9 §9.9 — response-side backpressure (slow-client abort).
		{name: "NEGELIR_API_RESPONSE_WRITE_TIMEOUT_MS", dflt: "5000", intDst: &c.APIResponseWriteTimeoutMs},

		// Phase 9 §9.3 — SWR cache knobs.
		{name: "NEGELIR_API_CACHE_STALE_AFTER_S", dflt: "30",  intDst: &c.APICacheStaleAfterS},
		{name: "NEGELIR_API_CACHE_MAX_AGE_S",     dflt: "300", intDst: &c.APICacheMaxAgeS},
		{name: "NEGELIR_API_SWR_INFLIGHT_MAX",    dflt: "64",  intDst: &c.APISWRInflightMax},

		// Phase 9 §9.15 / Phase 11 compute boundary.
		{name: "NEGELIR_COMPUTE_CLASS", dflt: "cpu_only", stringDst: &c.ComputeClass},

		// Phase 9 §9.8 — RED metrics port and cardinality cap.
		{name: "NEGELIR_TELEMETRY_METRICS_PORT", dflt: "9091",  stringDst: &c.TelemetryMetricsPort},
		{name: "NEGELIR_TELEMETRY_MAX_SERIES",   dflt: "10000", intDst:    &c.TelemetryMaxSeries},

		// Phase 9 §9.8 — structured access log sampling.
		{name: "NEGELIR_API_LOG_SAMPLE_PCT", dflt: "10", intDst: &c.APILogSamplePct},

		// Phase 9 §9.8 — OTLP gRPC trace export endpoint (empty = no-op).
		{name: "NEGELIR_TELEMETRY_OTLP_ENDPOINT", dflt: "", stringDst: &c.TelemetryOTLPEndpoint},

		// Phase 9 §9.8 — SLO burn-rate alert knobs.
		{name: "NEGELIR_API_SLO_BURN_WINDOW_S",  dflt: "3600", intDst:   &c.APISLOBurnWindowS},
		{name: "NEGELIR_API_SLO_BURN_THRESHOLD", dflt: "2.0",  floatDst: &c.APISLOBurnThreshold},

		// Phase 9 §9.11 — deprecation window.
		{name: "NEGELIR_API_DEPRECATION_WINDOW_DAYS", dflt: "90", intDst: &c.APIDeprecationWindowDays},

		// Phase 9 §9.11 — schema-version stamp.
		{name: "NEGELIR_API_SCHEMA_VERSION", dflt: "1", intDst: &c.APISchemaVersion},

		// Phase 9 §9.12 — fixture window, allowed markets, trusted proxy list.
		{name: "NEGELIR_API_FIXTURE_WINDOW_MAX_DAYS", dflt: "14",  intDst:    &c.APIFixtureWindowMaxDays},
		{name: "NEGELIR_API_ALLOWED_MARKETS",         dflt: "ms,au_2.5,btts,ah_home,modal_score", stringDst: &c.APIAllowedMarkets},
		{name: "NEGELIR_API_TRUSTED_PROXIES",         dflt: "",   stringDst: &c.APITrustedProxies},

		// Phase 9 §9.17.1 — Go runtime tuning.
		{name: "NEGELIR_API_GO_MEM_LIMIT_MIB",        dflt: "0",     intDst:    &c.APIGoMemLimitMiB},
		{name: "NEGELIR_API_GO_GC_PERCENT",            dflt: "50",    intDst:    &c.APIGoGCPercent},
		{name: "NEGELIR_API_READ_HEADER_TIMEOUT_MS",   dflt: "5000",  intDst:    &c.APIReadHeaderTimeoutMs},
		{name: "NEGELIR_API_READ_TIMEOUT_MS",          dflt: "10000", intDst:    &c.APIReadTimeoutMs},
		{name: "NEGELIR_API_WRITE_TIMEOUT_MS",         dflt: "15000", intDst:    &c.APIWriteTimeoutMs},
		{name: "NEGELIR_API_IDLE_TIMEOUT_MS",          dflt: "60000", intDst:    &c.APIIdleTimeoutMs},
		{name: "NEGELIR_API_SHUTDOWN_GRACE_S",         dflt: "30",    intDst:    &c.APIShutdownGraceS},
		{name: "NEGELIR_API_IN_MESH_PORT",             dflt: "8082",  stringDst: &c.APIInMeshPort},

		// Phase 9 §9.17.3 — Connection pool sizing.
		{name: "NEGELIR_API_PG_POOL_MAX_CONNS",      dflt: "25",  intDst:    &c.APIPGPoolMaxConns},
		{name: "NEGELIR_API_PG_REPLICA_URL",         dflt: "",    stringDst: &c.APIPGReplicaURL},
		{name: "NEGELIR_API_PG_REPLICA_LAG_CHECK_S", dflt: "10",  intDst:    &c.APIPGReplicaLagCheckS},
		{name: "NEGELIR_API_PG_REPLICA_LAG_MAX_MS",  dflt: "500", intDst:    &c.APIPGReplicaLagMaxMs},
		{name: "NEGELIR_API_REDIS_CACHE_POOL_SIZE",  dflt: "50",  intDst:    &c.APIRedisCachePoolSize},
		{name: "NEGELIR_API_REDIS_BUS_POOL_SIZE",    dflt: "20",  intDst:    &c.APIRedisBusPoolSize},

		// Phase 9 §9.17.4 — Resilience: circuit breakers, bulkheads, hedging, retry budgets.
		{name: "NEGELIR_API_BREAKER_FAIL_RATIO",     dflt: "0.5", floatDst: &c.APIBreakerFailRatio},
		{name: "NEGELIR_API_BREAKER_WINDOW_S",       dflt: "10",  intDst:   &c.APIBreakerWindowS},
		{name: "NEGELIR_API_BREAKER_MIN_REQUESTS",   dflt: "20",  intDst:   &c.APIBreakerMinRequests},
		{name: "NEGELIR_API_BREAKER_OPEN_S",         dflt: "15",  intDst:   &c.APIBreakerOpenS},
		{name: "NEGELIR_API_HEDGE_AFTER_MS",         dflt: "200", intDst:   &c.APIHedgeAfterMs},
		{name: "NEGELIR_API_HEDGING_ENABLED",        dflt: "true", boolDst: &c.APIHedgingEnabled},
		{name: "NEGELIR_API_HEDGE_BUDGET_PCT",       dflt: "10",  intDst:   &c.APIHedgeBudgetPct},
		{name: "NEGELIR_API_RETRY_BUDGET_PER_S",     dflt: "10",  floatDst: &c.APIRetryBudgetPerS},
		{name: "NEGELIR_API_RETRY_BUDGET_CAPACITY",  dflt: "50",  intDst:   &c.APIRetryBudgetCapacity},
		{name: "NEGELIR_API_BENCH_TARGET_RPS",        dflt: "200", intDst:   &c.APIBenchTargetRPS},
		// Phase 9 §9.17.6 — In-process L0 LRU cache.
		{name: "NEGELIR_API_L0_CACHE_MAX_ENTRIES",      dflt: "10000",    intDst: &c.APIL0CacheMaxEntries},
		{name: "NEGELIR_API_L0_CACHE_MAX_BYTES",        dflt: "67108864",  intDst: &c.APIL0CacheMaxBytes},
		{name: "NEGELIR_API_L0_MAX_TTL_S",              dflt: "5",         intDst: &c.APIL0MaxTTLS},
		{name: "NEGELIR_API_NEGATIVE_CACHE_S",          dflt: "10",        intDst: &c.APINegativeCacheS},
		{name: "NEGELIR_API_L0_REFRESH_MAX_WAIT_MS",    dflt: "200",       intDst: &c.APIL0RefreshMaxWaitMs},
		{name: "NEGELIR_API_L0_INVALIDATION_LAG_MAX_MS",dflt: "500",       intDst: &c.APIL0InvalidationLagMaxMs},
		// Phase 9 §9.17.7 — Audit pipeline performance.
		{name: "NEGELIR_API_AUDIT_BATCH_MAX",               dflt: "64",   intDst: &c.APIAuditBatchMax},
		{name: "NEGELIR_API_AUDIT_BATCH_MAX_MS",            dflt: "10",   intDst: &c.APIAuditBatchMaxMs},
		{name: "NEGELIR_API_AUDIT_CHAN_CAP",                dflt: "4096", intDst: &c.APIAuditChanCap},
		{name: "NEGELIR_API_AUDIT_SAMPLE_PCT_UNDER_PRESSURE", dflt: "10", intDst: &c.APIAuditSamplePctUnderPressure},
		// Phase 9 §9.17.8 — TCP_USER_TIMEOUT.
		{name: "NEGELIR_API_TCP_USER_TIMEOUT_MS", dflt: "20000", intDst: &c.APITCPUserTimeoutMs},
		// Phase 9 §9.17.9 — Backpressure feedback loops.
		{name: "NEGELIR_API_ADAPTIVE_ERROR_RATE_THRESHOLD", dflt: "0.02", floatDst: &c.APIAdaptiveErrorRateThreshold},
		{name: "NEGELIR_API_ADAPTIVE_SHED_FACTOR",          dflt: "0.5",  floatDst: &c.APIAdaptiveShedFactor},
		{name: "NEGELIR_API_ADAPTIVE_SHED_DURATION_S",      dflt: "60",   intDst:   &c.APIAdaptiveShedDurationS},
		{name: "NEGELIR_API_PRIORITY_TIER_FLOOR",           dflt: "0",    intDst:   &c.APIPriorityTierFloor},
		// Phase 9 §9.17.10 — Observability for performance.
		{name: "NEGELIR_API_PPROF_ENABLED_DEV",  dflt: "true",           boolDst:  &c.APIPprofEnabledDev},
		{name: "NEGELIR_API_PPROF_ENABLED_PROD", dflt: "false",          boolDst:  &c.APIPprofEnabledProd},
		{name: "NEGELIR_API_ALLOC_SAMPLE_RATE",  dflt: "0.001",          floatDst: &c.APIAllocSampleRate},
		{name: "NEGELIR_API_PPROF_DIR",          dflt: "data/api/profiles", stringDst: &c.APIPprofDir},
	}
}

func bindEnv(c *Config) error {
	var errs []string
	for _, s := range c.specs() {
		raw := strings.TrimSpace(os.Getenv(s.name))
		if raw == "" {
			raw = s.dflt
		}
		switch {
		case s.stringDst != nil:
			*s.stringDst = raw
		case s.intDst != nil:
			if raw == "" {
				*s.intDst = 0
				continue
			}
			n, err := strconv.Atoi(raw)
			if err != nil {
				errs = append(errs, fmt.Sprintf("%s=%q: %s", s.name, raw, err))
				continue
			}
			*s.intDst = n
		case s.floatDst != nil:
			if raw == "" {
				*s.floatDst = 0
				continue
			}
			f, err := strconv.ParseFloat(raw, 64)
			if err != nil {
				errs = append(errs, fmt.Sprintf("%s=%q: %s", s.name, raw, err))
				continue
			}
			*s.floatDst = f
		case s.boolDst != nil:
			switch strings.ToLower(strings.TrimSpace(raw)) {
			case "true", "1", "yes":
				*s.boolDst = true
			case "false", "0", "no", "":
				*s.boolDst = false
			default:
				errs = append(errs, fmt.Sprintf("%s=%q: must be true/false/1/0/yes/no", s.name, raw))
			}
		}
	}
	if len(errs) > 0 {
		return errors.New("invalid env values: " + strings.Join(errs, "; "))
	}
	return nil
}

// EnvKeys returns every env-var name the Config struct binds. Used by
// sync_test.go to enforce parity with .env.example.
func EnvKeys() []string {
	c := &Config{}
	specs := c.specs()
	out := make([]string, 0, len(specs))
	for _, s := range specs {
		out = append(out, s.name)
	}
	return out
}
