package auth_test

import (
	"errors"
	"os"
	"testing"

	"github.com/metaphy6/negelir/server/internal/auth"
)

// TestNoopProvider_AllMethods verifies every NoopProvider method returns
// ErrNotConfigured and no other error value.
func TestNoopProvider_AllMethods(t *testing.T) {
	p := auth.NoopProvider{}

	t.Run("Discover", func(t *testing.T) {
		err := p.Discover()
		if !errors.Is(err, auth.ErrNotConfigured) {
			t.Fatalf("Discover() = %v; want ErrNotConfigured", err)
		}
	})

	t.Run("Exchange", func(t *testing.T) {
		tok, err := p.Exchange("any_code")
		if !errors.Is(err, auth.ErrNotConfigured) {
			t.Fatalf("Exchange() err = %v; want ErrNotConfigured", err)
		}
		if tok != nil {
			t.Fatalf("Exchange() token = %v; want nil", tok)
		}
	})

	t.Run("Userinfo", func(t *testing.T) {
		claims, err := p.Userinfo("any_token")
		if !errors.Is(err, auth.ErrNotConfigured) {
			t.Fatalf("Userinfo() err = %v; want ErrNotConfigured", err)
		}
		if claims != nil {
			t.Fatalf("Userinfo() claims = %v; want nil", claims)
		}
	})

	t.Run("IDTokenClaims", func(t *testing.T) {
		claims, err := p.IDTokenClaims("raw.id.token")
		if !errors.Is(err, auth.ErrNotConfigured) {
			t.Fatalf("IDTokenClaims() err = %v; want ErrNotConfigured", err)
		}
		if claims != nil {
			t.Fatalf("IDTokenClaims() claims = %v; want nil", claims)
		}
	})
}

// TestLoadProvider_NoEnvVars verifies that LoadProvider returns a NoopProvider
// when no OIDC_* environment variables are set (the expected default state).
func TestLoadProvider_NoEnvVars(t *testing.T) {
	// Ensure env is clean for this test.
	for _, key := range []string{"OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET"} {
		t.Setenv(key, "")
	}

	p := auth.LoadProvider()
	if err := p.Discover(); !errors.Is(err, auth.ErrNotConfigured) {
		t.Fatalf("LoadProvider() with no OIDC env: Discover() = %v; want ErrNotConfigured", err)
	}
}

// TestLoadProvider_WithEnvVars verifies that LoadProvider still returns a
// NoopProvider when OIDC_* env vars are set — no real provider is bundled in
// Phase 9 (doctrine: forbidden to bundle Google/MS/GH SDKs in v1).
func TestLoadProvider_WithEnvVars(t *testing.T) {
	t.Setenv("OIDC_ISSUER", "https://example.com")
	t.Setenv("OIDC_CLIENT_ID", "client_id")
	t.Setenv("OIDC_CLIENT_SECRET", "client_secret")
	defer func() {
		os.Unsetenv("OIDC_ISSUER")
		os.Unsetenv("OIDC_CLIENT_ID")
		os.Unsetenv("OIDC_CLIENT_SECRET")
	}()

	p := auth.LoadProvider()
	if err := p.Discover(); !errors.Is(err, auth.ErrNotConfigured) {
		t.Fatalf("LoadProvider() with OIDC env set: Discover() = %v; want ErrNotConfigured (no real provider in v1)", err)
	}
}

// TestNoopProvider_ImplementsProvider ensures NoopProvider satisfies the
// Provider interface at compile time (adversarial: catches accidental interface
// drift).
func TestNoopProvider_ImplementsProvider(t *testing.T) {
	var _ auth.Provider = auth.NoopProvider{}
}

// TestErrNotConfigured_IsDistinct ensures ErrNotConfigured is not nil and has
// the expected message (guards against accidental reassignment or wrapping).
func TestErrNotConfigured_IsDistinct(t *testing.T) {
	if auth.ErrNotConfigured == nil {
		t.Fatal("ErrNotConfigured must not be nil")
	}
	if auth.ErrNotConfigured.Error() != "not_configured" {
		t.Fatalf("ErrNotConfigured.Error() = %q; want %q", auth.ErrNotConfigured.Error(), "not_configured")
	}
}
