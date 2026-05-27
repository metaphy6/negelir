package api_test

// §9.14 proof tests — mTLS & migrations
//
// Tests covered in this file:
//   TestMigrationsIdempotent_012_013_014 — test_migrations_idempotent_012_013_014

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// TestMigrationsIdempotent_012_013_014 verifies that SQL migrations 012, 013,
// and 014 are idempotent (safe to re-apply without side effects). It checks:
//
//   - Every CREATE TABLE uses IF NOT EXISTS.
//   - Every CREATE INDEX and CREATE UNIQUE INDEX uses IF NOT EXISTS.
//   - No destructive DDL (DROP TABLE, DROP COLUMN, TRUNCATE) is present.
//     (DROP TRIGGER IF EXISTS is idempotent and is therefore allowed.)
//
// The test is file-system-only (no live DB required) so it runs offline.
func TestMigrationsIdempotent_012_013_014(t *testing.T) {
	root := repoRoot(t)

	migrations := []string{
		"012_users_and_sessions.sql",
		"013_api_audit_partitions.sql",
		"014_jwt_keys.sql",
	}

	for _, name := range migrations {
		t.Run(name, func(t *testing.T) {
			raw, err := os.ReadFile(filepath.Join(root, "migrations", name))
			if err != nil {
				t.Fatalf("read %s: %v", name, err)
			}
			upper := strings.ToUpper(string(raw))

			// checkAllGuarded scans every occurrence of `needle` in the
			// upper-cased SQL and asserts that `guard` appears within the next
			// `window` characters. Failures are reported as sub-errors so the
			// scan continues past the first problem.
			checkAllGuarded := func(needle, guard string, window int) {
				rest := upper
				for {
					idx := strings.Index(rest, needle)
					if idx < 0 {
						break
					}
					end := idx + window
					if end > len(rest) {
						end = len(rest)
					}
					if !strings.Contains(rest[idx:end], guard) {
						// Surface the offending snippet (capped at 80 chars) for readability.
						snip := rest[idx:]
						if len(snip) > 80 {
							snip = snip[:80]
						}
						t.Errorf("%s: %q not followed by %q within %d chars — got: %q",
							name, needle, guard, window, snip)
					}
					rest = rest[idx+len(needle):]
				}
			}

			// All CREATE TABLE statements must carry IF NOT EXISTS.
			checkAllGuarded("CREATE TABLE", "IF NOT EXISTS", 50)

			// All CREATE INDEX statements must carry IF NOT EXISTS.
			// Note: "CREATE INDEX" does not match inside "CREATE UNIQUE INDEX"
			// because they are distinct substrings.
			checkAllGuarded("CREATE INDEX", "IF NOT EXISTS", 60)
			checkAllGuarded("CREATE UNIQUE INDEX", "IF NOT EXISTS", 60)

			// Destructive DDL must be absent.
			// DROP TRIGGER IF EXISTS is intentionally not in this list — it is
			// the standard idempotency pattern for triggers.
			for _, bad := range []string{"DROP TABLE", "DROP COLUMN", "TRUNCATE"} {
				if strings.Contains(upper, bad) {
					t.Errorf("%s: contains destructive DDL %q — migrations must be safe to re-run", name, bad)
				}
			}
		})
	}
}
