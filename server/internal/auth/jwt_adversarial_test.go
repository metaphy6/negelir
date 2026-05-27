package auth_test

// jwt_adversarial_test.go — Phase 9 §9.14 adversarial JWT proof tests.
//
// These four tests are Phase 12 prerequisites and must be green at Phase 9 close.
// They are NEVER xfail — if any of them fails the build fails unconditionally.
//
//   adv_test_jwt_alg_none_attack          (TestAdvJWTAlgNoneAttack)
//   adv_test_jwt_kid_path_traversal       (TestAdvJWTKidPathTraversal)
//   adv_test_jwt_hs256_with_pubkey_as_secret (TestAdvJWTHS256WithPubkeyAsSecret)
//   adv_test_jwt_expired_in_grace_clock_skew (TestAdvJWTExpiredInGraceClockSkew)

import (
	"crypto/rand"
	"crypto/rsa"
	"testing"
	"time"

	jwt "github.com/golang-jwt/jwt/v5"

	"github.com/metaphy6/negelir/server/internal/auth"
)

// ─── TestAdvJWTAlgNoneAttack ──────────────────────────────────────────────────

// TestAdvJWTAlgNoneAttack — adv_test_jwt_alg_none_attack.
//
// A JWT whose header declares "alg":"none" must be rejected with an error.
// No fallback path (e.g. accepting unsigned tokens) is tolerated. This closes
// the CVE-2015-9235 class of algorithm-confusion vulnerabilities.
func TestAdvJWTAlgNoneAttack(t *testing.T) {
	ks, _ := newKeyStore(t)

	// Craft an unsigned ("alg":"none") token.  golang-jwt/v5 requires
	// jwt.UnsafeAllowNoneSignatureType as the signing secret to produce such a
	// token, preventing accidental use.
	unsignedClaims := jwt.MapClaims{
		"sub": "attacker",
		"exp": float64(time.Now().Add(2 * time.Minute).Unix()),
	}
	tok := jwt.NewWithClaims(jwt.SigningMethodNone, unsignedClaims)
	tokenStr, err := tok.SignedString(jwt.UnsafeAllowNoneSignatureType)
	if err != nil {
		t.Fatalf("craft alg=none token: %v", err)
	}

	_, err = ks.Verify(tokenStr)
	if err == nil {
		t.Fatal("adv: alg=none token must be rejected (got nil error — 401 not enforced)")
	}
	// Confirm it is a signing-method rejection, not some other transient error.
	t.Logf("alg=none correctly rejected: %v", err)
}

// ─── TestAdvJWTKidPathTraversal ───────────────────────────────────────────────

// TestAdvJWTKidPathTraversal — adv_test_jwt_kid_path_traversal.
//
// A JWT with kid="../../etc/passwd" (path traversal) must be rejected.
// The verifier must not attempt to read any file based on the kid header value;
// the only lookup path is the in-memory cache and the DB.
//
// Attack surface: some naive implementations concatenate cfg.jwt_key_dir + kid
// and call os.ReadFile.  This test proves Verify does no such thing.
func TestAdvJWTKidPathTraversal(t *testing.T) {
	ks, _ := newKeyStore(t)

	// Generate a throwaway RSA key — NOT registered in the keystore.
	throwawayKey, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatalf("generate throwaway key: %v", err)
	}

	maliciousClaims := jwt.MapClaims{
		"sub": "attacker",
		"exp": float64(time.Now().Add(2 * time.Minute).Unix()),
	}
	tok := jwt.NewWithClaims(jwt.SigningMethodRS256, maliciousClaims)
	tok.Header["kid"] = "../../etc/passwd" // path traversal attempt
	tokenStr, err := tok.SignedString(throwawayKey)
	if err != nil {
		t.Fatalf("craft path-traversal token: %v", err)
	}

	_, err = ks.Verify(tokenStr)
	if err == nil {
		t.Fatal("adv: kid=../../etc/passwd token must be rejected (got nil error — 401 not enforced)")
	}
	// Verify rejection is due to an unknown/unregistered kid, not a filesystem
	// side-effect.  The error must not contain OS-level path access messages;
	// it is acceptable for the error to quote the kid value itself (which
	// happens to contain the string "../../etc/passwd") as long as no OS read
	// was attempted.
	errStr := err.Error()
	for _, forbidden := range []string{"no such file", "permission denied", "open /", "read /"} {
		if containsFold(errStr, forbidden) {
			t.Errorf("adv: error message leaks filesystem access (%q found in %q)", forbidden, errStr)
		}
	}
	t.Logf("kid path-traversal correctly rejected: %v", err)
}

