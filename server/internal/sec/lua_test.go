package sec

import (
	"errors"
	"strings"
	"testing"
)

// TestHeaderSHA256MatchesEmbedded — the embedded Lua scripts pass
// the same gate the Python `make verify.lua` enforces. If this fails,
// the SHA256 line in the .lua file does not match the body bytes
// (run `make verify.lua fix`).
func TestHeaderSHA256MatchesEmbedded(t *testing.T) {
	cases := []struct {
		name string
		body string
	}{
		{"sec_rate_check.lua", EmbeddedRateCheckLua},
		{"sec_denylist_mutate.lua", EmbeddedDenylistMutateLua},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if err := VerifyHeader(c.name, c.body); err != nil {
				t.Fatalf("VerifyHeader: %v", err)
			}
		})
	}
}

func TestHeaderSHA256RejectsTamperedBody(t *testing.T) {
	tampered := EmbeddedRateCheckLua + "\n-- injected comment\n"
	err := VerifyHeader("tampered.lua", tampered)
	if err == nil || !strings.Contains(err.Error(), "drift") {
		t.Fatalf("expected drift error, got %v", err)
	}
}

func TestHeaderRejectsMissingHeaders(t *testing.T) {
	cases := []struct{ name, body, want string }{
		{"empty", "", "empty body"},
		{"no_version", "-- SHA256: deadbeef\nreturn 1\n", "missing `-- VERSION:`"},
		{"no_sha", "-- VERSION: 1.0.0\nreturn 1\n", "missing `-- SHA256:`"},
		{"placeholder", "-- VERSION: 1.0.0\n-- SHA256: PLACEHOLDER\nreturn 1\n", "placeholder"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			err := VerifyHeader("x.lua", c.body)
			if err == nil || !strings.Contains(err.Error(), c.want) {
				t.Fatalf("got %v, want substring %q", err, c.want)
			}
		})
	}
}

func TestScriptSHA1Stable(t *testing.T) {
	// SHA1("") = da39a3ee5e6b4b0d3255bfef95601890afd80709 — sanity check
	// for the wrapper.
	if got := ScriptSHA1(""); got != "da39a3ee5e6b4b0d3255bfef95601890afd80709" {
		t.Fatalf("SHA1 wrapper drift: %s", got)
	}
}

func TestScriptLoaderVerifyHappyPath(t *testing.T) {
	loader := NewScriptLoader("sec_rate_check", EmbeddedRateCheckLua)
	called := false
	load := func(body string) (string, error) {
		called = true
		if body != EmbeddedRateCheckLua {
			t.Fatalf("LoadFn received wrong body")
		}
		return loader.SHA1(), nil
	}
	if err := loader.Verify(load); err != nil {
		t.Fatalf("Verify: %v", err)
	}
	if !called {
		t.Fatal("LoadFn must be invoked")
	}
}

func TestScriptLoaderVerifyDetectsDeploySkew(t *testing.T) {
	loader := NewScriptLoader("sec_rate_check", EmbeddedRateCheckLua)
	load := func(body string) (string, error) {
		return "0000000000000000000000000000000000000000", nil
	}
	err := loader.Verify(load)
	if err == nil || !strings.Contains(err.Error(), "deploy skew") {
		t.Fatalf("expected deploy-skew error, got %v", err)
	}
}

func TestScriptLoaderVerifyPropagatesLoadError(t *testing.T) {
	loader := NewScriptLoader("sec_rate_check", EmbeddedRateCheckLua)
	sentinel := errors.New("redis down")
	load := func(body string) (string, error) { return "", sentinel }
	err := loader.Verify(load)
	if err == nil || !errors.Is(err, sentinel) {
		t.Fatalf("expected wrapped sentinel, got %v", err)
	}
}

func TestScriptLoaderRejectsNilLoadFn(t *testing.T) {
	loader := NewScriptLoader("sec_rate_check", EmbeddedRateCheckLua)
	if err := loader.Verify(nil); err == nil {
		t.Fatal("expected error on nil LoadFn")
	}
}

// TestLuaLoaderRefusesBootOnDrift tampers the `-- SHA256:` header line of
// sec_rate_check.lua (simulating an attacker or deploy-skew modifying the
// embedded script's header) and verifies that ScriptLoader.Verify — the
// boot validator — returns an explicit "drift" error before ever reaching
// the LoadFn (i.e. the boot is refused at header-integrity stage).
func TestLuaLoaderRefusesBootOnDrift(t *testing.T) {
	// Locate the real claimed digest so we can swap it for a fake one.
	realClaimed := HeaderClaimedSHA256(EmbeddedRateCheckLua)
	if realClaimed == "" {
		t.Fatal("EmbeddedRateCheckLua has no SHA256 header — test precondition failed")
	}

	// Replace the real SHA256 with an all-zeros digest of the same length.
	// This models an attacker modifying the header field in the .lua file
	// (distinct from modifying the script body, which changes the claimed
	// hash indirectly — here we directly forge the header line).
	fakeDigest := strings.Repeat("0", len(realClaimed))
	tampered := strings.Replace(
		EmbeddedRateCheckLua,
		"-- SHA256: "+realClaimed,
		"-- SHA256: "+fakeDigest,
		1,
	)

	loader := NewScriptLoader("sec_rate_check.lua", tampered)

	// The LoadFn must NOT be called: VerifyHeader runs first and must
	// short-circuit with a drift error before any Redis I/O.
	load := func(body string) (string, error) {
		t.Error("LoadFn must not be invoked when header is tampered")
		return "", nil
	}

	err := loader.Verify(load)
	if err == nil {
		t.Fatal("Verify must return an error on header drift, got nil")
	}
	if !strings.Contains(err.Error(), "drift") {
		t.Fatalf("error must contain 'drift' to be explicit, got: %v", err)
	}
}
