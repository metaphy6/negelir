package sec

import (
	"crypto/sha1"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"regexp"
	"strings"
)

// Lua script header doctrine (mirrors xops/makefile/lua.py):
//
//   -- VERSION: <semver>
//   -- SHA256: <hex digest of the file with the SHA256 line replaced
//             by the placeholder string "PLACEHOLDER">
//
// On startup, the gateway:
//   (1) verifies the embedded script body's header SHA256 matches
//       the recompute over the body — file integrity / deploy-skew;
//   (2) computes the script body's SHA1 (which is what Redis EVALSHA
//       uses) and remembers it for `EVALSHA` calls;
//   (3) calls SCRIPT LOAD on Redis, gets back a SHA1; if the returned
//       SHA1 disagrees with the locally computed SHA1, the gateway
//       refuses to start (deployment skew between the binary's
//       embedded body and what Redis actually loaded).
//
// The Lua loader does not own the Redis client. It exposes the two
// helpers (HeaderSHA256 + ScriptSHA1) and `VerifyHeader` so the
// caller can wire it into whichever Redis driver is in scope. Tests
// drive ScriptLoader.Verify with a fake LoadFn.

const (
	luaShaPlaceholder = "PLACEHOLDER"
)

var (
	luaSHALineRE     = regexp.MustCompile(`(?m)^-- SHA256: (.+)$`)
	luaVersionLineRE = regexp.MustCompile(`(?m)^-- VERSION: (.+)$`)
)

// HeaderSHA256 returns the recomputed SHA256 of `body` with the
// `-- SHA256:` line replaced by the placeholder string. Mirrors
// xops/makefile/lua.py::_expected_sha — drift between the two would
// silently break the cross-language gate.
func HeaderSHA256(body string) string {
	normalized := luaSHALineRE.ReplaceAllString(body, "-- SHA256: "+luaShaPlaceholder)
	sum := sha256.Sum256([]byte(normalized))
	return hex.EncodeToString(sum[:])
}

// HeaderClaimedSHA256 returns the SHA256 written in the `-- SHA256:`
// header line, or "" if the header is missing/blank.
func HeaderClaimedSHA256(body string) string {
	m := luaSHALineRE.FindStringSubmatch(body)
	if m == nil {
		return ""
	}
	return strings.TrimSpace(m[1])
}

// HeaderVersion returns the semver in the `-- VERSION:` line, or "".
func HeaderVersion(body string) string {
	m := luaVersionLineRE.FindStringSubmatch(body)
	if m == nil {
		return ""
	}
	return strings.TrimSpace(m[1])
}

// ScriptSHA1 is the SHA1 hex digest of `body` exactly as Redis would
// compute it (Redis hashes the script bytes; Lua interpretation runs
// against those same bytes). EVALSHA targets this value.
func ScriptSHA1(body string) string {
	sum := sha1.Sum([]byte(body))
	return hex.EncodeToString(sum[:])
}

// VerifyHeader checks the embedded body's `-- SHA256:` header against
// a recompute. Returns nil when in agreement; otherwise an error
// pointing at the drift. The placeholder string is treated as a
// build-time signal that `make verify.lua fix` was not run after an
// edit and is rejected loud.
func VerifyHeader(name, body string) error {
	if body == "" {
		return fmt.Errorf("lua %s: empty body", name)
	}
	if HeaderVersion(body) == "" {
		return fmt.Errorf("lua %s: missing `-- VERSION:` header", name)
	}
	claimed := HeaderClaimedSHA256(body)
	if claimed == "" {
		return fmt.Errorf("lua %s: missing `-- SHA256:` header", name)
	}
	if claimed == luaShaPlaceholder {
		return fmt.Errorf("lua %s: `-- SHA256:` header is the placeholder; run `make verify.lua fix`", name)
	}
	expected := HeaderSHA256(body)
	if claimed != expected {
		return fmt.Errorf("lua %s: header SHA256 drift (claimed=%s expected=%s)", name, claimed, expected)
	}
	return nil
}

// LoadFn abstracts a Redis SCRIPT LOAD call. It returns whatever the
// server returned (typically the SHA1 of the script body) or an error.
// Production code wires this to `redis.Client.ScriptLoad(...).Result()`;
// tests stub it with a closure.
type LoadFn func(body string) (string, error)

// ScriptLoader runs the deploy-skew gate for one Lua script.
//
// Use:
//
//	loader := sec.NewScriptLoader("sec_rate_check", sec.EmbeddedRateCheckLua)
//	if err := loader.Verify(rdb.ScriptLoadFn); err != nil {
//	    log.Fatal(err)
//	}
//	// loader.SHA1() now returns the value to pass to EVALSHA.
type ScriptLoader struct {
	name string
	body string
	sha1 string
}

// NewScriptLoader pins a name + body. The SHA1 is computed lazily on
// first use; the constructor itself does no I/O.
func NewScriptLoader(name, body string) *ScriptLoader {
	return &ScriptLoader{name: name, body: body, sha1: ScriptSHA1(body)}
}

// Body returns the embedded script body (handy for fallback EVAL on
// NOSCRIPT recovery).
func (l *ScriptLoader) Body() string { return l.body }

// Name returns the loader's human-readable name (e.g. "sec_rate_check").
func (l *ScriptLoader) Name() string { return l.name }

// SHA1 is the value to pass to EVALSHA.
func (l *ScriptLoader) SHA1() string { return l.sha1 }

// Verify runs the deploy-skew gate end-to-end:
//
//  1. Header integrity (HeaderVersion + HeaderClaimedSHA256 match
//     HeaderSHA256(body)).
//  2. SCRIPT LOAD — calls `load(body)`, expects the returned SHA1 to
//     equal `ScriptSHA1(body)`. A drift here means Redis loaded a
//     different body than the binary embeds, which only happens if
//     the operator pointed the binary at a Redis preloaded by a
//     different binary version. Loud failure is the only safe move.
func (l *ScriptLoader) Verify(load LoadFn) error {
	if err := VerifyHeader(l.name, l.body); err != nil {
		return err
	}
	if load == nil {
		return fmt.Errorf("lua %s: nil LoadFn", l.name)
	}
	got, err := load(l.body)
	if err != nil {
		return fmt.Errorf("lua %s: SCRIPT LOAD: %w", l.name, err)
	}
	got = strings.TrimSpace(got)
	if got != l.sha1 {
		return fmt.Errorf(
			"lua %s: deploy skew — Redis returned SHA1 %q but local body hashes to %q",
			l.name, got, l.sha1,
		)
	}
	return nil
}