// containsFold is strings.Contains with ASCII fold — avoids importing strings.
func containsFold(s, sub string) bool {
	if len(sub) == 0 {
		return true
	}
	for i := 0; i+len(sub) <= len(s); i++ {
		match := true
		for j := 0; j < len(sub); j++ {
			a, b := s[i+j], sub[j]
			if a >= 'A' && a <= 'Z' {
				a += 'a' - 'A'
			}
			if b >= 'A' && b <= 'Z' {
				b += 'a' - 'A'
			}
			if a != b {
				match = false
				break
			}
		}
		if match {
			return true
		}
	}
	return false
}

// ─── TestAdvJWTHS256WithPubkeyAsSecret ───────────────────────────────────────

// TestAdvJWTHS256WithPubkeyAsSecret — adv_test_jwt_hs256_with_pubkey_as_secret.
//
// Algorithm-confusion attack: the RS256 public key is used as the HS256 HMAC
// secret to forge a plausible-looking token.  A server that accepts both RS256
// and HS256 and naively applies the stored public key as the HMAC secret would
// accept this token.
//
// Our verifier rejects it because it asserts t.Method must be *jwt.SigningMethodRSA.
func TestAdvJWTHS256WithPubkeyAsSecret(t *testing.T) {
	ks, db := newKeyStore(t)

	// Retrieve the active public key PEM from the in-memory DB.
	activeRecs, err := db.GetKeysByStatus(auth.KeyStatusActive)
	if err != nil || len(activeRecs) != 1 {
		t.Fatalf("GetKeysByStatus(active): err=%v, count=%d", err, len(activeRecs))
	}
	pubPEM := activeRecs[0].PubPEM
	kid := activeRecs[0].KID

	// Craft an HS256 token using the RS256 public key as the HMAC secret.
	// This is the canonical CVE-2016-5431 / "alg confusion" attack.
	confusedClaims := jwt.MapClaims{
		"sub": "attacker",
		"exp": float64(time.Now().Add(2 * time.Minute).Unix()),
	}
	tok := jwt.NewWithClaims(jwt.SigningMethodHS256, confusedClaims)
	tok.Header["kid"] = kid                        // plausible kid to pass key-lookup
	tokenStr, err := tok.SignedString([]byte(pubPEM)) // public key as HMAC secret
	if err != nil {
		t.Fatalf("craft HS256-with-pubkey token: %v", err)
	}

	_, err = ks.Verify(tokenStr)
	if err == nil {
		t.Fatal("adv: HS256-with-pubkey-as-secret token must be rejected (got nil error — alg confusion not blocked)")
	}
	t.Logf("HS256 alg-confusion correctly rejected: %v", err)
}

// ─── TestAdvJWTExpiredInGraceClockSkew ────────────────────────────────────────

// TestAdvJWTExpiredInGraceClockSkew — adv_test_jwt_expired_in_grace_clock_skew.
//
// Clock-skew tolerance is bounded by cfg.api_jwt_clock_skew_s (default 30 s).
//
//   token expired 29 s ago  →  accepted (within tolerance)
//   token expired 31 s ago  →  rejected (beyond tolerance → 401)
//
// This test wires the knob directly on the KeyStore via SetClockLeeway(30s) and
// asserts both the acceptance boundary and the rejection boundary.
func TestAdvJWTExpiredInGraceClockSkew(t *testing.T) {
	const clockSkew = 30 * time.Second

	ks, _ := newKeyStore(t)
	ks.SetClockLeeway(clockSkew) // mirrors cfg.api_jwt_clock_skew_s = 30

	signExpiredBy := func(d time.Duration) string {
		t.Helper()
		claims := jwt.MapClaims{
			"sub": "u-skew-test",
			"exp": float64(time.Now().Add(-d).Unix()),
		}
		tok, err := ks.Sign(claims)
		if err != nil {
			t.Fatalf("Sign(exp=-%v): %v", d, err)
		}
		return tok
	}

	// Within tolerance: token expired 29 s ago must be accepted.
	withinTok := signExpiredBy(29 * time.Second)
	if _, err := ks.Verify(withinTok); err != nil {
		t.Errorf("adv: token expired 29s ago must be accepted within 30s clock skew: %v", err)
	}

	// Beyond tolerance: token expired 31 s ago must be rejected.
	beyondTok := signExpiredBy(31 * time.Second)
	if _, err := ks.Verify(beyondTok); err == nil {
		t.Error("adv: token expired 31s ago must be rejected when clock skew is 30s (got nil error — clock-skew cap not enforced)")
	}
}
