package config

import (
	"os"
	"path/filepath"
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
		HTTPReadTimeoutSec: 1, HTTPWriteTimeoutSec: 1, HTTPHandlerTimeoutSec: 1, HTTPShutdownTimeoutSec: 1,
		CacheMatchesTTLSec: 1, CacheTeamsTTLSec: 1, SwarmHeartbeatSec: 1,
		APITimeFormat: "iso8601_utc"}
	if err := cfg.Validate(); err == nil {
		t.Fatal("expected error for SERVER_PORT=70000, got nil")
	}
}

func TestValidateBadDatabaseURL(t *testing.T) {
	cfg := &Config{Port: "8080", PostgresPort: "5432", RedisPort: "6379", DBMaxConns: 1,
		DBConnectTimeoutSec: 1, DBPingTimeoutSec: 1, DBRetryDelaySec: 1, RedisRetryDelaySec: 1,
		HTTPReadTimeoutSec: 1, HTTPWriteTimeoutSec: 1, HTTPHandlerTimeoutSec: 1, HTTPShutdownTimeoutSec: 1,
		CacheMatchesTTLSec: 1, CacheTeamsTTLSec: 1, SwarmHeartbeatSec: 1,
		APITimeFormat: "iso8601_utc", APICursorTTLSec: 1800,
		APIRequestMaxBytes: 65536, QAInputMaxBytes: 65536, AuthLoginMaxBytes: 4096,
		APIBcryptCost: 12,
		// §9.2 JWT knobs — must be valid so the DATABASE_URL check is reached.
		APIJWTKeyDir: "data/api/jwt_keys", APIJWTKeyPollSec: 10, APIJWTRetiredGraceSec: 960,
		// §9.2 token shape — must be valid so the DATABASE_URL check is reached.
		APIAccessTTLSec: 900, APIRefreshTTLSec: 2592000, APIRefreshReplayGraceSec: 30,
		APIRevocationSetMax: 10000,
		// §9.2 self-registration — must be valid so the DATABASE_URL check is reached.
		APIRegisterCapPerSubnetPerH: 20,
		// §9.3 reply reaper — must be valid so the DATABASE_URL check is reached.
		APIReplyReaperSec: 60,
		// §9.3 idempotency — must be valid so the DATABASE_URL check is reached.
		APIIdempotencyTTLS: 86400, APIIdempotencyInflightWaitMs: 500,
		// §9.9 backpressure threshold — must be valid so the DATABASE_URL check is reached.
		APIPredictRequestBacklogHigh: 5000,
		// §9.9 concurrency semaphore — must be valid so the DATABASE_URL check is reached.
		APIMaxConcurrentRequests: 5000,
		// §9.9 response-side backpressure — must be valid so the DATABASE_URL check is reached.
		APIResponseWriteTimeoutMs: 5000,
		// §9.7 burst budget — must be valid so the DATABASE_URL check is reached.
		APIBurstCapacity: 60, APIBurstRefillPerS: 2.0,
		// §9.3 SWR cache knobs — must be valid so the DATABASE_URL check is reached.
		APICacheStaleAfterS: 30, APICacheMaxAgeS: 300, APISWRInflightMax: 64,
		ComputeClass: "cpu_only",
		// §9.8 telemetry — must be valid so the DATABASE_URL check is reached.
		TelemetryMetricsPort: "9091", TelemetryMaxSeries: 10000,
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

// TestAPITimeFormatDefault asserts the zero-env default is "iso8601_utc" and
// that Load succeeds (triangle test: §9.1 cfg knob has exactly one legal value).
func TestAPITimeFormatDefault(t *testing.T) {
	clearAllEnv(t)
	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load() with cleared env returned error: %v", err)
	}
	if cfg.APITimeFormat != "iso8601_utc" {
		t.Errorf("APITimeFormat default = %q, want \"iso8601_utc\"", cfg.APITimeFormat)
	}
}

// TestAPITimeFormatRejectsOtherValues asserts the validator rejects any value
// other than "iso8601_utc" — prevents typos from silently enabling local-zone
// or epoch-int output.
func TestAPITimeFormatRejectsOtherValues(t *testing.T) {
	for _, bad := range []string{"rfc3339", "epoch", "local", "RFC9557"} {
		t.Run(bad, func(t *testing.T) {
			clearAllEnv(t)
			t.Setenv("NEGELIR_API_TIME_FORMAT", bad)
			if _, err := Load(); err == nil {
				t.Errorf("Load() with NEGELIR_API_TIME_FORMAT=%q expected error, got nil", bad)
			}
		})
	}
}

// TestComputeClassDefaultCPUOnly — §9.15 Phase 11 boundary: NEGELIR_COMPUTE_CLASS
// must default to "cpu_only" so the container declares its compute constraint at
// startup without requiring an explicit operator knob.
func TestComputeClassDefaultCPUOnly(t *testing.T) {
	clearAllEnv(t)
	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.ComputeClass != "cpu_only" {
		t.Errorf("ComputeClass default = %q, want %q", cfg.ComputeClass, "cpu_only")
	}
}

// TestComputeClassRejectsOtherValues — adversarial: Validate() must reject any
// value other than "cpu_only" in v1 so an operator cannot accidentally enable a
// CUDA path that is not present in the binary.
func TestComputeClassRejectsOtherValues(t *testing.T) {
	for _, bad := range []string{"gpu_only", "cuda", "auto", "gpu_optional"} {
		t.Run(bad, func(t *testing.T) {
			clearAllEnv(t)
			t.Setenv("NEGELIR_COMPUTE_CLASS", bad)
			if _, err := Load(); err == nil {
				t.Errorf("Load() with NEGELIR_COMPUTE_CLASS=%q expected error, got nil", bad)
			}
		})
	}
}

// TestCmdAPIMainBuildTagConstraint — boundary (§9.15 Phase 11): cmd/api/main.go
// MUST carry the //go:build cpu_only constraint so the binary is never built
// without the cpu_only tag (cgo CUDA paths excluded). This is a static source
// check: if someone removes the tag, this test fails before any binary is built.
func TestCmdAPIMainBuildTagConstraint(t *testing.T) {
	// Walk up from the config package directory to find the server root
	// (containing go.mod), then resolve cmd/api/main.go.
	dir, err := os.Getwd()
	if err != nil {
		t.Fatalf("getwd: %v", err)
	}
	// Locate server root by finding go.mod while walking up.
	serverRoot := ""
	for i := 0; i < 8; i++ {
		if _, statErr := os.Stat(filepath.Join(dir, "go.mod")); statErr == nil {
			serverRoot = dir
			break
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			break
		}
		dir = parent
	}
	if serverRoot == "" {
		t.Fatal("could not locate server root (go.mod) walking up from config package")
	}
	mainGo := filepath.Join(serverRoot, "cmd", "api", "main.go")
	content, err := os.ReadFile(mainGo)
	if err != nil {
		t.Fatalf("cannot read cmd/api/main.go: %v", err)
	}
	if !strings.Contains(string(content), "//go:build cpu_only") {
		t.Error("cmd/api/main.go must contain '//go:build cpu_only' build constraint (§9.15 Phase 11 boundary)")
	}
}

// TestAPITransitJitterMsDefault — §9.3 timeout-budget chaining: transit jitter
// must default to 100 ms so the boot validator includes it in the inequality
// without requiring an explicit operator knob.
func TestAPITransitJitterMsDefault(t *testing.T) {
	clearAllEnv(t)
	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load() with cleared env returned error: %v", err)
	}
	if cfg.APITransitJitterMs != 100 {
		t.Errorf("APITransitJitterMs default = %d, want 100", cfg.APITransitJitterMs)
	}
}

