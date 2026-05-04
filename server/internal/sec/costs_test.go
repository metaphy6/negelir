package sec

import (
	"strings"
	"testing"
)

func TestEndpointCostsLoadFromEmbedded(t *testing.T) {
	m, err := LoadEndpointCosts(EmbeddedEndpointCostsYAML)
	if err != nil {
		t.Fatalf("load embedded: %v", err)
	}
	if m.DefaultCost() < 0 {
		t.Fatalf("default cost negative: %d", m.DefaultCost())
	}
	// Sanity: at least the patterns we know we shipped.
	expected := []string{
		"/v1/healthz",
		"/v1/auth/login",
		"/v1/matches/:id/predictions",
		"/v1/qa",
	}
	for _, p := range expected {
		c, ok := m.CostFor(p)
		if !ok {
			t.Fatalf("expected explicit entry for %s, got default fallback (cost=%d)", p, c)
		}
	}
}

func TestEndpointCostsRejectVersion(t *testing.T) {
	_, err := LoadEndpointCosts([]byte("default_cost: 1\ncosts: []\n"))
	if err == nil || !strings.Contains(err.Error(), "version") {
		t.Fatalf("expected version error, got %v", err)
	}
}

func TestEndpointCostsRejectNegativeDefault(t *testing.T) {
	_, err := LoadEndpointCosts([]byte("version: 1\ndefault_cost: -1\ncosts: []\n"))
	if err == nil || !strings.Contains(err.Error(), "default_cost") {
		t.Fatalf("expected default_cost error, got %v", err)
	}
}

func TestEndpointCostsRejectNegativeCost(t *testing.T) {
	body := []byte(`version: 1
default_cost: 1
costs:
  - pattern: "/v1/foo"
    cost: -2
`)
	_, err := LoadEndpointCosts(body)
	if err == nil || !strings.Contains(err.Error(), "cost") {
		t.Fatalf("expected cost error, got %v", err)
	}
}

func TestEndpointCostsRejectDuplicate(t *testing.T) {
	body := []byte(`version: 1
default_cost: 1
costs:
  - pattern: "/v1/foo"
    cost: 1
  - pattern: "/v1/foo"
    cost: 2
`)
	_, err := LoadEndpointCosts(body)
	if err == nil || !strings.Contains(err.Error(), "duplicate") {
		t.Fatalf("expected duplicate error, got %v", err)
	}
}

func TestEndpointCostsRejectEmptyPattern(t *testing.T) {
	body := []byte(`version: 1
default_cost: 1
costs:
  - pattern: ""
    cost: 1
`)
	_, err := LoadEndpointCosts(body)
	if err == nil || !strings.Contains(err.Error(), "pattern") {
		t.Fatalf("expected pattern error, got %v", err)
	}
}

func TestCostForFallback(t *testing.T) {
	m, err := LoadEndpointCosts([]byte(`version: 1
default_cost: 7
costs:
  - pattern: "/v1/foo"
    cost: 3
`))
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if c, ok := m.CostFor("/v1/foo"); !ok || c != 3 {
		t.Fatalf("explicit /v1/foo => %d ok=%v", c, ok)
	}
	if c, ok := m.CostFor("/v1/unknown"); ok || c != 7 {
		t.Fatalf("unknown fallback => %d ok=%v (want 7,false)", c, ok)
	}
}

func TestCostForExplicitZero(t *testing.T) {
	m, _ := LoadEndpointCosts([]byte(`version: 1
default_cost: 5
costs:
  - pattern: "/v1/healthz"
    cost: 0
`))
	if c, ok := m.CostFor("/v1/healthz"); !ok || c != 0 {
		t.Fatalf("explicit zero must report ok=true and cost=0, got %d ok=%v", c, ok)
	}
}

// TestCheckTotalityHappyPath — every router pattern explicitly mapped.
func TestCheckTotalityHappyPath(t *testing.T) {
	m, _ := LoadEndpointCosts([]byte(`version: 1
default_cost: 1
costs:
  - pattern: "/v1/healthz"
    cost: 0
  - pattern: "/v1/qa"
    cost: 5
`))
	missing := m.CheckTotality([]string{"/v1/healthz", "/v1/qa"}, nil)
	if len(missing) != 0 {
		t.Fatalf("expected no missing, got %v", missing)
	}
}

// TestCheckTotalityFlagsSilentFreeRoutes — a router pattern with no
// explicit entry and no allow-list spot is reported. This is the
// binding §7.6 "endpoint cost mapping is total" gate.
func TestCheckTotalityFlagsSilentFreeRoutes(t *testing.T) {
	m, _ := LoadEndpointCosts([]byte(`version: 1
default_cost: 1
costs:
  - pattern: "/v1/healthz"
    cost: 0
`))
	missing := m.CheckTotality([]string{"/v1/healthz", "/v1/secret"}, nil)
	if len(missing) != 1 || missing[0] != "/v1/secret" {
		t.Fatalf("expected /v1/secret reported, got %v", missing)
	}
}

func TestCheckTotalityAllowFallback(t *testing.T) {
	m, _ := LoadEndpointCosts([]byte(`version: 1
default_cost: 1
costs: []
`))
	missing := m.CheckTotality([]string{"/v1/foo"}, []string{"/v1/foo"})
	if len(missing) != 0 {
		t.Fatalf("explicit allow-fallback should silence, got %v", missing)
	}
}
