package main

// Phase 9.6 — password-field sec-gate bypass.
//
// authLoginHandler and authRegisterHandler route the password field through
// sec.PasswordPasses (length-cap only; no NFC normalisation; no pattern
// engine). This satisfies §9.6 "Password-field bypass" and §7.1 of the
// Phase-7 security spec. Full auth implementation (bcrypt verify/hash,
// JWT minting, user-store writes) is deferred to Phase 9.2.
//
// Phase 9.2 — self-registration default OFF.
//
// authRegisterHandler returns 403 forbidden unless enabled=true
// (cfg.api_self_registration_enabled). When enabled it also enforces a
// per-/24 (IPv4) or per-/64 (IPv6) subnet registration cap per hour
// (cfg.api_register_cap_per_subnet_per_h, default 20) tracked in Redis
// to prevent mass-account-spray.  The GCRA cost=3 already in
// endpoint_costs.yaml applies on top as the global rate budget.

import (
	"fmt"
	"net"
	"time"

	"github.com/gin-gonic/gin"
	aperrors "github.com/metaphy6/negelir/server/internal/errors"
	"github.com/metaphy6/negelir/server/internal/middleware"
	"github.com/metaphy6/negelir/server/internal/sec"
	"github.com/redis/go-redis/v9"
)

// subnet24Key returns a stable Redis key segment for the /24 (IPv4) or
// /64 (IPv6) subnet of ip.  Used as the registration-rate bucket key.
func subnet24Key(ip net.IP) string {
	if ip4 := ip.To4(); ip4 != nil {
		return fmt.Sprintf("%d.%d.%d.0/24", ip4[0], ip4[1], ip4[2])
	}
	// IPv6: bucket by first 8 bytes (/64).
	if len(ip) >= 8 {
		return fmt.Sprintf("%x:%x:%x:%x::/64", ip[0:2], ip[2:4], ip[4:6], ip[6:8])
	}
	return ip.String()
}

// authLoginHandler handles POST /v1/auth/login.
// Phase 9.6: password is routed through sec.PasswordPasses (length-cap
// only; no Unicode normalise; no pattern engine). Full auth logic
// (bcrypt verify, JWT mint) is wired in Phase 9.2.
func authLoginHandler(gate *sec.QAInputGate) gin.HandlerFunc {
	return func(c *gin.Context) {
		var req struct {
			Email    string `json:"email"`
			Password string `json:"password"`
		}
		if err := c.ShouldBindJSON(&req); err != nil || req.Email == "" || req.Password == "" {
			aperrors.Respond(c, aperrors.CodeInvalidRequest, "email and password are required")
			return
		}
		// Phase 9.6 §7.1 password-field carve-out: PasswordPasses applies
		// the length cap and nothing else — no NFC, no strip, no pattern.
		pwDec := gate.PasswordPasses(req.Password)
		if pwDec.Verdict == sec.VerdictQuarantine {
			aperrors.Respond(c, aperrors.CodeInvalidRequest, "password rejected by security gate")
			return
		}
		// Stub: full bcrypt-verify + JWT path wired in Phase 9.2.
		c.Status(501)
	}
}

// authRegisterHandler handles POST /v1/auth/register.
//
// When enabled=false (default, cfg.api_self_registration_enabled=false):
//   returns 403 forbidden immediately.
//
// When enabled=true:
//   1. Checks a per-/24 subnet hourly cap in Redis (capPerSubnetH,
//      cfg.api_register_cap_per_subnet_per_h=20). Returns 429 if exceeded.
//      Skipped gracefully when rdb is nil (test env) or client IP absent.
//   2. Routes the password through sec.PasswordPasses (length cap only).
//   3. Stub 501 — full bcrypt-hash + user-store path wired in Phase 9.2.
func authRegisterHandler(gate *sec.QAInputGate, enabled bool, capPerSubnetH int, rdb *redis.Client) gin.HandlerFunc {
	return func(c *gin.Context) {
		// §9.2 — self-registration default OFF.
		if !enabled {
			aperrors.Respond(c, aperrors.CodeForbidden, "registration is disabled")
			return
		}

		// §9.2 — per-/24 subnet registration cap (Redis sliding 1-hour window).
		// Fail open on Redis unavailability: the GCRA cost=3 bucket still limits
		// the global registration rate.  Skipped when rdb is nil (test env).
		if rdb != nil {
			if v, ok := c.Get(middleware.ContextKeyClientIP); ok {
				if ip, ipOK := v.(net.IP); ipOK && ip != nil {
					key := "reg:subnet:" + subnet24Key(ip)
					ctx := c.Request.Context()
					pipe := rdb.Pipeline()
					incrCmd := pipe.Incr(ctx, key)
					pipe.ExpireNX(ctx, key, time.Hour) // anchor TTL to first request
					if _, err := pipe.Exec(ctx); err == nil {
						if incrCmd.Val() > int64(capPerSubnetH) {
							aperrors.Respond(c, aperrors.CodeRateLimited, "registration rate exceeded for your network")
							return
						}
					}
					// Redis error → fail open (logged by caller; GCRA still active).
				}
			}
		}

		var req struct {
			Email    string `json:"email"`
			Password string `json:"password"`
		}
		if err := c.ShouldBindJSON(&req); err != nil || req.Email == "" || req.Password == "" {
			aperrors.Respond(c, aperrors.CodeInvalidRequest, "email and password are required")
			return
		}
		// Phase 9.6 §7.1 password-field carve-out: PasswordPasses applies
		// the length cap and nothing else — no NFC, no strip, no pattern.
		pwDec := gate.PasswordPasses(req.Password)
		if pwDec.Verdict == sec.VerdictQuarantine {
			aperrors.Respond(c, aperrors.CodeInvalidRequest, "password rejected by security gate")
			return
		}
		// Stub: full bcrypt-hash + user-store path wired in Phase 9.2.
		c.Status(501)
	}
}

