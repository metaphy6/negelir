package auth_test

// oidc_adversarial_test.go — §9.14 adversarial OIDC proof test.
//
// TestAdvOpenRedirectInOIDCCallback — adv_test_open_redirect_in_oidc_callback.
//
// Phase 12 prerequisite; must be green at Phase 9 close.

import (
	"net/http"
	"net/http/httptest"
	"net/url"
	"testing"

	"github.com/gin-gonic/gin"

	"github.com/metaphy6/negelir/server/internal/auth"
)

// TestAdvOpenRedirectInOIDCCallback — adv_test_open_redirect_in_oidc_callback.
//
// The OIDC callback handler must validate redirect_uri against the configured
// allowlist BEFORE any interaction with the OIDC provider. A redirect_uri that
// is not in the allowlist must be rejected with 400 Bad Request.
//
// This holds even when the configured provider is auth.NoopProvider (Phase 9
// default — no real IdP is bundled), proving that the parameter validator is
// not gated on provider availability.
func TestAdvOpenRedirectInOIDCCallback(t *testing.T) {
	gin.SetMode(gin.TestMode)

	allowlist := []string{
		"https://negelir.com/auth/callback",
		"http://localhost:8080/auth/callback",
	}

	// Inline handler that mirrors the OIDC callback contract:
	// validate redirect_uri first, then (no-op) interact with the provider.
	// This is the pre-wiring shape until Phase 20+ registers a real provider.
	provider := auth.LoadProvider() // always NoopProvider in Phase 9

	r := gin.New()
	r.GET("/v1/auth/callback", func(c *gin.Context) {
		redirectURI := c.Query("redirect_uri")
		if err := auth.ValidateRedirectURI(redirectURI, allowlist); err != nil {
			c.JSON(http.StatusBadRequest, gin.H{
				"type":   "https://negelir.com/errors/redirect_not_allowed",
				"title":  "Redirect URI not in allow-list",
				"status": http.StatusBadRequest,
			})
			return
		}
		// Provider interaction would happen here. In Phase 9 this is always
		// ErrNotConfigured; the validator is the subject of this test, not the
		// provider response.
		_ = provider
		c.Status(http.StatusOK)
	})

	tests := []struct {
		name        string
		redirectURI string
		wantStatus  int
	}{
		{
			name:        "open_redirect_attack",
			redirectURI: "https://evil.example.com/steal",
			wantStatus:  http.StatusBadRequest,
		},
		{
			name:        "empty_uri_rejected",
			redirectURI: "",
			wantStatus:  http.StatusBadRequest,
		},
		{
			name:        "partial_match_rejected",
			redirectURI: "https://negelir.com/auth/callback?extra=injected",
			wantStatus:  http.StatusBadRequest,
		},
		{
			name:        "allowlisted_uri_accepted",
			redirectURI: "https://negelir.com/auth/callback",
			wantStatus:  http.StatusOK,
		},
		{
			name:        "second_allowlisted_uri_accepted",
			redirectURI: "http://localhost:8080/auth/callback",
			wantStatus:  http.StatusOK,
		},
		{
			name:        "scheme_swap_rejected",
			redirectURI: "http://negelir.com/auth/callback", // http not https
			wantStatus:  http.StatusBadRequest,
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			path := "/v1/auth/callback"
			if tc.redirectURI != "" {
				path += "?redirect_uri=" + url.QueryEscape(tc.redirectURI)
			}
			w := httptest.NewRecorder()
			req := httptest.NewRequest(http.MethodGet, path, nil)
			r.ServeHTTP(w, req)

			if w.Code != tc.wantStatus {
				t.Errorf("redirect_uri=%q: got HTTP %d, want %d; body=%s",
					tc.redirectURI, w.Code, tc.wantStatus, w.Body.String())
			}
		})
	}
}

// TestValidateRedirectURI_Unit — unit test for auth.ValidateRedirectURI.
// Verifies the exact-match semantics directly, without the HTTP layer.
func TestValidateRedirectURI_Unit(t *testing.T) {
	allowlist := []string{
		"https://negelir.com/auth/callback",
		"http://localhost:8080/auth/callback",
	}

	cases := []struct {
		uri     string
		wantErr bool
	}{
		{"https://negelir.com/auth/callback", false},
		{"http://localhost:8080/auth/callback", false},
		{"https://evil.com/steal", true},
		{"", true},
		{"https://negelir.com/auth/callback?extra=1", true}, // exact match only
		{"https://NEGELIR.COM/auth/callback", true},         // case-sensitive
	}

	for _, tc := range cases {
		err := auth.ValidateRedirectURI(tc.uri, allowlist)
		if (err != nil) != tc.wantErr {
			t.Errorf("ValidateRedirectURI(%q): err=%v, wantErr=%v", tc.uri, err, tc.wantErr)
		}
	}

	// Empty allowlist must reject everything.
	if err := auth.ValidateRedirectURI("https://negelir.com/auth/callback", nil); err == nil {
		t.Error("empty allowlist: want ErrRedirectNotAllowed, got nil")
	}
}
