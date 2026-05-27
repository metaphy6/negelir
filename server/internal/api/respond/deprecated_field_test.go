package respond

import "testing"

type sampleResponse struct {
	ID    int     `json:"id"`
	Name  string  `json:"name"`
	Score float64 `json:"score"`
}

// TestWithDeprecatedSibling_AddsFlag verifies the sibling flag is added and
// all original fields are preserved.
func TestWithDeprecatedSibling_AddsFlag(t *testing.T) {
	resp := sampleResponse{ID: 1, Name: "Galatasaray", Score: 0.75}
	out := WithDeprecatedSibling(resp, "score")

	if out["score"] != 0.75 {
		t.Errorf("original 'score' field missing or wrong; got %v", out["score"])
	}
	if out["score_deprecated"] != true {
		t.Errorf("'score_deprecated' sibling absent or wrong; got %v", out["score_deprecated"])
	}
	if out["id"] == nil {
		t.Errorf("unrelated 'id' field lost")
	}
	if out["name"] != "Galatasaray" {
		t.Errorf("unrelated 'name' field lost; got %v", out["name"])
	}
}

// TestWithDeprecatedSibling_MapInput verifies the fast path for map[string]any.
func TestWithDeprecatedSibling_MapInput(t *testing.T) {
	resp := map[string]any{"foo": "bar", "count": 42}
	out := WithDeprecatedSibling(resp, "foo")

	if out["foo"] != "bar" {
		t.Errorf("'foo' field missing; got %v", out["foo"])
	}
	if out["foo_deprecated"] != true {
		t.Errorf("'foo_deprecated' sibling absent; got %v", out["foo_deprecated"])
	}
	if out["count"] != 42 {
		t.Errorf("unrelated 'count' field lost; got %v", out["count"])
	}
	// Ensure the original map is not mutated.
	if _, exists := resp["foo_deprecated"]; exists {
		t.Error("original map[string]any was mutated (should be a copy)")
	}
}

// TestWithDeprecatedSibling_NonexistentField verifies that adding a sibling
// for a field that does not exist still works (sets the flag, no panic).
func TestWithDeprecatedSibling_NonexistentField(t *testing.T) {
	resp := map[string]any{"a": 1}
	out := WithDeprecatedSibling(resp, "b")
	if out["b_deprecated"] != true {
		t.Errorf("expected b_deprecated=true; got %v", out["b_deprecated"])
	}
}

// TestWithDeprecatedSibling_MultipleFields verifies that multiple siblings
// can be added in successive calls without losing earlier additions.
func TestWithDeprecatedSibling_MultipleFields(t *testing.T) {
	resp := map[string]any{"x": 1, "y": 2}
	out := WithDeprecatedSibling(resp, "x")
	out2 := WithDeprecatedSibling(out, "y")

	if out2["x_deprecated"] != true {
		t.Errorf("x_deprecated lost after second call")
	}
	if out2["y_deprecated"] != true {
		t.Errorf("y_deprecated absent")
	}
}