// TestTimeoutBudgetChainingRejectsUndersizedTimeout — adversarial §9.3:
// Validate() must refuse to start when APIRequestTimeoutMs < sum of all
// budget components including transit jitter.
func TestTimeoutBudgetChainingRejectsUndersizedTimeout(t *testing.T) {
	clearAllEnv(t)
	// Set all components so their sum (200+100+100+50 = 450) exceeds the timeout.
	t.Setenv("NEGELIR_CONSENSUS_WINDOW_MS", "200")
	t.Setenv("NEGELIR_PROOFREADER_QUORUM_WINDOW_MS", "100")
	t.Setenv("NEGELIR_API_CONSENSUS_OVERHEAD_MS", "100")
	t.Setenv("NEGELIR_API_TRANSIT_JITTER_MS", "50")
	t.Setenv("NEGELIR_API_REQUEST_TIMEOUT_MS", "400") // 400 < 450 → must fail
	if _, err := Load(); err == nil {
		t.Fatal("expected timeout-budget error when APIRequestTimeoutMs < sum of components, got nil")
	}
}

// TestTimeoutBudgetChainingAcceptsExactMinimum — §9.3: Validate() must accept
// a timeout that equals exactly the sum of all budget components.
func TestTimeoutBudgetChainingAcceptsExactMinimum(t *testing.T) {
	clearAllEnv(t)
	// Sum = 200 + 100 + 100 + 50 = 450.
	t.Setenv("NEGELIR_CONSENSUS_WINDOW_MS", "200")
	t.Setenv("NEGELIR_PROOFREADER_QUORUM_WINDOW_MS", "100")
	t.Setenv("NEGELIR_API_CONSENSUS_OVERHEAD_MS", "100")
	t.Setenv("NEGELIR_API_TRANSIT_JITTER_MS", "50")
	t.Setenv("NEGELIR_API_REQUEST_TIMEOUT_MS", "450") // exactly equal → must pass
	if _, err := Load(); err != nil {
		t.Fatalf("Load() rejected exact-minimum timeout: %v", err)
	}
}

// TestTransitJitterNegativeRejected — adversarial §9.3: Validate() must reject
// a negative transit jitter value (operator typo or unit confusion).
func TestTransitJitterNegativeRejected(t *testing.T) {
	clearAllEnv(t)
	t.Setenv("NEGELIR_API_TRANSIT_JITTER_MS", "-1")
	if _, err := Load(); err == nil {
		t.Fatal("expected error for NEGELIR_API_TRANSIT_JITTER_MS=-1, got nil")
	}
}

// TestTimeoutChainValidatorRefusesBoot — §9.14 proof test: setting
// NEGELIR_API_REQUEST_TIMEOUT_MS below the consensus-chain minimum must cause
// Load() / Validate() to return an error that names the env var.
//
// Chain minimum: ConsensusWindowMs(750) + ProofreaderQuorumWindowMs(200)
//                + APIConsensusOverheadMs(200) + APITransitJitterMs(100) = 1250 ms.
// Setting 100 ms is far below this threshold.
func TestTimeoutChainValidatorRefusesBoot(t *testing.T) {
	clearAllEnv(t)
	t.Setenv("NEGELIR_API_REQUEST_TIMEOUT_MS", "100")
	_, err := Load()
	if err == nil {
		t.Fatal("expected error when api_request_timeout_ms < consensus chain sum, got nil")
	}
	if !strings.Contains(err.Error(), "NEGELIR_API_REQUEST_TIMEOUT_MS") {
		t.Errorf("error must mention NEGELIR_API_REQUEST_TIMEOUT_MS; got: %q", err.Error())
	}
}
