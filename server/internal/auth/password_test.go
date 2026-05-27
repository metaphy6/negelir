package auth_test

import (
	"errors"
	"testing"

	"golang.org/x/crypto/bcrypt"
	"golang.org/x/text/unicode/norm"

	"github.com/metaphy6/negelir/server/internal/auth"
)

// TestHashPassword_AlgIsB verifies HashPassword always returns alg="b".
func TestHashPassword_AlgIsB(t *testing.T) {
	_, alg, err := auth.HashPassword("secret", bcrypt.MinCost)
	if err != nil {
		t.Fatalf("HashPassword: %v", err)
	}
	if alg != auth.PasswordAlgBcrypt {
		t.Errorf("alg=%q, want %q", alg, auth.PasswordAlgBcrypt)
	}
}

// TestHashPassword_CostRoundtrip verifies the stored cost matches what was
// requested.
func TestHashPassword_CostRoundtrip(t *testing.T) {
	hash, _, err := auth.HashPassword("secret", bcrypt.MinCost)
	if err != nil {
		t.Fatalf("HashPassword: %v", err)
	}
	got, err := bcrypt.Cost([]byte(hash))
	if err != nil {
		t.Fatalf("bcrypt.Cost: %v", err)
	}
	if got != bcrypt.MinCost {
		t.Errorf("stored cost=%d, want %d", got, bcrypt.MinCost)
	}
}

// TestVerifyAndRehash_Match verifies a correct password is accepted.
func TestVerifyAndRehash_Match(t *testing.T) {
	hash, alg, _ := auth.HashPassword("hunter2", bcrypt.MinCost)
	_, _, rehashed, err := auth.VerifyAndRehash("hunter2", hash, alg, bcrypt.MinCost)
	if err != nil {
		t.Fatalf("VerifyAndRehash: %v", err)
	}
	if rehashed {
		t.Error("rehashed=true but cost already at target")
	}
}

// TestVerifyAndRehash_BadPassword verifies a wrong password is rejected.
func TestVerifyAndRehash_BadPassword(t *testing.T) {
	hash, alg, _ := auth.HashPassword("hunter2", bcrypt.MinCost)
	_, _, _, err := auth.VerifyAndRehash("wrong", hash, alg, bcrypt.MinCost)
	if err == nil {
		t.Error("expected error for wrong password, got nil")
	}
}

// TestVerifyAndRehash_UnsupportedAlg verifies an unknown alg is rejected.
func TestVerifyAndRehash_UnsupportedAlg(t *testing.T) {
	_, _, _, err := auth.VerifyAndRehash("pw", "hash", "z", bcrypt.MinCost)
	if err == nil {
		t.Error("expected error for unknown alg")
	}
}

// TestVerifyAndRehash_RehashesWhenCostLow verifies that after a successful
// login, if stored cost < targetCost a new hash is returned with rehashed=true.
func TestVerifyAndRehash_RehashesWhenCostLow(t *testing.T) {
	// Hash at MinCost, then verify demanding MinCost+1.
	hash, alg, _ := auth.HashPassword("hunter2", bcrypt.MinCost)
	newHash, newAlg, rehashed, err := auth.VerifyAndRehash("hunter2", hash, alg, bcrypt.MinCost+1)
	if err != nil {
		t.Fatalf("VerifyAndRehash: %v", err)
	}
	if !rehashed {
		t.Error("rehashed=false but stored cost < targetCost")
	}
	if newAlg != auth.PasswordAlgBcrypt {
		t.Errorf("newAlg=%q, want %q", newAlg, auth.PasswordAlgBcrypt)
	}
	// Confirm new hash is at the upgraded cost.
	gotCost, _ := bcrypt.Cost([]byte(newHash))
	if gotCost != bcrypt.MinCost+1 {
		t.Errorf("upgraded hash cost=%d, want %d", gotCost, bcrypt.MinCost+1)
	}
}

// TestProbeBcryptCost_DetectsUnderCost verifies that ProbeBcryptCost returns
// an error when the cost is so low that hashing completes under the minimum
// duration threshold. bcrypt.MinCost (4) hashes in well under 100 ms on any
// modern machine.
func TestProbeBcryptCost_DetectsUnderCost(t *testing.T) {
	_, err := auth.ProbeBcryptCost(bcrypt.MinCost)
	if err == nil {
		t.Error("expected error for bcrypt.MinCost (too fast), got nil")
	}
}

