package auth

// oidc.go — Phase 9 §9.2 OIDC plug-point (interface + NoopProvider)
//
// This file wires the Provider interface contract only. No real provider
// (Google, MS, GH, or any other identity IdP) is bundled in this phase.
// Doctrine: "no external secret-manager dep" extends to identity providers
// in v1 (see §9.2 — Forbidden in this phase).
//
// Future phases register a concrete provider by implementing Provider and
// returning it from LoadProvider when the OIDC_* env vars are present.

import (
	"errors"
	"os"
)

// ErrNotConfigured is returned by NoopProvider on every call.
// API handlers MUST treat this as "OIDC disabled" (return 501 Not Implemented
// or 403 Forbidden depending on context; never 500 — it is an expected state).
var ErrNotConfigured = errors.New("not_configured")

// TokenResponse is the minimal token-endpoint payload the Provider contract
// requires.  All fields are opaque strings; consumers MUST NOT assume structure
// beyond what is needed to pass them to Userinfo / IDTokenClaims.
type TokenResponse struct {
	IDToken      string
	AccessToken  string
	RefreshToken string
	ExpiresIn    int // seconds
}

// Provider is the OIDC plug-point interface.
//
// The four methods mirror the standard OIDC Authorization-Code flow:
//
//	Discover       — fetch and cache the provider's /.well-known/openid-configuration
//	Exchange(code) — swap an authorization code for a TokenResponse
//	Userinfo(tok)  — fetch claims from the userinfo endpoint
//	IDTokenClaims  — parse and verify the raw ID-token JWT, return its claims
//
// All implementations MUST be safe for concurrent use.
type Provider interface {
	Discover() error
	Exchange(code string) (*TokenResponse, error)
	Userinfo(accessToken string) (map[string]any, error)
	IDTokenClaims(rawIDToken string) (map[string]any, error)
}

// NoopProvider is the default Provider used when no OIDC_* env vars are set.
// Every method returns ErrNotConfigured; no network calls are ever made.
type NoopProvider struct{}

func (NoopProvider) Discover() error                                { return ErrNotConfigured }
func (NoopProvider) Exchange(_ string) (*TokenResponse, error)     { return nil, ErrNotConfigured }
func (NoopProvider) Userinfo(_ string) (map[string]any, error)     { return nil, ErrNotConfigured }
func (NoopProvider) IDTokenClaims(_ string) (map[string]any, error) { return nil, ErrNotConfigured }

// oidcEnvKeys lists the env-var names whose presence signals that an operator
// intends to configure an OIDC provider. Absence of ALL of them → noop path.
var oidcEnvKeys = []string{
	"OIDC_ISSUER",
	"OIDC_CLIENT_ID",
	"OIDC_CLIENT_SECRET",
}

// oidcEnvPresent returns true if at least one OIDC_* env var is non-empty.
func oidcEnvPresent() bool {
	for _, key := range oidcEnvKeys {
		if os.Getenv(key) != "" {
			return true
		}
	}
	return false
}

// LoadProvider returns a Provider based on the OIDC_* environment variables.
//
// Phase 9 always returns NoopProvider — no concrete provider is bundled.
// When OIDC_* vars are absent this is the expected noop path.
// When OIDC_* vars are present the operator is signalling future provider
// intent; NoopProvider is still returned until a Phase 20+ provider is
// registered. API handlers that call LoadProvider().Discover() will get
// ErrNotConfigured and should surface a clear 501 response.
func LoadProvider() Provider {
	_ = oidcEnvPresent() // consumed by future phases; currently no concrete path
	return NoopProvider{}
}

// ErrRedirectNotAllowed is returned by ValidateRedirectURI when the supplied
// URI is not an exact match for any entry in the configured allowlist.
// API handlers must return 400 Bad Request on this error.
//
// Open-redirect defense: this error is distinct from ErrNotConfigured so that
// callers can differentiate "OIDC disabled" from "bad redirect_uri".
var ErrRedirectNotAllowed = errors.New("redirect_not_allowed")

// ValidateRedirectURI returns nil when uri is an exact match for one of the
// entries in allowlist, or ErrRedirectNotAllowed otherwise.
//
// Security contract (§9.2 open-redirect prevention):
//   - An empty allowlist rejects every URI — this is the safe default.
//     Operators must explicitly populate the allowlist from config
//     (future: NEGELIR_OIDC_REDIRECT_ALLOWLIST).
//   - Matching is exact (byte-for-byte): partial matches, prefix matches, and
//     URIs with extra query parameters are all rejected.
//   - This check MUST run before any OIDC provider interaction so that the
//     security posture is identical whether the provider is NoopProvider or
//     a real IdP.
func ValidateRedirectURI(uri string, allowlist []string) error {
	for _, allowed := range allowlist {
		if uri == allowed {
			return nil
		}
	}
	return ErrRedirectNotAllowed
}
