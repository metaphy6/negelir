package sec

import (
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// TestEmbeddedAssetsByteIdenticalToCanonical asserts that the copies
// in `server/internal/sec/embedded/` are byte-for-byte identical to
// their canonical sources. //go:embed cannot escape the package
// directory, so we copy on build; this test is the gate that guarantees
// the copy is never stale.
//
// If this test fails, refresh the embedded copy with:
//
//	cp ai/common/security/injection_patterns.yaml \
//	   server/internal/sec/embedded/injection_patterns.yaml
//	# (etc. for whichever file diverged)
func TestEmbeddedAssetsByteIdenticalToCanonical(t *testing.T) {
	root := repoRoot(t)
	cases := []struct {
		embedded string
		canon    string
	}{
		{"server/internal/sec/embedded/sec_rate_check.lua", "infra/redis/lua/sec_rate_check.lua"},
		{"server/internal/sec/embedded/sec_denylist_mutate.lua", "infra/redis/lua/sec_denylist_mutate.lua"},
		{"server/internal/sec/embedded/sec_denylist_decimate.lua", "infra/redis/lua/sec_denylist_decimate.lua"},
		{"server/internal/sec/embedded/qa.request.v1.json", "ai/swarm/sdk/schemas/qa.request.v1.json"},
		{"server/internal/sec/embedded/injection_patterns.yaml", "ai/common/security/injection_patterns.yaml"},
		{"server/internal/sec/embedded/endpoint_costs.yaml", "ai/common/security/endpoint_costs.yaml"},
	}
	for _, c := range cases {
		t.Run(filepath.Base(c.embedded), func(t *testing.T) {
			a, err := os.ReadFile(filepath.Join(root, c.embedded))
			if err != nil {
				t.Fatalf("read embedded %s: %v", c.embedded, err)
			}
			b, err := os.ReadFile(filepath.Join(root, c.canon))
			if err != nil {
				t.Fatalf("read canonical %s: %v", c.canon, err)
			}
			if string(a) != string(b) {
				t.Fatalf("embedded copy of %s drifted from canonical %s", c.embedded, c.canon)
			}
		})
	}
}

// TestEmbeddedConstantsNonEmpty is a smoke check that the //go:embed
// directives actually pulled file content (catches a misnamed path
// that would otherwise silently produce an empty string).
func TestEmbeddedConstantsNonEmpty(t *testing.T) {
	if len(EmbeddedRateCheckLua) == 0 {
		t.Fatal("EmbeddedRateCheckLua is empty")
	}
	if len(EmbeddedDenylistMutateLua) == 0 {
		t.Fatal("EmbeddedDenylistMutateLua is empty")
	}
	if len(EmbeddedDecimateLua) == 0 {
		t.Fatal("EmbeddedDecimateLua is empty")
	}
	if len(EmbeddedQARequestV1Schema) == 0 {
		t.Fatal("EmbeddedQARequestV1Schema is empty")
	}
	if len(EmbeddedInjectionPatternsYAML) == 0 {
		t.Fatal("EmbeddedInjectionPatternsYAML is empty")
	}
	if len(EmbeddedEndpointCostsYAML) == 0 {
		t.Fatal("EmbeddedEndpointCostsYAML is empty")
	}
}

func TestGoSecLayerDoesNotParseMorphology(t *testing.T) {
	root := repoRoot(t)
	secDir := filepath.Join(root, "server/internal/sec")
	walkErr := filepath.WalkDir(secDir, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() || filepath.Ext(path) != ".go" {
			return nil
		}
		content, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		needle := strings.Join([]string{"z", "e", "m", "b", "e", "r", "e", "k"}, "")
		if strings.Contains(string(content), needle) {
			rel, err := filepath.Rel(root, path)
			if err != nil {
				rel = path
			}
			t.Fatalf("unexpected Zemberek reference in %s", rel)
		}
		return nil
	})
	if walkErr != nil {
		t.Fatalf("walk sec dir: %v", walkErr)
	}
}

// repoRoot walks up until it finds AGENTS.md (the repo's reliable
// root marker; mirrors the pattern in `server/internal/config/sync_test.go`).
func repoRoot(t *testing.T) string {
	t.Helper()
	dir, err := os.Getwd()
	if err != nil {
		t.Fatalf("getwd: %v", err)
	}
	for {
		if _, err := os.Stat(filepath.Join(dir, "AGENTS.md")); err == nil {
			return dir
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			t.Fatal("could not find repo root (AGENTS.md)")
		}
		dir = parent
	}
}