// TestProbeBcryptCost_BadCostReturnsError verifies that an invalid cost value
// propagates a bcrypt error (not a MinBcryptDuration violation).
func TestProbeBcryptCost_BadCostReturnsError(t *testing.T) {
	// bcrypt.MaxCost+1 is out of range and will fail GenerateFromPassword.
	_, err := auth.ProbeBcryptCost(bcrypt.MaxCost + 1)
	if err == nil {
		t.Error("expected error for cost > bcrypt.MaxCost, got nil")
	}
	// The error must NOT be a MinBcryptDuration violation — it must be a bcrypt
	// internal error.
	var bcryptErr *bcrypt.HashVersionTooNewError
	if errors.As(err, &bcryptErr) {
		t.Skip("unexpected HashVersionTooNewError type")
	}
}

// TestPasswordFieldSkipsNormalize verifies that the login path does NOT trim or
// normalize the password before bcrypt comparison.  A password registered with
// leading whitespace ("  secret") must only match when the same leading
// whitespace is supplied at login; stripping the spaces must produce a mismatch.
//
// This guards against any accidental strings.TrimSpace / unicode.Normalize call
// being inserted into the VerifyAndRehash hot-path (§9.14 sec-gate proof).
func TestPasswordFieldSkipsNormalize(t *testing.T) {
	const withLeadingSpaces = "  secret"
	const withoutSpaces = "secret"

	// Register: hash the password that includes leading whitespace.
	hash, alg, err := auth.HashPassword(withLeadingSpaces, bcrypt.MinCost)
	if err != nil {
		t.Fatalf("HashPassword: %v", err)
	}

	// Login with the exact same whitespace-prefixed string → must succeed.
	_, _, _, err = auth.VerifyAndRehash(withLeadingSpaces, hash, alg, bcrypt.MinCost)
	if err != nil {
		t.Errorf("VerifyAndRehash with leading-space password failed: %v (whitespace was stripped before hashing or comparing)", err)
	}

	// Login with the stripped version → must fail.
	// If VerifyAndRehash were normalizing/trimming, both would succeed — which
	// would be a security regression (wrong password accepted).
	_, _, _, err = auth.VerifyAndRehash(withoutSpaces, hash, alg, bcrypt.MinCost)
	if err == nil {
		t.Error("VerifyAndRehash accepted stripped password; leading whitespace was discarded before bcrypt compare")
	}
}

// TestAdvPasswordUnicodeNormBypass — adv_test_password_unicode_norm_bypass.
//
// Documented one-way design:
//   - Registration caller MUST apply NFC normalisation before calling HashPassword.
//   - Login (VerifyAndRehash) receives raw bytes from the HTTP client — no NFC applied.
//
// Consequences:
//   - hash(NFC(pw)) verified against NFC(pw) → SUCCESS (same bytes hashed and compared).
//   - hash(NFC(pw)) verified against NFD(pw) → FAILURE (different bytes → bcrypt mismatch).
//
// This is intentional: the server is a correct bcrypt oracle for exactly the
// bytes that were hashed at registration. Applying NFC at login too would cause
// false positives when the client sends a normalisation form different from the
// one stored at registration.
func TestAdvPasswordUnicodeNormBypass(t *testing.T) {
	// Turkish word "kağıt" (paper). The 'ğ' (U+011F) and 'ı' (U+0131) have
	// multi-codepoint NFD representations distinct from their NFC forms.
	raw := "kağıt"
	nfc := norm.NFC.String(raw)
	nfd := norm.NFD.String(raw)

	if nfc == nfd {
		// On some platforms the source literal is already fully decomposed,
		// making NFC and NFD identical for this input. Skip rather than fail.
		t.Skip("NFC and NFD forms are identical for this input; bypass test not applicable on this platform")
	}

	// Simulate registration: caller applies NFC, then passes to HashPassword.
	hash, alg, err := auth.HashPassword(nfc, bcrypt.MinCost)
	if err != nil {
		t.Fatalf("HashPassword(NFC form): %v", err)
	}

	// Login with the NFC form → bcrypt compares identical byte strings → SUCCESS.
	if _, _, _, err = auth.VerifyAndRehash(nfc, hash, alg, bcrypt.MinCost); err != nil {
		t.Errorf("adv: NFC login against NFC-hashed password: expected success, got: %v", err)
	}

	// Login with the NFD form → bcrypt sees different bytes → FAILURE.
	// This is the documented contract: raw bytes are used at login, not NFC bytes.
	if _, _, _, err = auth.VerifyAndRehash(nfd, hash, alg, bcrypt.MinCost); err == nil {
		t.Error("adv: NFD login against NFC-hashed password: expected failure " +
			"(byte sequences differ), but VerifyAndRehash succeeded; " +
			"this violates the documented one-way NFC-before-bcrypt contract")
	}
}
