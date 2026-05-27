package api

import (
	"fmt"
	"sort"

	openapi "github.com/metaphy6/negelir/server/api"
	"gopkg.in/yaml.v3"
)

// requiredExtensions is the closed set of OpenAPI extension keys that every
// route MUST carry (§9.4 binding contract). Boot fails if any operation is
// missing any of these.
//
//   x-rate-cost          integer  GCRA token cost; 0 is valid (probes only).
//   x-tier-required      string   Dormant until Phase 20; must be declared.
//   x-idempotent-mutation bool    Drives the Idempotency-Key requirement.
var requiredExtensions = []string{
	"x-rate-cost",
	"x-tier-required",
	"x-idempotent-mutation",
}

// httpMethods is the set of OpenAPI path-item keys that represent HTTP methods.
var httpMethods = map[string]bool{
	"get": true, "post": true, "put": true,
	"patch": true, "delete": true, "head": true, "options": true,
}

// ValidateSpecExtensions parses an OpenAPI 3.x YAML payload and checks that
// every operation (path × method) carries all three required Phase 9
// extensions. Returns a descriptive error listing every violation so the
// operator can fix them all in one pass rather than iterating one-by-one.
//
// Designed to accept raw bytes so it can be called from main (with the
// embedded spec) AND from unit tests (with inline YAML fixtures).
func ValidateSpecExtensions(data []byte) error {
	var doc map[string]any
	if err := yaml.Unmarshal(data, &doc); err != nil {
		return fmt.Errorf("spec_loader: YAML parse: %w", err)
	}

	pathsAny, ok := doc["paths"]
	if !ok {
		return fmt.Errorf("spec_loader: openapi.yaml has no 'paths' key")
	}
	paths, ok := pathsAny.(map[string]any)
	if !ok {
		return fmt.Errorf("spec_loader: openapi.yaml 'paths' is not a map")
	}

	var violations []string
	// Sort paths for deterministic error output.
	routeKeys := make([]string, 0, len(paths))
	for r := range paths {
		routeKeys = append(routeKeys, r)
	}
	sort.Strings(routeKeys)

	for _, route := range routeKeys {
		pathItemAny := paths[route]
		pathItem, ok := pathItemAny.(map[string]any)
		if !ok {
			continue
		}
		for method, opAny := range pathItem {
			if !httpMethods[method] {
				continue
			}
			op, ok := opAny.(map[string]any)
			if !ok {
				violations = append(violations, fmt.Sprintf("%s %s: operation is not a map", method, route))
				continue
			}
			for _, ext := range requiredExtensions {
				if _, present := op[ext]; !present {
					violations = append(violations,
						fmt.Sprintf("%s %s: missing required extension %q", method, route, ext),
					)
				}
			}
		}
	}

	if len(violations) > 0 {
		sort.Strings(violations)
		return fmt.Errorf("spec_loader: %d route(s) missing required extensions:\n  %s",
			len(violations), joinViolations(violations))
	}
	return nil
}

// BootValidateSpec is the boot-time gate called from cmd/api/main.go.
// It validates the embedded canonical OpenAPI spec. The binary refuses to
// start if any operation lacks a required Phase 9 extension.
func BootValidateSpec() error {
	return ValidateSpecExtensions(openapi.EmbeddedSpec)
}

func joinViolations(vv []string) string {
	out := ""
	for i, v := range vv {
		if i > 0 {
			out += "\n  "
		}
		out += v
	}
	return out
}
