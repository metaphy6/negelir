package api_test

// §9.4 spec_loader tests.
//
// ValidateSpecExtensions must:
//   - Accept a well-formed spec where every route carries all three required extensions.
//   - Return a descriptive error listing every violation when any route lacks
//     one or more required extensions.
//   - Return an error for unparseable YAML.
//   - Return an error for a spec with no 'paths' key.

import (
	"strings"
	"testing"

	"github.com/metaphy6/negelir/server/internal/api"
)

const validSpec = `
openapi: "3.0.3"
info:
  title: Test
  version: "1.0.0"
paths:
  /v1/foo:
    get:
      operationId: getFoo
      x-rate-cost: 1
      x-tier-required: free
      x-idempotent-mutation: false
      responses:
        "200":
          description: ok
  /v1/bar:
    post:
      operationId: postBar
      x-rate-cost: 3
      x-tier-required: free
      x-idempotent-mutation: true
      responses:
        "200":
          description: ok
`

const specMissingRateCost = `
openapi: "3.0.3"
info:
  title: Test
  version: "1.0.0"
paths:
  /v1/foo:
    get:
      operationId: getFoo
      x-tier-required: free
      x-idempotent-mutation: false
      responses:
        "200":
          description: ok
`

const specMissingMultiple = `
openapi: "3.0.3"
info:
  title: Test
  version: "1.0.0"
paths:
  /v1/foo:
    get:
      operationId: getFoo
      responses:
        "200":
          description: ok
  /v1/bar:
    post:
      operationId: postBar
      x-rate-cost: 3
      responses:
        "200":
          description: ok
`

// TestValidateSpecExtensions_valid — a spec with all required extensions passes.
func TestValidateSpecExtensions_valid(t *testing.T) {
	if err := api.ValidateSpecExtensions([]byte(validSpec)); err != nil {
		t.Fatalf("expected nil error for fully-annotated spec, got: %v", err)
	}
}

// TestValidateSpecExtensions_missingRateCost — single missing extension reported.
func TestValidateSpecExtensions_missingRateCost(t *testing.T) {
	err := api.ValidateSpecExtensions([]byte(specMissingRateCost))
	if err == nil {
		t.Fatal("expected error for spec missing x-rate-cost, got nil")
	}
	if !strings.Contains(err.Error(), "x-rate-cost") {
		t.Errorf("error should name missing extension 'x-rate-cost', got: %v", err)
	}
}

// TestValidateSpecExtensions_multipleViolations — all violations reported in one error.
func TestValidateSpecExtensions_multipleViolations(t *testing.T) {
	err := api.ValidateSpecExtensions([]byte(specMissingMultiple))
	if err == nil {
		t.Fatal("expected error for spec missing multiple extensions, got nil")
	}
	// /v1/foo missing all three; /v1/bar missing two.
	for _, ext := range []string{"x-rate-cost", "x-tier-required", "x-idempotent-mutation"} {
		if !strings.Contains(err.Error(), ext) {
			t.Errorf("error should mention %q, got: %v", ext, err)
		}
	}
}

// TestValidateSpecExtensions_invalidYAML — unparseable input returns error.
func TestValidateSpecExtensions_invalidYAML(t *testing.T) {
	err := api.ValidateSpecExtensions([]byte(":\t:"))
	if err == nil {
		t.Fatal("expected error for invalid YAML, got nil")
	}
}

// TestValidateSpecExtensions_noPaths — spec without a paths key returns error.
func TestValidateSpecExtensions_noPaths(t *testing.T) {
	err := api.ValidateSpecExtensions([]byte("openapi: \"3.0.3\"\ninfo:\n  title: t\n  version: \"1\"\n"))
	if err == nil {
		t.Fatal("expected error for spec with no paths key, got nil")
	}
	if !strings.Contains(err.Error(), "paths") {
		t.Errorf("error should mention 'paths', got: %v", err)
	}
}
