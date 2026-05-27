package apigen_test

// §9.4 openapi.yaml binding tests.
//
// Asserts the invariants that make `server/api/openapi.yaml` the binding
// source of truth:
//
//   TestOpenAPISpecParses            — file exists and is valid YAML
//   TestOpenAPIRoutesHaveRequiredExtensions — every route has x-rate-cost,
//                                      x-tier-required, x-idempotent-mutation
//   TestGenFileIsCommitted           — api.gen.go is present (not empty)
//
// These tests are file-system / structural: they require no running service
// and no network access.

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"gopkg.in/yaml.v3"
)

// repoRoot walks up from the test binary's working directory until AGENTS.md
// is found. Safe to call from any subdirectory.
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
			t.Fatal("could not find repo root (AGENTS.md not found)")
		}
		dir = parent
	}
}

// TestOpenAPISpecParses verifies server/api/openapi.yaml exists and is
// well-formed YAML (structural parse only — not full OpenAPI validation).
func TestOpenAPISpecParses(t *testing.T) {
	root := repoRoot(t)
	spec := filepath.Join(root, "server", "api", "openapi.yaml")
	data, err := os.ReadFile(spec)
	if err != nil {
		t.Fatalf("server/api/openapi.yaml not found: %v", err)
	}
	var doc map[string]any
	if err := yaml.Unmarshal(data, &doc); err != nil {
		t.Fatalf("openapi.yaml is not valid YAML: %v", err)
	}
	if doc["openapi"] == nil {
		t.Error("openapi.yaml missing top-level 'openapi' key")
	}
	if doc["paths"] == nil {
		t.Error("openapi.yaml missing top-level 'paths' key")
	}
}

// TestOpenAPIRoutesHaveRequiredExtensions verifies every path+method in
// server/api/openapi.yaml carries the three required Phase 9 extensions:
//   x-rate-cost         (integer — must be present; 0 is valid for probes)
//   x-tier-required     (string — dormant; must still be declared)
//   x-idempotent-mutation (bool — drives Idempotency-Key requirement)
//
// This mirrors the boot-time check that spec_loader.go (§9.4 bullet 4)
// will enforce at runtime; having it as a test lets CI catch missing
// extensions without a running server.
func TestOpenAPIRoutesHaveRequiredExtensions(t *testing.T) {
	root := repoRoot(t)
	spec := filepath.Join(root, "server", "api", "openapi.yaml")
	data, err := os.ReadFile(spec)
	if err != nil {
		t.Fatalf("server/api/openapi.yaml not found: %v", err)
	}
	var doc map[string]any
	if err := yaml.Unmarshal(data, &doc); err != nil {
		t.Fatalf("openapi.yaml is not valid YAML: %v", err)
	}

	paths, ok := doc["paths"].(map[string]any)
	if !ok || len(paths) == 0 {
		t.Fatal("openapi.yaml has no paths")
	}

	httpMethods := map[string]bool{
		"get": true, "post": true, "put": true,
		"patch": true, "delete": true, "head": true, "options": true,
	}
	required := []string{"x-rate-cost", "x-tier-required", "x-idempotent-mutation"}

	for route, pathItemAny := range paths {
		pathItem, ok := pathItemAny.(map[string]any)
		if !ok {
			continue
		}
		for key, opAny := range pathItem {
			if !httpMethods[key] {
				continue // skip parameters, summary, etc.
			}
			op, ok := opAny.(map[string]any)
			if !ok {
				t.Errorf("%s %s: operation is not a map", key, route)
				continue
			}
			for _, ext := range required {
				if _, present := op[ext]; !present {
					t.Errorf(
						"%s %s: missing required extension %q — "+
							"every route must carry x-rate-cost, "+
							"x-tier-required, and x-idempotent-mutation",
						key, route, ext,
					)
				}
			}
		}
	}
}

// TestNoBillingRouteInV1 asserts the Phase 20 boundary contract: no
// /v1/billing/* route may be pre-exposed in v1.  Phase 20 owns those
// routes and will add them under its own milestone; any premature
// /billing/ path in server/api/openapi.yaml is a contract violation.
func TestNoBillingRouteInV1(t *testing.T) {
	root := repoRoot(t)
	spec := filepath.Join(root, "server", "api", "openapi.yaml")
	data, err := os.ReadFile(spec)
	if err != nil {
		t.Fatalf("server/api/openapi.yaml not found: %v", err)
	}
	var doc map[string]any
	if err := yaml.Unmarshal(data, &doc); err != nil {
		t.Fatalf("openapi.yaml is not valid YAML: %v", err)
	}

	paths, ok := doc["paths"].(map[string]any)
	if !ok {
		// No paths at all — nothing to check.
		return
	}
	for route := range paths {
		if strings.Contains(route, "/billing/") || strings.HasSuffix(route, "/billing") {
			t.Errorf(
				"Phase 20 boundary violation: path %q must not exist in v1 — "+
					"billing routes are owned by Phase 20 (see §9.15 forward-phase contracts)",
				route,
			)
		}
	}
}

// TestGenFileIsCommitted verifies server/internal/apigen/api.gen.go exists
// and is non-empty.  The CI gate make api.gen-check verifies it matches the
// spec; this test just ensures it hasn't been deleted by accident.
func TestGenFileIsCommitted(t *testing.T) {
	root := repoRoot(t)
	gen := filepath.Join(root, "server", "internal", "apigen", "api.gen.go")
	info, err := os.Stat(gen)
	if err != nil {
		t.Fatalf("server/internal/apigen/api.gen.go not found: %v\nRun `make api.gen` to regenerate.", err)
	}
	if info.Size() == 0 {
		t.Fatal("server/internal/apigen/api.gen.go is empty — run `make api.gen`")
	}
}
