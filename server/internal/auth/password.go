package auth

import (
	"fmt"
	"time"

	"golang.org/x/crypto/bcrypt"
)

const (
	// PasswordAlgBcrypt identifies the bcrypt password-hashing algorithm.
	// Stored in the users.password_alg column (CHAR(1)).
	PasswordAlgBcrypt = "b"

	// PasswordAlgArgon2id is reserved for a future algorithm swap (Phase X).
	// No code path currently produces or verifies argon2id hashes.
	PasswordAlgArgon2id = "a"

	// MinBcryptDuration is the minimum acceptable duration for a single bcrypt
	// hash at the configured cost. The startup probe refuses boot when the
	// measured duration falls below this threshold — guarding against a
	// deployment target so fast that cost=12 becomes a no-op security-wise.
	MinBcryptDuration = 100 * time.Millisecond
)

// HashPassword hashes plaintext using bcrypt at the given cost.
// Returns the Modular Crypt Format hash and the algorithm identifier ("b").
// cost must be in [bcrypt.MinCost, bcrypt.MaxCost].
func HashPassword(plaintext string, cost int) (hash, alg string, err error) {
	b, err := bcrypt.GenerateFromPassword([]byte(plaintext), cost)
	if err != nil {
		return "", "", fmt.Errorf("bcrypt hash: %w", err)
	}
	return string(b), PasswordAlgBcrypt, nil
}

// VerifyAndRehash checks plaintext against the stored hash.
// alg must be PasswordAlgBcrypt ("b"); any other value is an error.
//
// If verification succeeds and the stored bcrypt cost is below targetCost,
// a new hash at targetCost is returned with rehashed=true — the caller is
// responsible for writing the upgraded hash + alg back to the user store.
// The upgrade is best-effort: if re-hashing fails for any reason the login
// still succeeds (rehashed=false, original hash returned).
//
// If verification fails, err is non-nil and rehashed is always false.
func VerifyAndRehash(plaintext, hash, alg string, targetCost int) (newHash, newAlg string, rehashed bool, err error) {
	if alg != PasswordAlgBcrypt {
		return "", "", false, fmt.Errorf("unsupported password algorithm %q", alg)
	}
	if err := bcrypt.CompareHashAndPassword([]byte(hash), []byte(plaintext)); err != nil {
		return "", "", false, err
	}
	// Password matched. Check whether a cost upgrade is warranted.
	storedCost, costErr := bcrypt.Cost([]byte(hash))
	if costErr != nil {
		// Malformed hash — cannot parse cost. Login succeeds without upgrade.
		return hash, alg, false, nil
	}
	if storedCost < targetCost {
		upgraded, _, hashErr := HashPassword(plaintext, targetCost)
		if hashErr != nil {
			// Best-effort: login succeeds, upgrade silently skipped.
			return hash, alg, false, nil
		}
		return upgraded, PasswordAlgBcrypt, true, nil
	}
	return hash, alg, false, nil
}

// ProbeBcryptCost performs one bcrypt hash at the given cost and returns the
// elapsed wall-clock duration. An error is returned when duration <
// MinBcryptDuration — this signals that the deployment target is fast enough
// to render the cost setting meaningless, which is a security misconfiguration.
//
// The startup probe in cmd/api/main.go calls this function with
// cfg.APIBcryptCost and refuses to bind the public listener on error.
func ProbeBcryptCost(cost int) (time.Duration, error) {
	start := time.Now()
	if _, err := bcrypt.GenerateFromPassword([]byte("__probe__"), cost); err != nil {
		return 0, fmt.Errorf("bcrypt probe: %w", err)
	}
	elapsed := time.Since(start)
	if elapsed < MinBcryptDuration {
		return elapsed, fmt.Errorf(
			"bcrypt cost=%d hashed in %v — below %v minimum; "+
				"raise NEGELIR_API_BCRYPT_COST or check deployment target",
			cost, elapsed.Round(time.Millisecond), MinBcryptDuration,
		)
	}
	return elapsed, nil
}
