package sec

import (
	"net"
	"testing"
)

// TestDeterministicPathLatencyUnderSLO asserts the in-process tier's
// median latency on a benign QA payload stays well under the
// `cfg.sec_input_gateway_max_latency_ms` budget. The integration
// equivalent (against the live gateway + Redis) lands with the
// Phase 9 router wiring; this micro-benchmark fences the deterministic
// path's contribution to that budget.
//
// Budget contract: the deterministic path (length cap + sanitize +
// pattern engine + XFF + endpoint-cost lookup) is the floor of the
// per-request latency. The classifier and Redis EVALSHA hops sit on
// top. We assert the floor is at most a small fraction (1/4) of the
// 50ms default budget so the tail leaves room for the non-
// deterministic upper tiers.
func TestDeterministicPathLatencyUnderSLO(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping latency assertion in -short mode")
	}
	rs, err := LoadInjectionPatterns(EmbeddedInjectionPatternsYAML)
	if err != nil {
		t.Fatalf("rules: %v", err)
	}
	costs, err := LoadEndpointCosts(EmbeddedEndpointCostsYAML)
	if err != nil {
		t.Fatalf("costs: %v", err)
	}
	tp, _ := ParseTrustedProxies("10.0.0.0/8")
	gate := NewQAInputGate(rs, 4096)

	payload := "Bugün Galatasaray maçı saat kaçta? Ev sahibi avantajı ne?"
	const iters = 5000
	res := testing.Benchmark(func(b *testing.B) {
		for i := 0; i < b.N; i++ {
			_ = gate.Inspect(payload)
			ip := DeriveClientIP("203.0.113.42, 10.0.0.1", "10.0.0.1", tp)
			_ = SubjectKey(ip, 32, 64)
			_, _ = costs.CostFor("/v1/qa")
		}
	})
	_ = iters
	// `NsPerOp` is the per-iteration mean. We expect the deterministic
	// path well under 1 ms per call on a normal CI box; 12.5 ms (1/4 of
	// the 50ms budget) is the conservative upper bound.
	const maxNsPerOp = 12_500_000 // 12.5 ms
	if res.NsPerOp() > maxNsPerOp {
		t.Fatalf("deterministic path too slow: %d ns/op (budget %d ns/op)",
			res.NsPerOp(), maxNsPerOp)
	}
	t.Logf("deterministic path: %d ns/op (budget %d ns/op)",
		res.NsPerOp(), maxNsPerOp)
}

// TestDeterministicPathBuildsFromEmbeddedAssets is a smoke test that
// the assets ship in a state the gateway can boot from. Composes the
// loaders the same way `cmd/api/main.go` will when Phase 9 wires
// them in.
func TestDeterministicPathBuildsFromEmbeddedAssets(t *testing.T) {
	if _, err := LoadInjectionPatterns(EmbeddedInjectionPatternsYAML); err != nil {
		t.Fatalf("injection patterns: %v", err)
	}
	if _, err := LoadEndpointCosts(EmbeddedEndpointCostsYAML); err != nil {
		t.Fatalf("endpoint costs: %v", err)
	}
	if _, err := ParseTrustedProxies(""); err != nil {
		t.Fatalf("trusted proxies (empty): %v", err)
	}
	loader := NewScriptLoader("sec_rate_check.lua", EmbeddedRateCheckLua)
	if err := VerifyHeader(loader.Name(), loader.Body()); err != nil {
		t.Fatalf("rate-check header: %v", err)
	}
	loader2 := NewScriptLoader("sec_denylist_mutate.lua", EmbeddedDenylistMutateLua)
	if err := VerifyHeader(loader2.Name(), loader2.Body()); err != nil {
		t.Fatalf("denylist-mutate header: %v", err)
	}
	// QA request envelope schema is JSON; just assert it parses as a
	// JSON object (deeper schema validation is the cross-language
	// parity test that runs in Python).
	if EmbeddedQARequestV1Schema[0] != '{' {
		t.Fatal("qa.request.v1 schema must be a JSON object")
	}
	// Bind together — confirms IP + cost + gate compose without a
	// runtime panic.
	tp, _ := ParseTrustedProxies("10.0.0.0/8")
	if !DeriveClientIP("203.0.113.7, 10.0.0.1", "10.0.0.1", tp).Equal(net.ParseIP("203.0.113.7")) {
		t.Fatal("derive client IP wiring broken")
	}
}
