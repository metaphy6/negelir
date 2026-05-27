package middleware

import (
	"bytes"
	"encoding/json"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"

	"github.com/metaphy6/negelir/server/internal/config"
)

// minCfg returns the smallest valid Config for access-log tests.
// APILogSamplePct is set by the caller.
func minAccessLogCfg(samplePct int) *config.Config {
	return &config.Config{
		Port:                        "8080",
		PostgresPort:                "5432",
		RedisPort:                   "6379",
		DBMaxConns:                  10,
		DBConnectTimeoutSec:         5,
		DBPingTimeoutSec:            5,
		DBRetryDelaySec:             3,
		RedisRetryDelaySec:          2,
		HTTPReadTimeoutSec:          10,
		HTTPWriteTimeoutSec:         30,
		HTTPHandlerTimeoutSec:       25,
		HTTPShutdownTimeoutSec:      5,
		CacheMatchesTTLSec:          300,
		CacheTeamsTTLSec:            600,
		SwarmHeartbeatSec:           5,
		APIRequestTimeoutMs:         3000,
		ConsensusWindowMs:           750,
		APIConsensusOverheadMs:      250,
		ProofreaderQuorumWindowMs:   200,
		APITransitJitterMs:          100,
		APITimeFormat:               "iso8601_utc",
		APICursorTTLSec:             1800,
		APIRequestMaxBytes:          65536,
		QAInputMaxBytes:             65536,
		AuthLoginMaxBytes:           4096,
		APIBcryptCost:               12,
		APIJWTKeyDir:                "data/api/jwt_keys",
		APIJWTKeyPollSec:            10,
		APIJWTRetiredGraceSec:       960,
		APIAccessTTLSec:             900,
		APIRefreshTTLSec:            2592000,
		APIRefreshReplayGraceSec:    30,
		APIRevocationSetMax:         10000,
		APIRegisterCapPerSubnetPerH: 20,
		APIIdempotencyTTLS:          86400,
		APIIdempotencyInflightWaitMs: 500,
		APIReplyReaperSec:           60,
		APIBurstCapacity:            60,
		APIBurstRefillPerS:          2.0,
		APIPredictRequestBacklogHigh: 5000,
		APIResponseWriteTimeoutMs:    5000,
		APICacheStaleAfterS:         30,
		APICacheMaxAgeS:             300,
		APISWRInflightMax:           64,
		ComputeClass:                "cpu_only",
		TelemetryMetricsPort:        "9091",
		TelemetryMaxSeries:          10000,
		APILogSamplePct:             samplePct,
		SecInputMaxLen:              8192,
		SecInputGatewayMaxLatencyMs: 10,
		SecInputPatternReloadSec:    30,
		SecQuarantinePayloadMaxBytes: 65536,
		SecRatePreAuthCapacity:      30,
		SecRatePreAuthRefillPerS:    0.5,
		SecRatePostAuthCapacity:     600,
		SecRatePostAuthRefillPerS:   5.0,
		SecRateBucketIdleTTLSec:     3600,
		SecRateIPv4Prefix:           32,
		SecRateIPv6Prefix:           64,
		SecRateRedisTimeoutMs:       50,
		SecRateSecondaryCapacity:    300,
		SecRateSecondaryRefillPerS:  5.0,
		SecRateDefaultCost:          1,
		SecDenylistMaxEntries:       250000,
	}
}

// accessLogRouter builds a minimal Gin router that applies accessLogWithWriter
// and registers GET /test which returns the given status.
func accessLogRouter(cfg *config.Config, buf *bytes.Buffer, status int) *gin.Engine {
	gn := gin.New()
	gn.Use(accessLogWithWriter(cfg, buf))
	gn.GET("/test", func(c *gin.Context) {
		c.Status(status)
	})
	gn.GET("/v1/matches/:id", func(c *gin.Context) {
		c.Status(status)
	})
	return gn
}

