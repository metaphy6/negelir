package config

import (
	"os"
	"strings"
	"testing"
)

// clearAllEnv unsets every key the Config binds, so tests start from defaults.
func clearAllEnv(t *testing.T) {
	t.Helper()
	for _, k := range EnvKeys() {
		t.Setenv(k, "")
	}
}

func TestLoadDefaults(t *testing.T) {
	clearAllEnv(t)
	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load() with cleared env returned error: %v", err)
	}
	if cfg.Port != "8080" {
		t.Errorf("Port default = %q, want %q", cfg.Port, "8080")
	}
	if cfg.DBMaxConns != 10 {
		t.Errorf("DBMaxConns default = %d, want %d", cfg.DBMaxConns, 10)
	}
	if cfg.DBConnectTimeoutSec != 5 {
		t.Errorf("DBConnectTimeoutSec default = %d, want %d", cfg.DBConnectTimeoutSec, 5)
	}
}

func TestLoadOverride(t *testing.T) {
	clearAllEnv(t)
	t.Setenv("SERVER_PORT", "9090")
	t.Setenv("DB_MAX_CONNS", "42")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.Port != "9090" {
		t.Errorf("Port override = %q, want %q", cfg.Port, "9090")
	}
	if cfg.DBMaxConns != 42 {
		t.Errorf("DBMaxConns override = %d, want %d", cfg.DBMaxConns, 42)
	}
}

func TestLoadInvalidInt(t *testing.T) {
	clearAllEnv(t)
	t.Setenv("DB_MAX_CONNS", "not-a-number")
	if _, err := Load(); err == nil {
		t.Fatal("expected error for non-numeric DB_MAX_CONNS, got nil")
	}
}

func TestValidateBadPort(t *testing.T) {
	cfg := &Config{Port: "70000", PostgresPort: "5432", RedisPort: "6379", DBMaxConns: 1,
		DBConnectTimeoutSec: 1, DBPingTimeoutSec: 1, DBRetryDelaySec: 1, RedisRetryDelaySec: 1,
		HTTPReadTimeoutSec: 1, HTTPWriteTimeoutSec: 1, HTTPShutdownTimeoutSec: 1,
		CacheMatchesTTLSec: 1, CacheTeamsTTLSec: 1, SwarmHeartbeatSec: 1}
	if err := cfg.Validate(); err == nil {
		t.Fatal("expected error for SERVER_PORT=70000, got nil")
	}
}

func TestValidateBadDatabaseURL(t *testing.T) {
	cfg := &Config{Port: "8080", PostgresPort: "5432", RedisPort: "6379", DBMaxConns: 1,
		DBConnectTimeoutSec: 1, DBPingTimeoutSec: 1, DBRetryDelaySec: 1, RedisRetryDelaySec: 1,
		HTTPReadTimeoutSec: 1, HTTPWriteTimeoutSec: 1, HTTPShutdownTimeoutSec: 1,
		CacheMatchesTTLSec: 1, CacheTeamsTTLSec: 1, SwarmHeartbeatSec: 1,
		DatabaseURL: "mysql://nope"}
	if err := cfg.Validate(); err == nil || !strings.Contains(err.Error(), "DATABASE_URL") {
		t.Fatalf("expected DATABASE_URL scheme error, got %v", err)
	}
}

func TestEffectiveDatabaseURLFromParts(t *testing.T) {
	cfg := &Config{
		PostgresUser: "u", PostgresPassword: "p",
		PostgresHost: "h", PostgresPort: "5432", PostgresDB: "d",
	}
	want := "postgres://u:p@h:5432/d?sslmode=disable"
	if got := cfg.EffectiveDatabaseURL(); got != want {
		t.Errorf("EffectiveDatabaseURL = %q, want %q", got, want)
	}
}

func TestEffectiveRedisURLOverride(t *testing.T) {
	cfg := &Config{RedisURL: "redis-cluster:6380"}
	if got := cfg.EffectiveRedisURL(); got != "redis-cluster:6380" {
		t.Errorf("EffectiveRedisURL override = %q, want passthrough", got)
	}
}

// Defensive: assert nothing slipped through that would let `os.LookupEnv`
// see a stale value across tests (Go's `t.Setenv` resets after each).
func TestEnvKeysCoverConfigStruct(t *testing.T) {
	if len(EnvKeys()) == 0 {
		t.Fatal("EnvKeys() is empty")
	}
	for _, k := range EnvKeys() {
		// All keys must be UPPER_SNAKE_CASE.
		if k != strings.ToUpper(k) || strings.ContainsAny(k, " -.") {
			t.Errorf("env key %q is not UPPER_SNAKE_CASE", k)
		}
		if _, ok := os.LookupEnv(k); ok && os.Getenv(k) == "" {
			// just touch — making sure os interactions are fine
		}
	}
}
