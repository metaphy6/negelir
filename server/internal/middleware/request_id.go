package middleware

import (
	"crypto/rand"
	"fmt"
	"time"

	"github.com/gin-gonic/gin"
)

// ContextKeyRequestID is the Gin context key under which the effective
// X-Request-ID is stored so that downstream middleware (audit emitter,
// error encoder, content-type enforcer) can retrieve it without
// re-reading the response header.
const ContextKeyRequestID = "request_id"

// RequestID returns a Gin middleware that implements the X-Request-ID
// contract (§9.1 header inventory, binding):
//   - If the client supplies X-Request-ID, echo it back unchanged.
//   - If absent, mint a UUIDv7 (sortable, monotonic) and set it on both
//     the Gin context and the response header.
//
// UUIDv7 is chosen over v4 because the timestamp prefix makes request IDs
// lexicographically sortable, which simplifies log correlation across
// replicas without a central sequence authority.
func RequestID() gin.HandlerFunc {
	return func(c *gin.Context) {
		id := c.GetHeader("X-Request-ID")
		if id == "" {
			id = newUUIDv7()
		}
		c.Set(ContextKeyRequestID, id)
		c.Header("X-Request-ID", id)
		c.Next()
	}
}

// newUUIDv7 returns a randomly-seeded version 7 UUID (RFC 9562).
//
// Layout (128 bits):
//
//	bits  0-47  unix_ts_ms — 48-bit Unix millisecond timestamp (big-endian)
//	bits 48-51  ver        — 4-bit version field = 7 (0b0111)
//	bits 52-63  rand_a     — 12 bits of cryptographic random
//	bits 64-65  var        — 2-bit variant = 10 (RFC 4122)
//	bits 66-127 rand_b     — 62 bits of cryptographic random
//
// Two UUIDs generated in the same millisecond differ only in the random
// fields; across different milliseconds they sort by creation time.
func newUUIDv7() string {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		// crypto/rand.Read can only fail on catastrophic OS entropy
		// exhaustion — treat as unrecoverable.
		panic("middleware: crypto/rand.Read failed: " + err.Error())
	}
	now := time.Now().UnixMilli()
	b[0] = byte(now >> 40)
	b[1] = byte(now >> 32)
	b[2] = byte(now >> 24)
	b[3] = byte(now >> 16)
	b[4] = byte(now >> 8)
	b[5] = byte(now)
	b[6] = (b[6] & 0x0f) | 0x70 // version 7
	b[8] = (b[8] & 0x3f) | 0x80 // variant 10 (RFC 4122)
	return fmt.Sprintf("%08x-%04x-%04x-%04x-%012x",
		b[0:4], b[4:6], b[6:8], b[8:10], b[10:16])
}
