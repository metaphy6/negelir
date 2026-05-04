package sec

import (
	"fmt"
	"sort"
	"strings"

	"gopkg.in/yaml.v3"
)

// EndpointCost represents one entry from `endpoint_costs.yaml`.
type EndpointCost struct {
	Pattern string
	Cost    int
}

// EndpointCostMap is the compiled, hot-swappable view of the per-
// endpoint weighted cost table. The mapping is total over the
// gateway router by construction (see TestEndpointCostMappingTotal
// in this package's test suite).
type EndpointCostMap struct {
	defaultCost int
	entries     []EndpointCost
	byPattern   map[string]int
}

type rawCostFile struct {
	Version     int            `yaml:"version"`
	DefaultCost int            `yaml:"default_cost"`
	Costs       []EndpointCost `yaml:"costs"`
}

// UnmarshalYAML for EndpointCost so we can keep the public struct
// field names while accepting the YAML's snake_case keys.
func (e *EndpointCost) UnmarshalYAML(node *yaml.Node) error {
	var raw struct {
		Pattern string `yaml:"pattern"`
		Cost    int    `yaml:"cost"`
	}
	if err := node.Decode(&raw); err != nil {
		return err
	}
	e.Pattern = raw.Pattern
	e.Cost = raw.Cost
	return nil
}

// LoadEndpointCosts parses + validates an endpoint-cost YAML payload
// (typically EmbeddedEndpointCostsYAML). Validation:
//
//   - version >= 1;
//   - default_cost >= 0;
//   - every entry has a non-empty pattern;
//   - every cost is >= 0 (zero is allowed, but reserved for trivial
//     probes — operators are expected to be deliberate);
//   - patterns are unique.
//
// Returns a fully-built EndpointCostMap; the caller is expected to
// validate router-totality separately (TestEndpointCostMappingTotal).
func LoadEndpointCosts(body []byte) (*EndpointCostMap, error) {
	var raw rawCostFile
	if err := yaml.Unmarshal(body, &raw); err != nil {
		return nil, fmt.Errorf("endpoint_costs: yaml parse: %w", err)
	}
	if raw.Version < 1 {
		return nil, fmt.Errorf("endpoint_costs: version must be >= 1, got %d", raw.Version)
	}
	if raw.DefaultCost < 0 {
		return nil, fmt.Errorf("endpoint_costs: default_cost must be >= 0, got %d", raw.DefaultCost)
	}
	seen := make(map[string]struct{}, len(raw.Costs))
	for i, e := range raw.Costs {
		if strings.TrimSpace(e.Pattern) == "" {
			return nil, fmt.Errorf("endpoint_costs[%d]: pattern is empty", i)
		}
		if e.Cost < 0 {
			return nil, fmt.Errorf("endpoint_costs[%s]: cost must be >= 0, got %d", e.Pattern, e.Cost)
		}
		if _, dup := seen[e.Pattern]; dup {
			return nil, fmt.Errorf("endpoint_costs[%s]: duplicate pattern", e.Pattern)
		}
		seen[e.Pattern] = struct{}{}
	}
	m := &EndpointCostMap{
		defaultCost: raw.DefaultCost,
		entries:     raw.Costs,
		byPattern:   make(map[string]int, len(raw.Costs)),
	}
	for _, e := range raw.Costs {
		m.byPattern[e.Pattern] = e.Cost
	}
	return m, nil
}

// CostFor looks up the cost for an exact route pattern (the Gin
// router exposes `c.FullPath()` which returns the pattern as
// registered, e.g. "/v1/matches/:id"). Returns the default cost when
// the pattern has no explicit entry.
//
// `ok` distinguishes an explicit `cost: 0` entry from the
// "unmapped → default" fallback so the gateway's totality test can
// flag silently-free routes.
func (m *EndpointCostMap) CostFor(pattern string) (cost int, ok bool) {
	if m == nil {
		return 0, false
	}
	if c, found := m.byPattern[pattern]; found {
		return c, true
	}
	return m.defaultCost, false
}

// DefaultCost returns the configured default. Useful for tests that
// want to assert "unmapped routes get exactly N".
func (m *EndpointCostMap) DefaultCost() int {
	if m == nil {
		return 0
	}
	return m.defaultCost
}

// Patterns returns the registered patterns in YAML order.
func (m *EndpointCostMap) Patterns() []string {
	if m == nil {
		return nil
	}
	out := make([]string, 0, len(m.entries))
	for _, e := range m.entries {
		out = append(out, e.Pattern)
	}
	return out
}

// PatternsSorted returns the patterns sorted alphabetically — handy
// for snapshot tests insensitive to YAML re-order.
func (m *EndpointCostMap) PatternsSorted() []string {
	out := m.Patterns()
	sort.Strings(out)
	return out
}

// CheckTotality returns the list of registered routes that have NO
// explicit cost entry. The gateway calls this with `router.Routes()`
// at startup and refuses to start when the result is non-empty
// UNLESS the operator has opted into the default-cost fallback for
// that route by adding it to `allowFallback`.
//
// Test contract (binding §7.6 "Endpoint cost mapping is total"):
// every route registered with the gateway router has either an
// explicit entry here OR is intentionally unmapped (charged
// default_cost). No route may be silently free unless an entry
// declares `cost: 0`.
//
// `routerPatterns` is the list returned by `gin.Engine.Routes()`
// reduced to `Path` strings. `allowFallback` is the (typically empty)
// allow-list of patterns that intentionally inherit `default_cost`.
func (m *EndpointCostMap) CheckTotality(routerPatterns []string, allowFallback []string) []string {
	if m == nil {
		return append([]string(nil), routerPatterns...)
	}
	allow := make(map[string]struct{}, len(allowFallback))
	for _, p := range allowFallback {
		allow[p] = struct{}{}
	}
	var missing []string
	for _, p := range routerPatterns {
		if _, ok := m.byPattern[p]; ok {
			continue
		}
		if _, ok := allow[p]; ok {
			continue
		}
		missing = append(missing, p)
	}
	sort.Strings(missing)
	return missing
}
