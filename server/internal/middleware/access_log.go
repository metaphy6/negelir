package middleware

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"math/rand"
	"net"
	"os"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/metaphy6/negelir/server/internal/config"
)

// Context keys for timing and error values set by upstream middleware.
// SecGate and Authenticate middleware reference these keys when they
// record their own processing latency.

// ContextKeySecGateMs is the Gin context key under which the security-gate
// processing latency (milliseconds, int64) is stored by the SecGate middleware.
const ContextKeySecGateMs = "sec.gate_ms"

// ContextKeyAuthMs is the Gin context key under which the JWT authentication
// latency (milliseconds, int64) is stored by the Authenticate middleware.
const ContextKeyAuthMs = "auth.latency_ms"

// ContextKeyErrorCode is the Gin context key under which the machine-readable
// API error code (string, e.g. "rate_limited", "invalid_cursor") is stored by
// error-emitting middleware and handlers.
const ContextKeyErrorCode = "api.error_code"

// accessLogEntry is the structured log line written per request.
// omitempty omits absent context values so the JSON stays compact.
type accessLogEntry struct {
	TS             string  `json:"ts"`
	RequestID      string  `json:"request_id,omitempty"`
	TraceID        string  `json:"trace_id,omitempty"`
	Route          string  `json:"route,omitempty"`
	Method         string  `json:"method"`
	Status         int     `json:"status"`
	LatencyMs      int64   `json:"latency_ms"`
	UserIDH        *string `json:"user_id_h,omitempty"`
	AnonSubjectKey string  `json:"anon_subject_key,omitempty"`
	IPSubject      string  `json:"ip_subject,omitempty"`
	SecGateMs      *int64  `json:"sec_gate_ms,omitempty"`
	AuthMs         *int64  `json:"auth_ms,omitempty"`
	Cache          string  `json:"cache,omitempty"`
	Degraded       string  `json:"degraded,omitempty"`
	ErrorCode      *string `json:"error_code,omitempty"`
}

// hashUserID returns the first 12 hex characters of sha256(userID).
// This is the only form in which user identity may appear in access logs.
// The raw user_id is never written.
func hashUserID(userID string) string {
	sum := sha256.Sum256([]byte(userID))
	return hex.EncodeToString(sum[:])[:12]
}

// AccessLog returns a Gin middleware that writes one JSON access-log line to
// os.Stderr after the full handler chain returns.
//
// Sampling:
//   - 2xx responses: logged at cfg.APILogSamplePct percent (0=never, 100=always).
//   - 4xx / 5xx responses: always logged regardless of sampling config.
//
// PII discipline: ContextKeyUserID is sha256-hashed to 12 hex chars before
// writing; the raw user_id never appears in the log.
//
// Placement: register AFTER TraceParent, RequestID, XFF, SecGate, and
// Authenticate so all context keys are populated before assembly.
func AccessLog(cfg *config.Config) gin.HandlerFunc {
	return accessLogWithWriter(cfg, os.Stderr)
}

// accessLogWithWriter is the testable form of AccessLog. Tests pass a
// *bytes.Buffer; production code passes os.Stderr via AccessLog.
func accessLogWithWriter(cfg *config.Config, w io.Writer) gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		c.Next()

		status := c.Writer.Status()
		latencyMs := time.Since(start).Milliseconds()

		// Sampling decision: 4xx/5xx always log; 2xx at cfg.APILogSamplePct %.
		if status >= 200 && status < 300 {
			pct := cfg.APILogSamplePct
			if pct <= 0 {
				return // sampling=0: never log 2xx
			}
			if pct < 100 {
				// math/rand is intentional: sampling doesn't need cryptographic randomness.
				//nolint:gosec
				if rand.Intn(100) >= pct {
					return // not selected by sampler
				}
			}
		}

		entry := accessLogEntry{
			TS:        time.Now().UTC().Format(time.RFC3339Nano),
			RequestID: c.GetString(ContextKeyRequestID),
			TraceID:   c.GetString(ContextKeyTraceID),
			Route:     c.FullPath(),
			Method:    c.Request.Method,
			Status:    status,
			LatencyMs: latencyMs,
		}

		// user_id_h: sha256(user_id)[:12] — NEVER raw user_id.
		if uid := c.GetString(ContextKeyUserID); uid != "" {
			h := hashUserID(uid)
			entry.UserIDH = &h
		}

		// anon_subject_key: per-IP rate-bucket subject (e.g. "203.0.113.7/32").
		entry.AnonSubjectKey = c.GetString(ContextKeyRateSubject)

		// ip_subject: raw net.IP stored by XFF middleware.
		if ipRaw, ok := c.Get(ContextKeyClientIP); ok {
			if ip, ok := ipRaw.(net.IP); ok {
				entry.IPSubject = ip.String()
			}
		}

		// sec_gate_ms and auth_ms: set by SecGate / Authenticate when implemented.
		if v, ok := c.Get(ContextKeySecGateMs); ok {
			if ms, ok := toInt64(v); ok {
				entry.SecGateMs = &ms
			}
		}
		if v, ok := c.Get(ContextKeyAuthMs); ok {
			if ms, ok := toInt64(v); ok {
				entry.AuthMs = &ms
			}
		}

		// cache: mirrors metrics.ContextKeyCacheStatus ("metrics.cache_status").
		entry.Cache = c.GetString("metrics.cache_status")
		// degraded: mirrors metrics.ContextKeyDegraded ("metrics.degraded").
		entry.Degraded = c.GetString("metrics.degraded")

		// error_code: set by error-emitting middleware and handlers.
		if v, ok := c.Get(ContextKeyErrorCode); ok {
			if code, ok := v.(string); ok && code != "" {
				entry.ErrorCode = &code
			}
		}

		b, err := json.Marshal(entry)
		if err != nil {
			return // encoding failure: skip rather than partial write
		}
		b = append(b, '\n')
		_, _ = w.Write(b)
	}
}

// toInt64 converts int, int64, int32, or float64 to int64.
// Used to read timing values set by upstream middleware regardless of the
// concrete numeric type the setter used.
func toInt64(v any) (int64, bool) {
	switch x := v.(type) {
	case int64:
		return x, true
	case int:
		return int64(x), true
	case float64:
		return int64(x), true
	case int32:
		return int64(x), true
	}
	return 0, false
}
