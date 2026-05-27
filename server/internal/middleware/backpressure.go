package middleware

import (
	"context"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/redis/go-redis/v9"

	aperrors "github.com/metaphy6/negelir/server/internal/errors"
)

// BackpressureFlagKey is the Redis key that signals backpressure mode is active.
// It is written by the §8.x scaler when XLEN(predict.request.v1) exceeds
// cfg.api_predict_request_backlog_high; the key carries a 30 s TTL.
//
// The API only reads this key. Writing to the maint plane or sec alert
// topics is solely the responsibility of the §8.x maint agents.
const BackpressureFlagKey = "api:backpressure:on"

// BackpressureReader is the minimal Redis GET surface the middleware needs.
// *redis.Client satisfies this interface via RedisBackpressure.
type BackpressureReader interface {
	// Get returns the stored value and nil on a hit, or ("", redis.Nil) on a
	// miss, or ("", <err>) on a Redis communication fault.
	Get(ctx context.Context, key string) (string, error)
}

// RedisBackpressure adapts a *redis.Client to BackpressureReader.
type RedisBackpressure struct{ C *redis.Client }

// Get delegates to the underlying Redis client.
func (r *RedisBackpressure) Get(ctx context.Context, key string) (string, error) {
	return r.C.Get(ctx, key).Result()
}

// BackpressureCheck returns a Gin middleware that enforces cache-only mode when
// BackpressureFlagKey (api:backpressure:on) is present in Redis.
//
// Behaviour when backpressure is active:
//   - GET: passes through; the cache layer serves from cache or returns 503.
//   - Non-GET (POST /v1/qa, etc.): returns 425 Too Early + Retry-After: 10.
//
// Fail-open: on Redis error the middleware passes the request through rather
// than blocking valid traffic during a transient Redis fault.
func BackpressureCheck(rdr BackpressureReader) gin.HandlerFunc {
	return func(c *gin.Context) {
		if c.Request.Method == http.MethodGet {
			c.Next()
			return
		}

		val, err := rdr.Get(c.Request.Context(), BackpressureFlagKey)
		if err != nil || val == "" {
			// Key absent (redis.Nil) or Redis error → fail-open.
			c.Next()
			return
		}

		// Backpressure engaged for write requests.
		c.Header("Retry-After", "10")
		aperrors.Respond(c, aperrors.CodeTooEarly, "backpressure: predict.request queue is full, retry in 10 s")
		c.Abort()
	}
}

// StatusClientClosedRequest is the non-standard 499 status code used by nginx
// to signal that the client closed the connection before the server finished
// responding. We use it here for the same semantic.
const StatusClientClosedRequest = 499

// SlowClientAbort returns a Gin middleware that detects client disconnect
// during response writing and aborts the handler chain with status 499.
//
// Mechanism:
//   - Spawns a goroutine that waits on req.Context().Done() OR a write-
//     timeout timer (writeTimeout duration).
//   - If the context is cancelled (client disconnect / server-side deadline)
//     before the handler returns, the middleware sets ContextKeyErrorCode to
//     "client_disconnected" on the Gin context and calls c.Abort() with 499.
//   - If the handler completes normally, the goroutine is stopped via a
//     cancellable context and no action is taken.
//
// The http.Server WriteTimeout (HTTP_WRITE_TIMEOUT_SEC) is the hard OS-level
// cutoff; this middleware records the semantic error code so the access log
// captures the disconnect event (status=499, error_code=client_disconnected).
//
// DoS note: without this middleware a goroutine blocked on a slow client's
// TCP send buffer holds a connection open until HTTP_WRITE_TIMEOUT_SEC, which
// defaults to 30 s. With this middleware the handler is aborted at
// writeTimeout (default 5 s), freeing server resources sooner.
//
// Placement: register BEFORE route handlers, AFTER TraceParent and RequestID
// so the access log middleware that runs after c.Next() captures the 499.
func SlowClientAbort(writeTimeout time.Duration) gin.HandlerFunc {
	return func(c *gin.Context) {
		// watchCtx is cancelled when this middleware function returns
		// (i.e. when the handler chain is done), stopping the goroutine.
		watchCtx, stopWatch := context.WithCancel(context.Background())
		defer stopWatch()

		done := make(chan struct{})
		go func() {
			defer close(done)
			select {
			case <-watchCtx.Done():
				// Handler finished normally — nothing to do.
				return
			case <-c.Request.Context().Done():
				// Client disconnected or server-side deadline exceeded.
				c.Set(ContextKeyErrorCode, "client_disconnected")
				c.AbortWithStatus(StatusClientClosedRequest)
			case <-time.After(writeTimeout):
				// Write timeout elapsed — treat as slow-client disconnect.
				c.Set(ContextKeyErrorCode, "client_disconnected")
				c.AbortWithStatus(StatusClientClosedRequest)
			}
		}()

		c.Next()
		stopWatch() // signal the goroutine we are done
		<-done      // wait for the goroutine to exit before returning
	}
}
