package middleware

import (
	"github.com/gin-gonic/gin"
	"github.com/metaphy6/negelir/server/internal/sec"
)

// ContextKeyRateSubject is the Gin context key under which the per-IP
// rate-bucket subject (from sec.SubjectKey) is stored for downstream
// middleware (rate-limiter, audit emitter).
const ContextKeyRateSubject = "sec.rate_subject"

// ContextKeyClientIP is the Gin context key under which the derived
// net.IP is stored for downstream middleware that needs the raw address.
const ContextKeyClientIP = "sec.client_ip"

// XFF returns a Gin middleware that derives the real client IP from the
// X-Forwarded-For header (respecting the trusted-proxy CIDR list) and
// stores:
//   - the derived net.IP under ContextKeyClientIP
//   - the SubjectKey string (e.g. "203.0.113.7/32") under ContextKeyRateSubject
//
// Phase 9.6 XFF derivation contract:
//   - cfg.api_trusted_proxies parsed once at boot via sec.ParseTrustedProxies
//   - sec.DeriveClientIP(xff, peer, trusted) per request
//   - sec.SubjectKey(ip, ipv4Prefix, ipv6Prefix) for the per-IP rate bucket
//
// Defense: an attacker can only influence the right-most untrusted hop
// of X-Forwarded-For; prepended spoofed entries are unreachable because
// the walk stops at the first non-trusted address.
func XFF(trusted *sec.TrustedProxies, ipv4Prefix, ipv6Prefix int) gin.HandlerFunc {
	return func(c *gin.Context) {
		xff := c.GetHeader("X-Forwarded-For")
		peer := c.RemoteIP()

		ip := sec.DeriveClientIP(xff, peer, trusted)
		subject := sec.SubjectKey(ip, ipv4Prefix, ipv6Prefix)

		c.Set(ContextKeyClientIP, ip)
		c.Set(ContextKeyRateSubject, subject)

		c.Next()
	}
}
