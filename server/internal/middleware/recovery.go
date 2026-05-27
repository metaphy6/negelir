package middleware

import (
	"context"
	"crypto/sha256"
	"fmt"
	"net/http"
	"runtime/debug"

	"github.com/gin-gonic/gin"
)

// RecoveryAlertFunc is called when a handler panics.
// kind is always "api_panic"; severity is always "critical".
// stackTraceSHA256 is the hex-encoded SHA-256 of the full stack trace —
// the trace itself is written only to stderr, never forwarded to the alert
// bus (PII risk: handler arguments may appear in the stack trace).
type RecoveryAlertFunc func(ctx context.Context, kind, severity, stackTraceSHA256 string)

// PanicRecovery returns a Gin middleware that catches handler panics,
// emits a sec.alert.v1{kind=api_panic, severity=critical} event with the
// SHA-256 of the stack trace, writes the raw stack trace to stderr only,
// and responds with HTTP 500.
//
// The middleware keeps the server process alive after a panic: the pod
// continues serving other requests normally.
//
// Placement: should be the FIRST middleware in the chain so it wraps all
// handlers including auth, rate limiting, etc.
//
// Phase 9 §9.17.4 binding contract.
func PanicRecovery(alertFn RecoveryAlertFunc) gin.HandlerFunc {
	return func(c *gin.Context) {
		defer func() {
			if r := recover(); r != nil {
				stack := debug.Stack()

				// SHA-256 of the stack trace (not the trace itself).
				h := sha256.Sum256(stack)
				sha := fmt.Sprintf("%x", h[:])

				// Write full trace to stderr only (local, not forwarded).
				fmt.Printf("PANIC recovered: %v\nstack-trace SHA256=%s\n%s\n",
					r, sha, stack)

				// Emit sec.alert.v1 with the hash (not the trace).
				if alertFn != nil {
					alertFn(c.Request.Context(), "api_panic", "critical", sha)
				}

				c.AbortWithStatus(http.StatusInternalServerError)
			}
		}()
		c.Next()
	}
}
