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
}

// Duration helpers — keep callers free of `time.Duration(x) * time.Second`.

func (c *Config) DBConnectTimeout() time.Duration    { return secondsToDuration(c.DBConnectTimeoutSec) }
func (c *Config) DBPingTimeout() time.Duration       { return secondsToDuration(c.DBPingTimeoutSec) }
func (c *Config) DBRetryDelay() time.Duration        { return secondsToDuration(c.DBRetryDelaySec) }
func (c *Config) RedisRetryDelay() time.Duration     { return secondsToDuration(c.RedisRetryDelaySec) }
func (c *Config) HTTPReadTimeout() time.Duration     { return secondsToDuration(c.HTTPReadTimeoutSec) }
func (c *Config) HTTPWriteTimeout() time.Duration    { return secondsToDuration(c.HTTPWriteTimeoutSec) }
func (c *Config) HTTPHandlerTimeout() time.Duration  { return secondsToDuration(c.HTTPHandlerTimeoutSec) }
func (c *Config) HTTPShutdownTimeout() time.Duration { return secondsToDuration(c.HTTPShutdownTimeoutSec) }
func (c *Config) MatchesCacheTTL() time.Duration     { return secondsToDuration(c.CacheMatchesTTLSec) }
func (c *Config) TeamsCacheTTL() time.Duration       { return secondsToDuration(c.CacheTeamsTTLSec) }

func secondsToDuration(s int) time.Duration { return time.Duration(s) * time.Second }

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
// Validate(); callers should fail fast on a non-nil error.
func Load() (*Config, error) {
	cfg := &Config{}
	if err := bindEnv(cfg); err != nil {
		return nil, fmt.Errorf("config.Load: %w", err)
	}
	return cfg, cfg.Validate()
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
