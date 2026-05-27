package middleware

import (
	"crypto/rand"
	"encoding/hex"
	"regexp"
	"strings"

	"github.com/gin-gonic/gin"
)

// ContextKeyTraceID is the Gin context key under which the 32-hex W3C
// trace_id component is stored so downstream middleware, handlers, and
// bus publishers can attach it to the bus envelope without re-parsing headers.
const ContextKeyTraceID = "trace_id"

// traceparentHeaderRe validates the W3C Trace Context traceparent header
// (version-traceID-parentID-flags) and captures the 32-hex traceID.
var traceparentHeaderRe = regexp.MustCompile(
	`^[0-9a-f]{2}-([0-9a-f]{32})-[0-9a-f]{16}-[0-9a-f]{2}$`,
)

// TraceParent returns a Gin middleware that implements the §9.5 W3C
// traceparent contract:
//
//   - If the client supplies a valid Traceparent header (W3C Trace Context
//     format "00-<32hex>-<16hex>-<flags>"), the trace_id component is reused.
//   - Else if the client supplies X-Request-ID whose value normalises to 32
//     lower-case hex characters (e.g. a UUID with dashes stripped), that
//     value is used as the trace_id.
//   - Else a fresh trace_id (32 random hex, 16 bytes) and span_id (16 random
//     hex, 8 bytes) are minted using crypto/rand.
//
// A new span_id is always generated for this hop regardless of the source of
// the trace_id (each service hop gets its own span).
//
// Response headers set:
//
//	Traceparent  — "00-<traceID>-<spanID>-01" (sampled, version 00)
//	X-Request-ID — the 32-hex traceID (client-side alias for correlation)
//
// The trace_id is also stored in the Gin context under ContextKeyTraceID so
// that bus publishers can attach it to the envelope (§8.15.6).
//
// Placement: this middleware MUST be the first handler in the chain (before
// auth, sec gate, rate limiter, etc.) so every subsequent handler sees a
// populated ContextKeyTraceID.
func TraceParent() gin.HandlerFunc {
	return func(c *gin.Context) {
		traceID := resolveTraceID(c)
		spanID := newSpanID()

		traceparent := "00-" + traceID + "-" + spanID + "-01"

		c.Set(ContextKeyTraceID, traceID)
		c.Header("Traceparent", traceparent)
		c.Header("X-Request-ID", traceID)

		c.Next()
	}
}

// resolveTraceID extracts or mints the trace_id for this hop in priority order:
//  1. Valid incoming Traceparent header -> extract its trace_id component.
//  2. X-Request-ID that normalises to 32 lower-case hex -> use as trace_id.
//  3. Otherwise -> mint a random 32-hex trace_id (16 bytes, crypto/rand).
func resolveTraceID(c *gin.Context) string {
	// 1. W3C traceparent header -- must match version-traceID-parentID-flags.
	if tp := strings.ToLower(strings.TrimSpace(c.GetHeader("Traceparent"))); tp != "" {
		if m := traceparentHeaderRe.FindStringSubmatch(tp); m != nil {
			return m[1]
		}
	}

	// 2. X-Request-ID as alias: strip dashes, require 32 lower-case hex.
	if xid := strings.ToLower(strings.ReplaceAll(c.GetHeader("X-Request-ID"), "-", "")); len(xid) == 32 && isLowerHex(xid) {
		return xid
	}

	// 3. Mint fresh trace_id.
	return newTraceID()
}

// isLowerHex returns true if every character in s is a lower-case hex digit.
func isLowerHex(s string) bool {
	for _, ch := range s {
		if !((ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f')) {
			return false
		}
	}
	return true
}

// newTraceID returns 32 lower-case hex characters derived from 16 crypto-random bytes.
func newTraceID() string {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		panic("middleware: crypto/rand.Read failed: " + err.Error())
	}
	return hex.EncodeToString(b[:])
}

// newSpanID returns 16 lower-case hex characters derived from 8 crypto-random bytes.
func newSpanID() string {
	var b [8]byte
	if _, err := rand.Read(b[:]); err != nil {
		panic("middleware: crypto/rand.Read failed: " + err.Error())
	}
	return hex.EncodeToString(b[:])
}
