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
	HTTPShutdownTimeoutSec   int    `env:"HTTP_SHUTDOWN_TIMEOUT_SEC" default:"5"`
	CacheMatchesTTLSec       int    `env:"CACHE_MATCHES_TTL_SEC"     default:"300"`
	CacheTeamsTTLSec         int    `env:"CACHE_TEAMS_TTL_SEC"       default:"600"`

	// Shared with Python (ai/common/config.py) — used by `swarmctl` to
	// compute the dead-after-3-missed-heartbeats marker. Marked `# shared`
	// in .env.example.
	SwarmHeartbeatSec int `env:"SWARM_HEARTBEAT_SEC" default:"5"`
}

// Duration helpers — keep callers free of `time.Duration(x) * time.Second`.

func (c *Config) DBConnectTimeout() time.Duration    { return secondsToDuration(c.DBConnectTimeoutSec) }
func (c *Config) DBPingTimeout() time.Duration       { return secondsToDuration(c.DBPingTimeoutSec) }
func (c *Config) DBRetryDelay() time.Duration        { return secondsToDuration(c.DBRetryDelaySec) }
func (c *Config) RedisRetryDelay() time.Duration     { return secondsToDuration(c.RedisRetryDelaySec) }
func (c *Config) HTTPReadTimeout() time.Duration     { return secondsToDuration(c.HTTPReadTimeoutSec) }
func (c *Config) HTTPWriteTimeout() time.Duration    { return secondsToDuration(c.HTTPWriteTimeoutSec) }
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

// MustLoad is the panic-on-error variant; convenient for main().
func MustLoad() *Config {
	cfg, err := Load()
	if err != nil {
		panic(err)
	}
	return cfg
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
		"HTTP_SHUTDOWN_TIMEOUT_SEC": c.HTTPShutdownTimeoutSec,
		"CACHE_MATCHES_TTL_SEC":     c.CacheMatchesTTLSec,
		"CACHE_TEAMS_TTL_SEC":       c.CacheTeamsTTLSec,
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
		{name: "HTTP_SHUTDOWN_TIMEOUT_SEC", dflt: "5", intDst: &c.HTTPShutdownTimeoutSec},
		{name: "CACHE_MATCHES_TTL_SEC", dflt: "300", intDst: &c.CacheMatchesTTLSec},
		{name: "CACHE_TEAMS_TTL_SEC", dflt: "600", intDst: &c.CacheTeamsTTLSec},
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
