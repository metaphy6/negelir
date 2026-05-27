package middleware

import (
	"net"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/metaphy6/negelir/server/internal/sec"
)

func init() { gin.SetMode(gin.TestMode) }

// newXFFRouter builds a minimal test router that applies the XFF
// middleware and exposes a /probe endpoint that echoes the derived
// rate-subject back to the caller.
func newXFFRouter(trusted *sec.TrustedProxies, ipv4P, ipv6P int) *gin.Engine {
	r := gin.New()
	r.Use(XFF(trusted, ipv4P, ipv6P))
	r.GET("/probe", func(c *gin.Context) {
		subject, _ := c.Get(ContextKeyRateSubject)
		c.String(http.StatusOK, "%v", subject)
	})
	return r
}

// TestXFFSpoofedPrefixIgnoredNoTrusted — when no trusted proxies are
// configured the TCP peer address always wins; an attacker-supplied
// X-Forwarded-For is completely ignored.
func TestXFFSpoofedPrefixIgnoredNoTrusted(t *testing.T) {
	tp, _ := sec.ParseTrustedProxies("") // empty = no trusted proxies
	r := newXFFRouter(tp, 32, 64)

	req := httptest.NewRequest(http.MethodGet, "/probe", nil)
	// Attacker injects a spoofed XFF entry hoping to claim a different IP.
	req.Header.Set("X-Forwarded-For", "1.2.3.4")
	req.RemoteAddr = "192.0.2.99:1234" // actual TCP peer
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	got := w.Body.String()
	// With no trusted proxies the TCP peer (192.0.2.99/32) must win.
	if got != "192.0.2.99/32" {
		t.Fatalf("spoofed XFF must be ignored; expected 192.0.2.99/32, got %q", got)
	}
}

// TestXFFTrustedHopSkippedSpoofedEntryIgnored — boundary test per
// §9.6 spec: with a trusted CIDR the right-most untrusted hop wins;
// any addresses to the left of that (potentially attacker-controlled)
// are ignored.
func TestXFFTrustedHopSkippedSpoofedEntryIgnored(t *testing.T) {
	tp, _ := sec.ParseTrustedProxies("10.0.0.0/8")
	r := newXFFRouter(tp, 32, 64)

	req := httptest.NewRequest(http.MethodGet, "/probe", nil)
	// XFF: spoofed, real_client, trusted_lb (right-most = trusted_lb is skipped).
	req.Header.Set("X-Forwarded-For", "203.0.113.99, 203.0.113.42, 10.0.0.1")
	req.RemoteAddr = "10.0.0.1:4567" // TCP peer is the load balancer
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	got := w.Body.String()
	// real_client = 203.0.113.42 — first untrusted hop walking right-to-left.
	if got != "203.0.113.42/32" {
		t.Fatalf("expected right-most untrusted 203.0.113.42/32, got %q", got)
	}
}

// TestXFFSubjectKeyStored — the ContextKeyRateSubject key must be present
// and its value must be a non-empty string after the middleware runs.
func TestXFFSubjectKeyStored(t *testing.T) {
	tp, _ := sec.ParseTrustedProxies("")
	r := newXFFRouter(tp, 32, 64)

	req := httptest.NewRequest(http.MethodGet, "/probe", nil)
	req.RemoteAddr = "198.51.100.7:9999"
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Body.String() == "" || w.Body.String() == "<nil>" {
		t.Fatalf("rate subject must be non-empty, got %q", w.Body.String())
	}
}

// TestXFFClientIPStored — the ContextKeyClientIP value must be a valid
// net.IP (not nil).
func TestXFFClientIPStored(t *testing.T) {
	tp, _ := sec.ParseTrustedProxies("")
	r := gin.New()
	r.Use(XFF(tp, 32, 64))
	r.GET("/probe", func(c *gin.Context) {
		v, _ := c.Get(ContextKeyClientIP)
		ip, ok := v.(net.IP)
		if !ok || ip == nil {
			c.String(http.StatusInternalServerError, "no ip")
			return
		}
		c.String(http.StatusOK, ip.String())
	})

	req := httptest.NewRequest(http.MethodGet, "/probe", nil)
	req.RemoteAddr = "203.0.113.5:1234"
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", w.Code, w.Body.String())
	}
	if w.Body.String() != "203.0.113.5" {
		t.Fatalf("expected 203.0.113.5, got %q", w.Body.String())
	}
}

// TestXFFSpoofedUntrustedIgnored — §9.14 proof test.
// When trusted proxies are configured but the TCP peer is NOT inside
// the trusted CIDR, the XFF header is entirely attacker-controlled and
// must be ignored. The subject_key must be derived from the actual TCP
// peer address, not from the spoofed X-Forwarded-For value.
func TestXFFSpoofedUntrustedIgnored(t *testing.T) {
	// Trusted proxies: only 10.0.0.0/8 is trusted (e.g. internal load balancers).
	tp, _ := sec.ParseTrustedProxies("10.0.0.0/8")
	r := newXFFRouter(tp, 32, 64)

	req := httptest.NewRequest(http.MethodGet, "/probe", nil)
	// Attacker (203.0.113.5) is not inside 10.0.0.0/8 — it is a direct,
	// untrusted peer. It injects a spoofed XFF hoping to claim a different
	// rate-limit bucket.
	req.Header.Set("X-Forwarded-For", "1.2.3.4")
	req.RemoteAddr = "203.0.113.5:4321"
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	got := w.Body.String()
	// subject_key must be derived from the actual TCP peer (203.0.113.5/32),
	// NOT from the spoofed XFF value (1.2.3.4/32).
	if got != "203.0.113.5/32" {
		t.Fatalf("untrusted peer XFF must be ignored; expected 203.0.113.5/32, got %q", got)
	}
}
