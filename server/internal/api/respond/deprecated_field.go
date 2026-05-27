// Package respond provides Phase 9 §9.11 response-shaping helpers.
//
// Field-level deprecation convention: when a response field is marked
// deprecated in the OpenAPI spec (x-deprecated-field extension), the handler
// uses WithDeprecatedSibling to add <fieldName>_deprecated: true alongside
// the original field. The sibling is present for one minor version; the field
// and its sibling are both removed in the following minor.
package respond

import "encoding/json"

// WithDeprecatedSibling converts response to a flat map[string]any and adds
// <fieldName>_deprecated: true alongside the deprecated field value.
//
// Usage:
//
//	c.JSON(200, respond.WithDeprecatedSibling(myStruct, "old_field"))
//
// The caller is responsible for ensuring fieldName is the exact JSON key of
// the deprecated field in the serialised response. The original response is
// never mutated.
func WithDeprecatedSibling(response any, fieldName string) map[string]any {
	m := toFlatMap(response)
	m[fieldName+"_deprecated"] = true
	return m
}

// toFlatMap converts v to map[string]any via JSON round-trip.
// Fast path: when v is already map[string]any the map is shallow-copied so
// the caller's original is never mutated.
func toFlatMap(v any) map[string]any {
	if m, ok := v.(map[string]any); ok {
		out := make(map[string]any, len(m)+1)
		for k, val := range m {
			out[k] = val
		}
		return out
	}
	b, err := json.Marshal(v)
	if err != nil {
		return map[string]any{}
	}
	var m map[string]any
	if err := json.Unmarshal(b, &m); err != nil {
		return map[string]any{}
	}
	return m
}