// TestAccessLog_200_Sample100_Logged verifies that a 200 response with
// sampling=100 produces a log line on the writer.
func TestAccessLog_200_Sample100_Logged(t *testing.T) {
	var buf bytes.Buffer
	r := accessLogRouter(minAccessLogCfg(100), &buf, http.StatusOK)

	req := httptest.NewRequest(http.MethodGet, "/test", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if buf.Len() == 0 {
		t.Fatal("expected log output for 200 with sample=100, got none")
	}
	var entry map[string]any
	if err := json.Unmarshal(bytes.TrimRight(buf.Bytes(), "\n"), &entry); err != nil {
		t.Fatalf("log line is not valid JSON: %v — got: %s", err, buf.String())
	}
	if entry["status"] != float64(200) {
		t.Errorf("status = %v; want 200", entry["status"])
	}
	if entry["method"] != "GET" {
		t.Errorf("method = %v; want GET", entry["method"])
	}
	if _, ok := entry["ts"]; !ok {
		t.Error("log line missing ts field")
	}
}

// TestAccessLog_200_Sample0_NotLogged verifies that a 200 response with
// sampling=0 produces no log output.
func TestAccessLog_200_Sample0_NotLogged(t *testing.T) {
	var buf bytes.Buffer
	r := accessLogRouter(minAccessLogCfg(0), &buf, http.StatusOK)

	req := httptest.NewRequest(http.MethodGet, "/test", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if buf.Len() != 0 {
		t.Fatalf("expected no log output for 200 with sample=0, got: %s", buf.String())
	}
}

// TestAccessLog_4xx_Sample0_AlwaysLogged verifies that a 4xx response is
// always logged even when sampling is set to 0.
func TestAccessLog_4xx_Sample0_AlwaysLogged(t *testing.T) {
	var buf bytes.Buffer
	r := accessLogRouter(minAccessLogCfg(0), &buf, http.StatusNotFound)

	req := httptest.NewRequest(http.MethodGet, "/test", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if buf.Len() == 0 {
		t.Fatal("expected log output for 4xx with sample=0, got none")
	}
	var entry map[string]any
	if err := json.Unmarshal(bytes.TrimRight(buf.Bytes(), "\n"), &entry); err != nil {
		t.Fatalf("log line is not valid JSON: %v", err)
	}
	if entry["status"] != float64(404) {
		t.Errorf("status = %v; want 404", entry["status"])
	}
}

// TestAccessLog_5xx_Sample0_AlwaysLogged verifies that a 5xx response is
// always logged even when sampling is set to 0.
func TestAccessLog_5xx_Sample0_AlwaysLogged(t *testing.T) {
	var buf bytes.Buffer
	r := accessLogRouter(minAccessLogCfg(0), &buf, http.StatusInternalServerError)

	req := httptest.NewRequest(http.MethodGet, "/test", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if buf.Len() == 0 {
		t.Fatal("expected log output for 5xx with sample=0, got none")
	}
}

// TestAccessLog_UserID_Hashed verifies that the raw user_id is never written
// to the log — only the 12-character sha256 prefix appears as user_id_h.
func TestAccessLog_UserID_Hashed(t *testing.T) {
	const rawUID = "user-secret-12345"

	var buf bytes.Buffer
	cfg := minAccessLogCfg(100)
	gn := gin.New()
	gn.Use(func(c *gin.Context) {
		c.Set(ContextKeyUserID, rawUID)
		c.Next()
	})
	gn.Use(accessLogWithWriter(cfg, &buf))
	gn.GET("/test", func(c *gin.Context) { c.Status(http.StatusOK) })

	req := httptest.NewRequest(http.MethodGet, "/test", nil)
	w := httptest.NewRecorder()
	gn.ServeHTTP(w, req)

	logLine := buf.String()
	if strings.Contains(logLine, rawUID) {
		t.Errorf("raw user_id leaked into log: %s", logLine)
	}

	var entry map[string]any
	if err := json.Unmarshal(bytes.TrimRight(buf.Bytes(), "\n"), &entry); err != nil {
		t.Fatalf("invalid JSON: %v", err)
	}

	uidH, ok := entry["user_id_h"].(string)
	if !ok {
		t.Fatal("user_id_h missing or not a string")
	}
	if len(uidH) != 12 {
		t.Errorf("user_id_h length = %d; want 12", len(uidH))
	}
	// Verify it's valid hex.
	for _, ch := range uidH {
		if !((ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f')) {
			t.Errorf("user_id_h %q contains non-hex character %q", uidH, ch)
		}
	}
}

// TestAccessLog_MissingContext_NoFields verifies that when no optional context
// keys are set, omitempty fields are absent from the JSON output.
func TestAccessLog_MissingContext_NoFields(t *testing.T) {
	var buf bytes.Buffer
	r := accessLogRouter(minAccessLogCfg(100), &buf, http.StatusOK)

	req := httptest.NewRequest(http.MethodGet, "/test", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	var entry map[string]any
	if err := json.Unmarshal(bytes.TrimRight(buf.Bytes(), "\n"), &entry); err != nil {
		t.Fatalf("invalid JSON: %v", err)
	}
	for _, absent := range []string{"user_id_h", "sec_gate_ms", "auth_ms", "error_code"} {
		if _, ok := entry[absent]; ok {
			t.Errorf("field %q should be absent when context key is unset, but found it", absent)
		}
	}
}

// TestAccessLog_ContextFields verifies that optional context keys — when set —
// appear in the log entry with correct values.
func TestAccessLog_ContextFields(t *testing.T) {
	var buf bytes.Buffer
	cfg := minAccessLogCfg(100)

	gn := gin.New()
	gn.Use(func(c *gin.Context) {
		c.Set(ContextKeyRequestID, "req-abc")
		c.Set(ContextKeyTraceID, "trace-xyz")
		c.Set(ContextKeyRateSubject, "10.0.0.1/32")
		c.Set(ContextKeyClientIP, net.ParseIP("10.0.0.1"))
		c.Set(ContextKeySecGateMs, int64(3))
		c.Set(ContextKeyAuthMs, int64(7))
		c.Set("metrics.cache_status", "hit")
		c.Set("metrics.degraded", "false")
		c.Set(ContextKeyErrorCode, "")
		c.Next()
	})
	gn.Use(accessLogWithWriter(cfg, &buf))
	gn.GET("/test", func(c *gin.Context) { c.Status(http.StatusOK) })

	req := httptest.NewRequest(http.MethodGet, "/test", nil)
	w := httptest.NewRecorder()
	gn.ServeHTTP(w, req)

	var entry map[string]any
	if err := json.Unmarshal(bytes.TrimRight(buf.Bytes(), "\n"), &entry); err != nil {
		t.Fatalf("invalid JSON: %v", err)
	}

	tests := []struct {
		field string
		want  any
	}{
		{"request_id", "req-abc"},
		{"trace_id", "trace-xyz"},
		{"anon_subject_key", "10.0.0.1/32"},
		{"ip_subject", "10.0.0.1"},
		{"sec_gate_ms", float64(3)},
		{"auth_ms", float64(7)},
		{"cache", "hit"},
		{"degraded", "false"},
	}
	for _, tt := range tests {
		got, ok := entry[tt.field]
		if !ok {
			t.Errorf("field %q missing from log", tt.field)
			continue
		}
		if got != tt.want {
			t.Errorf("field %q = %v; want %v", tt.field, got, tt.want)
		}
	}
	// Empty error_code should be omitted.
	if _, ok := entry["error_code"]; ok {
		t.Error("error_code should be omitted for empty string, but was present")
	}
}

// TestHashUserID verifies the hash function produces 12 lowercase hex chars.
func TestHashUserID(t *testing.T) {
	h := hashUserID("some-user-id")
	if len(h) != 12 {
		t.Errorf("hashUserID length = %d; want 12", len(h))
	}
	for _, ch := range h {
		if !((ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f')) {
			t.Errorf("non-hex character %q in hash %q", ch, h)
		}
	}
	// Deterministic.
	if hashUserID("some-user-id") != h {
		t.Error("hashUserID is not deterministic")
	}
	// Different input -> different hash (extremely high probability).
	if hashUserID("other-user-id") == h {
		t.Error("hashUserID collision on different inputs")
	}
}

// TestAdvLogFieldNoPII — adv_test_log_field_no_pii.
//
// A synthetic request whose body contains a raw email address and an IP
// address must NOT cause those values to appear in the structured access-log
// output. The log may carry user_id_h (sha256 prefix) and anon_subject_key
// (derived rate-bucket key) but never the raw PII values.
//
// Phase 12 prerequisite; must be green at Phase 9 close.
func TestAdvLogFieldNoPII(t *testing.T) {
	const rawEmail = "kullanici@negelir.com"
	const bodyIP   = "192.0.2.99"    // IP embedded in request body — NOT the client IP
	const clientIP = "198.51.100.7"  // actual client IP (set by XFF middleware stub)
	const userID   = "user-pii-42"   // authenticated user ID set by auth middleware stub

	var buf bytes.Buffer
	cfg := minAccessLogCfg(100) // always log — sampling=100

	gn := gin.New()
	gn.Use(func(c *gin.Context) {
		// Simulate the auth and XFF middleware populating the context.
		c.Set(ContextKeyUserID, userID)
		c.Set(ContextKeyRateSubject, clientIP+"/32")
		c.Set(ContextKeyClientIP, net.ParseIP(clientIP))
		c.Next()
	})
	gn.Use(accessLogWithWriter(cfg, &buf))
	gn.POST("/v1/qa", func(c *gin.Context) {
		c.Status(http.StatusOK)
	})

	// Body contains raw PII: an email address and a separate IP address that
	// is distinct from the actual client IP. The access log must not echo
	// either value from the request body.
	body := `{"email":"` + rawEmail + `","source_ip":"` + bodyIP + `","query":"next match"}`
	req := httptest.NewRequest(http.MethodPost, "/v1/qa", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	gn.ServeHTTP(w, req)

	logLine := buf.String()
	if logLine == "" {
		t.Fatal("expected access log output but got none")
	}

	// The raw email from the request body must NEVER appear in the log.
	if strings.Contains(logLine, rawEmail) {
		t.Errorf("raw email %q leaked into access log: %s", rawEmail, logLine)
	}

	// The IP address embedded in the request body must NEVER appear in the log.
	if strings.Contains(logLine, bodyIP) {
		t.Errorf("raw body IP %q leaked into access log: %s", bodyIP, logLine)
	}

	// The raw user_id must not appear — only its hash may.
	if strings.Contains(logLine, userID) {
		t.Errorf("raw user_id %q leaked into access log: %s", userID, logLine)
	}

	// Parse the JSON and assert the correct PII-safe fields are present.
	var entry map[string]any
	if err := json.Unmarshal(bytes.TrimRight(buf.Bytes(), "\n"), &entry); err != nil {
		t.Fatalf("access log is not valid JSON: %v — got: %s", err, buf.String())
	}
	if _, ok := entry["user_id_h"]; !ok {
		t.Error("user_id_h missing from access log — must be present for authenticated requests")
	}
	if _, ok := entry["anon_subject_key"]; !ok {
		t.Error("anon_subject_key missing from access log — must be present when rate subject is set")
	}
}
