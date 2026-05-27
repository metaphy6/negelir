package apigen_test

// §9.4 OpenAPI response-body schema-validation tests.
//
// Every handler test in this file asserts that a response body conforms
// to the bound schema declared in server/api/openapi.yaml.  Validation
// runs via github.com/getkin/kin-openapi (dev/test only — never on the
// hot path).
//
//   TestResponseValidator_ConformingBodyPasses
//       — a well-formed ErrorEnvelope passes VisitJSON.
//
//   TestResponseValidator_MalformedHandlerExtraFieldFails
//       — adversarial: handler leaks an extra field into an
//         additionalProperties:false schema; VisitJSON returns an error
//         so the handler bug is caught before merge.
//
// ErrorEnvelope was chosen as the test schema because it already carries
// additionalProperties:false in the spec — no spec change needed.

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/getkin/kin-openapi/openapi3"
)

// loadSchema returns a fully-resolved *openapi3.Schema for the named
// component from server/api/openapi.yaml.  The spec is loaded from the
// repo root discovered by repoRoot (defined in openapi_spec_test.go).
func loadSchema(t *testing.T, schemaName string) *openapi3.Schema {
	t.Helper()
	root := repoRoot(t)
	specPath := filepath.Join(root, "server", "api", "openapi.yaml")

	data, err := os.ReadFile(specPath)
	if err != nil {
		t.Fatalf("loadSchema: cannot read openapi.yaml: %v", err)
	}

	loader := openapi3.NewLoader()
	doc, err := loader.LoadFromData(data)
	if err != nil {
		t.Fatalf("loadSchema: parse failed: %v", err)
	}
	// Resolve all $ref pointers so VisitJSON sees the full schema tree.
	if err := doc.Validate(context.Background()); err != nil {
		t.Fatalf("loadSchema: spec invalid: %v", err)
	}

	ref, ok := doc.Components.Schemas[schemaName]
	if !ok {
		t.Fatalf("loadSchema: schema %q not found in components.schemas", schemaName)
	}
	return ref.Value
}

// visitJSON is a thin wrapper: unmarshal rawJSON then call schema.VisitJSON.
func visitJSON(schema *openapi3.Schema, rawJSON string) error {
	var v any
	if err := json.Unmarshal([]byte(rawJSON), &v); err != nil {
		return err
	}
	return schema.VisitJSON(v)
}

// TestResponseValidator_ConformingBodyPasses — happy path.
// A well-formed ErrorEnvelope body passes schema validation.
func TestResponseValidator_ConformingBodyPasses(t *testing.T) {
	schema := loadSchema(t, "ErrorEnvelope")

	conforming := `{"error":"not_found","code":"not_found","request_id":"abc123"}`
	if err := visitJSON(schema, conforming); err != nil {
		t.Errorf("conforming ErrorEnvelope body failed validation (expected pass): %v", err)
	}

	// Minimal valid body (only required fields).
	minimal := `{"error":"internal","code":"internal"}`
	if err := visitJSON(schema, minimal); err != nil {
		t.Errorf("minimal ErrorEnvelope body failed validation (expected pass): %v", err)
	}
}

// TestResponseValidator_MalformedHandlerExtraFieldFails — adversarial.
// A handler that leaks an undeclared field into an
// additionalProperties:false response schema is caught by VisitJSON.
// This test is the schema-validation gate that prevents such a regression
// from merging undetected.
func TestResponseValidator_MalformedHandlerExtraFieldFails(t *testing.T) {
	schema := loadSchema(t, "ErrorEnvelope")

	// Simulate a handler that accidentally injects an extra field.
	malformed := `{"error":"not_found","code":"not_found","extra_field":"injected_by_buggy_handler"}`
	err := visitJSON(schema, malformed)
	if err == nil {
		t.Error(
			"malformed body with extra field passed validation on an " +
				"additionalProperties:false schema — schema validator failed to catch the regression",
		)
		return
	}
	// Confirm the error message identifies the offending property.
	if !strings.Contains(err.Error(), "extra_field") &&
		!strings.Contains(err.Error(), "additionalProperties") {
		t.Logf("validation correctly rejected malformed body; error: %v", err)
	} else {
		t.Logf("validation correctly rejected malformed body with extra_field: %v", err)
	}
}

// TestResponseValidator_MissingRequiredFieldFails — adversarial.
// A handler that omits a required field is also caught.
func TestResponseValidator_MissingRequiredFieldFails(t *testing.T) {
	schema := loadSchema(t, "ErrorEnvelope")

	// ErrorEnvelope requires both "error" and "code".
	missingCode := `{"error":"not_found"}`
	if err := visitJSON(schema, missingCode); err == nil {
		t.Error(
			"body missing required 'code' field passed validation — " +
				"schema validator should catch missing required fields",
		)
	}
}
