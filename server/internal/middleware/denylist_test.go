package middleware

import (
	"context"
	"errors"
	"net"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
)

// stubDenylistReader implements DenylistReader for unit tests.
type stubDenylistReader struct {
	val string
	err error
}

func (s *stubDenylistReader) Get(_ context.Context, _ string) (string, error) {
	return s.val, s.err
}

func newDenylistRouter(rdr DenylistReader) *gin.Engine {
	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set(ContextKeyRateSubject, "10.0.0.1/32")
	})
	r.Use(DenylistCheck(rdr))
	r.GET("/v1/qa", func(c *gin.Context) { c.Status(http.StatusOK) })
	return r
}

// TestDenylistShortCircuit_Returns429EmptyBody verifies that a denylisted
// subject receives a 429 with no body.
func TestDenylistShortCircuit_Returns429EmptyBody(t *testing.T) {
	r := newDenylistRouter(&stubDenylistReader{val: "reason=automated_burst", err: nil})

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/v1/qa", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusTooManyRequests {
		t.Fatalf("expected 429, got %d", w.Code)
	}
	if body := w.Body.String(); body != "" {
		t.Fatalf("expected empty body for denylisted response, got: %q", body)
	}
}

// TestDenylistShortCircuit_AuditFlagSet verifies that ContextKeyDenylisted
// is set to true when the subject is in the denylist, so the audit emitter
// can include `denylisted: true` in the api.request.v1 row.
//
// The AuditEmitter is registered BEFORE DenylistCheck in the real chain and
// reads the flag AFTER c.Next() returns (post-handler pattern). This test
// mirrors that setup: the spy middleware calls c.Next() then reads the flag
// on its way back up, which is how Gin delivers post-handler context to
// earlier-registered middleware even when a later middleware calls Abort().
func TestDenylistShortCircuit_AuditFlagSet(t *testing.T) {
	var capturedFlag interface{}

	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set(ContextKeyRateSubject, "10.0.0.2/32")
	})
	// Simulated AuditEmitter: registered before DenylistCheck, reads flag after Next().
	r.Use(func(c *gin.Context) {
		c.Next() // runs DenylistCheck (and triggers Abort)
		capturedFlag, _ = c.Get(ContextKeyDenylisted)
	})
	r.Use(DenylistCheck(&stubDenylistReader{val: "reason=operator_override"}))
	r.GET("/v1/qa", func(c *gin.Context) { c.Status(http.StatusOK) })

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/v1/qa", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusTooManyRequests {
		t.Fatalf("expected 429, got %d", w.Code)
	}
	flagVal, ok := capturedFlag.(bool)
	if !ok || !flagVal {
		t.Fatalf("ContextKeyDenylisted must be true after denylist hit; got: %v", capturedFlag)
	}
}

// TestDenylistShortCircuit_MissPassesThrough verifies that a subject absent
// from the denylist (redis.Nil / empty value) passes through to the handler.
func TestDenylistShortCircuit_MissPassesThrough(t *testing.T) {
	r := newDenylistRouter(&stubDenylistReader{val: "", err: errors.New("redis: nil")})

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/v1/qa", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("denylist miss: expected 200 (pass-through), got %d", w.Code)
	}
}

// TestDenylistShortCircuit_RedisErrorFailsOpen verifies that a Redis error
// is fail-open: the request passes through rather than being blocked.
func TestDenylistShortCircuit_RedisErrorFailsOpen(t *testing.T) {
	r := newDenylistRouter(&stubDenylistReader{val: "", err: errors.New("redis: connection refused")})

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/v1/qa", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("redis error: expected fail-open (200), got %d", w.Code)
	}
}

