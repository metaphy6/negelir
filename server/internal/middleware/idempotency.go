package middleware

// idempotency.go — Phase 9 §9.3 Idempotency-Key cache.
//
// Redis key scheme:
//   idem:<sha256(subjectID|method|path|Idempotency-Key-header)>
//     -> idemEntry JSON {status, content_type, body_b64, req_body_sha256,
//                       request_id, expires_at}
//     TTL = cfg.api_idempotency_ttl_s (default 86400 s)
//
// Inflight (request in-flight, no stored response yet):
//   idem:*:inflight  -> SET NX sentinel (TTL = 2x inflightWait)
//   idem:*:wait      -> Redis pubsub channel; notified on completion
//
// Proof tests (all in idempotency_test.go):
//   (a) double-POST returns identical bytes (203 X-Replayed: true)
//   (b) same Idempotency-Key + different body -> 409 drift + alert
//   (c) inflight request -> second caller -> 425 too_early
//   (d) PurgeStaleIdemWaiters at boot removes orphaned inflight keys

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
)

// ContextKeySubjectID is the Gin context key that holds the authenticated
// user ID (set by the JWT verification middleware after token validation).
// Anonymous requests leave this key absent; idempotency falls back to the
// rate-subject (IP-based) key in that case.
const ContextKeySubjectID = "auth.subject_id"

// IdempotencyStore is the minimal Redis interface required by Idempotency.
type IdempotencyStore interface {
	// Get returns the stored value for key, or ("", nil/ErrMiss) on miss.
	Get(ctx context.Context, key string) (string, error)
	// Set stores key -> value with TTL. Overwrites any existing entry.
	Set(ctx context.Context, key, value string, ttl time.Duration) error
	// SetNX stores key -> value with TTL only if the key is absent.
	// Returns true if the key was newly set; false if it already existed.
	SetNX(ctx context.Context, key, value string, ttl time.Duration) (bool, error)
	// Del removes the key. Must not error on a missing key.
	Del(ctx context.Context, key string) error
	// Subscribe returns a channel delivering messages published to channel
	// and a cleanup function that must be called to release resources.
	Subscribe(ctx context.Context, channel string) (<-chan string, func(), error)
	// Publish sends message to all subscribers on channel.
	Publish(ctx context.Context, channel, message string) error
	// ScanKeys returns all keys matching the glob pattern. Used by boot cleanup.
	ScanKeys(ctx context.Context, pattern string) ([]string, error)
}

// IdempotencyAlertFunc is called when the same Idempotency-Key is replayed
// with a different request body. kind is "idempotency_drift"; severity "warn".
type IdempotencyAlertFunc func(ctx context.Context, kind, severity string)

// idemEntry is the JSON value stored in Redis for a completed idempotent
// request. All fields are persisted so the replay is byte-for-byte faithful.
type idemEntry struct {
	Status      int    `json:"status"`
	ContentType string `json:"content_type"`
	BodyB64     string `json:"body_b64"`        // base64(response body bytes)
	ReqBodySHA  string `json:"req_body_sha256"` // hex(sha256(request body))
	RequestID   string `json:"request_id"`
	ExpiresAt   int64  `json:"expires_at"` // unix seconds; informational only
}

// idemRedisKey returns the primary Redis lookup key for an idempotent request.
// Formula: idem:<hex(sha256(subjectID+"|"+method+"|"+path+"|"+idemHeader))>
func idemRedisKey(subjectID, method, path, idemHeader string) string {
	h := sha256.New()
	h.Write([]byte(subjectID))
	h.Write([]byte("|"))
	h.Write([]byte(method))
	h.Write([]byte("|"))
	h.Write([]byte(path))
	h.Write([]byte("|"))
	h.Write([]byte(idemHeader))
	return "idem:" + hex.EncodeToString(h.Sum(nil))
}

func idemInflightKey(key string) string { return key + ":inflight" }
func idemWaitChan(key string) string    { return key + ":wait" }

// bodyCapturingWriter wraps gin.ResponseWriter and tees all Write calls into
// an internal buffer so the middleware can store the response after c.Next().
type bodyCapturingWriter struct {
	gin.ResponseWriter
	buf *bytes.Buffer
}

func (w *bodyCapturingWriter) Write(b []byte) (int, error) {
	w.buf.Write(b)
	return w.ResponseWriter.Write(b)
}

func (w *bodyCapturingWriter) WriteString(s string) (int, error) {
	return w.Write([]byte(s))
}

// Idempotency returns a Gin middleware implementing the Phase 9 §9.3
// idempotency-key cache.
//
// Only requests carrying an Idempotency-Key header are processed; all
// others fall through without touching Redis.
//
// Parameters:
//   - store        -- Redis-backed IdempotencyStore
//   - ttl          -- response cache duration (cfg.api_idempotency_ttl_s)
//   - inflightWait -- max block time before 425 (cfg.api_idempotency_inflight_wait_ms)
//   - alertFn      -- sec.alert.v1 publisher; may be nil in tests
func Idempotency(
	store IdempotencyStore,
	ttl time.Duration,
	inflightWait time.Duration,
	alertFn IdempotencyAlertFunc,
) gin.HandlerFunc {
	return func(c *gin.Context) {
		idemHeader := c.GetHeader("Idempotency-Key")
		if idemHeader == "" {
			c.Next()
			return
		}

		// Derive subject: authenticated user ID, or fall back to IP subject.
		subjectID := c.GetString(ContextKeySubjectID)
		if subjectID == "" {
			subjectID = c.GetString(ContextKeyRateSubject)
		}

		// Buffer the request body to (a) compute its hash for drift detection
		// and (b) restore it for downstream handlers.
		var rawBody []byte
		if c.Request.Body != nil {
			rawBody, _ = io.ReadAll(c.Request.Body)
			c.Request.Body = io.NopCloser(bytes.NewReader(rawBody))
		}
		reqBodyHashArr := sha256.Sum256(rawBody)
		reqBodySHA := hex.EncodeToString(reqBodyHashArr[:])

		key := idemRedisKey(subjectID, c.Request.Method, c.FullPath(), idemHeader)
		inflightKey := idemInflightKey(key)
		waitChan := idemWaitChan(key)
		ctx := c.Request.Context()

		// -- 1. Check for a stored response ---------------------------------
		raw, err := store.Get(ctx, key)
		if err == nil && raw != "" {
			var entry idemEntry
			if jsonErr := json.Unmarshal([]byte(raw), &entry); jsonErr == nil {
				if entry.ReqBodySHA != reqBodySHA {
					// Same Idempotency-Key, different request body -> drift.
					if alertFn != nil {
						alertFn(ctx, "idempotency_drift", "warn")
					}
					c.AbortWithStatusJSON(http.StatusConflict, gin.H{
						"error": "idempotency_key_replay_with_different_body",
					})
					return
				}
				// Body matches -> replay the stored response.
				body, decErr := base64.StdEncoding.DecodeString(entry.BodyB64)
				if decErr == nil {
					c.Header("X-Replayed", "true")
					c.Data(http.StatusNonAuthoritativeInfo, entry.ContentType, body)
					c.Abort()
					return
				}
			}
		}

		// -- 2. Check / acquire inflight lock --------------------------------
		// Inflight sentinel TTL: 2x inflightWait, minimum 5 s.
		inflightTTL := 2 * inflightWait
		if inflightTTL < 5*time.Second {
			inflightTTL = 5 * time.Second
		}
		acquired, setnxErr := store.SetNX(ctx, inflightKey, "1", inflightTTL)
		if setnxErr == nil && !acquired {
			// Another request is processing this key -> subscribe and wait.
			msgCh, cleanup, subErr := store.Subscribe(ctx, waitChan)
			if subErr == nil {
				defer cleanup()
				select {
				case <-msgCh:
					// Inflight completed; re-check the store for the now-stored
					// response and replay it if present (§9.14 inflight-blocks-
					// then-returns contract).
					if raw2, err2 := store.Get(ctx, key); err2 == nil && raw2 != "" {
						var entry2 idemEntry
						if jsonErr2 := json.Unmarshal([]byte(raw2), &entry2); jsonErr2 == nil && entry2.ReqBodySHA == reqBodySHA {
							body2, decErr2 := base64.StdEncoding.DecodeString(entry2.BodyB64)
							if decErr2 == nil {
								c.Header("X-Replayed", "true")
								c.Data(http.StatusNonAuthoritativeInfo, entry2.ContentType, body2)
								c.Abort()
								return
							}
						}
					}
					// Stored response not available (race or error); fall through to 425.
				case <-time.After(inflightWait):
					// Wait budget exhausted.
				}
			}
			c.AbortWithStatusJSON(http.StatusTooEarly, gin.H{
				"error": "too_early",
			})
			return
		}

		// -- 3. Run the downstream handler, capturing the response body ------
		bw := &bodyCapturingWriter{ResponseWriter: c.Writer, buf: new(bytes.Buffer)}
		c.Writer = bw

		c.Next()

		// -- 4. Store the completed response and release the inflight lock ---
		if bw.Written() {
			entry := idemEntry{
				Status:      bw.Status(),
				ContentType: bw.Header().Get("Content-Type"),
				BodyB64:     base64.StdEncoding.EncodeToString(bw.buf.Bytes()),
				ReqBodySHA:  reqBodySHA,
				RequestID:   c.GetString(ContextKeyRequestID),
				ExpiresAt:   time.Now().Add(ttl).Unix(),
			}
			if data, jerr := json.Marshal(entry); jerr == nil {
				store.Set(ctx, key, string(data), ttl) //nolint:errcheck
			}
		}
		// Release inflight lock and wake any waiting callers.
		store.Del(ctx, inflightKey)       //nolint:errcheck
		store.Publish(ctx, waitChan, "1") //nolint:errcheck
	}
}

// PurgeStaleIdemWaiters scans for orphaned idem:*:inflight keys left by
// prior pod crashes and deletes them so no goroutine blocks on a stale
// sentinel. Call once at boot before the HTTP listener opens.
func PurgeStaleIdemWaiters(ctx context.Context, store IdempotencyStore) error {
	keys, err := store.ScanKeys(ctx, "idem:*:inflight")
	if err != nil {
		return err
	}
	for _, k := range keys {
		if delErr := store.Del(ctx, k); delErr != nil {
			return delErr
		}
	}
	return nil
}