// TestDenylistShortCircuit_UsesRateSubjectFromContext verifies the Redis key
// is built from ContextKeyRateSubject, not c.RemoteIP().
func TestDenylistShortCircuit_UsesRateSubjectFromContext(t *testing.T) {
	var capturedKey string
	spyRdr := &spyDenylistReader{}

	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set(ContextKeyRateSubject, "203.0.113.7/32")
	})
	r.Use(DenylistCheck(spyRdr))
	r.GET("/v1/qa", func(c *gin.Context) { c.Status(http.StatusOK) })

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/v1/qa", nil)
	r.ServeHTTP(w, req)

	capturedKey = spyRdr.lastKey
	want := DenylistKeyPrefix + "203.0.113.7/32"
	if capturedKey != want {
		t.Fatalf("expected Redis key %q, got %q", want, capturedKey)
	}
}

// spyDenylistReader records the key argument from each Get call.
type spyDenylistReader struct {
	lastKey string
}

func (s *spyDenylistReader) Get(_ context.Context, key string) (string, error) {
	s.lastKey = key
	return "", errors.New("redis: nil")
}

// ── SubnetModeEscape ─────────────────────────────────────────────────────────

// toggleCappedReader is a DenylistReader stub whose capped flag can be flipped
// between requests to simulate the sec:denylist:capped Redis key being set.
type toggleCappedReader struct {
	capped bool
}

func (t *toggleCappedReader) Get(_ context.Context, key string) (string, error) {
	if key == DenylistCappedKey && t.capped {
		return "1", nil
	}
	return "", errors.New("redis: nil")
}

// TestSubnetModeOnCappedFlag is the §9.7 proof test: flip the cap flag
// mid-test; assert subsequent requests bucket on the /24 subnet key and
// carry X-RateLimit-Mode: subnet.
func TestSubnetModeOnCappedFlag(t *testing.T) {
	gin.SetMode(gin.TestMode)

	rdr := &toggleCappedReader{}
	var capturedSubject string

	r := gin.New()
	// Simulate XFF middleware: set raw client IP and full /32 subject key.
	r.Use(func(c *gin.Context) {
		c.Set(ContextKeyClientIP, net.IP{192, 168, 1, 123})
		c.Set(ContextKeyRateSubject, "192.168.1.123/32")
	})
	r.Use(SubnetModeEscape(rdr))
	r.GET("/v1/qa", func(c *gin.Context) {
		subj, _ := c.Get(ContextKeyRateSubject)
		capturedSubject, _ = subj.(string)
		c.Status(http.StatusOK)
	})

	// ── Request 1: cap flag NOT set ──────────────────────────────────────────
	w1 := httptest.NewRecorder()
	r.ServeHTTP(w1, httptest.NewRequest(http.MethodGet, "/v1/qa", nil))
	if w1.Code != http.StatusOK {
		t.Fatalf("request 1: expected 200, got %d", w1.Code)
	}
	if capturedSubject != "192.168.1.123/32" {
		t.Fatalf("request 1 (uncapped): want full subject %q, got %q", "192.168.1.123/32", capturedSubject)
	}
	if mode := w1.Header().Get("X-RateLimit-Mode"); mode != "" {
		t.Fatalf("request 1 (uncapped): expected no X-RateLimit-Mode header, got %q", mode)
	}

	// Flip the cap flag — simulates operator setting sec:denylist:capped in Redis.
	rdr.capped = true

	// ── Request 2: cap flag IS set ───────────────────────────────────────────
	w2 := httptest.NewRecorder()
	r.ServeHTTP(w2, httptest.NewRequest(http.MethodGet, "/v1/qa", nil))
	if w2.Code != http.StatusOK {
		t.Fatalf("request 2: expected 200, got %d", w2.Code)
	}
	const wantSubnet = "192.168.1.0/24"
	if capturedSubject != wantSubnet {
		t.Fatalf("request 2 (capped): want subnet subject %q, got %q", wantSubnet, capturedSubject)
	}
	if mode := w2.Header().Get("X-RateLimit-Mode"); mode != "subnet" {
		t.Fatalf("request 2 (capped): expected X-RateLimit-Mode: subnet, got %q", mode)
	}
}
