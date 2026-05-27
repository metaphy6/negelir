package main

import (
	"testing"
)

// TestWireAuthorityPhase9Topics verifies that the swarmctl static wire-authority
// map declares the three Phase 9 §9.5 topics with their correct sole producer.
//
// This is the Go-side companion to the Python boundary test
// `test_api_topic_v1_allowed_producers_constant` and the new
// `test_predict_cancel_v1_allowed_producers_constant` in
// `ai/swarm/agents/tests/test_boundary_discipline.py`.
//
// The assertions mirror the Python `wire_contracts.py` constants:
//
//	API_TOPIC_V1_ALLOWED_PRODUCERS     = frozenset({"api.gateway.v1"})
//	PREDICT_CANCEL_V1_ALLOWED_PRODUCERS = frozenset({"api.gateway.v1"})
func TestWireAuthorityPhase9Topics(t *testing.T) {
	required := map[string]string{
		"api.request.v1":   "api.gateway.v1",
		"api.response.v1":  "api.gateway.v1",
		"predict.cancel.v1": "api.gateway.v1",
	}
	for topic, wantProducer := range required {
		got, ok := wireAuthorityProducers[topic]
		if !ok {
			t.Errorf("wireAuthorityProducers missing topic %q (Phase 9 §9.5 requires it)", topic)
			continue
		}
		if got != wantProducer {
			t.Errorf("wireAuthorityProducers[%q] = %q; want %q", topic, got, wantProducer)
		}
	}
}

// TestWireAuthorityAllGatewayOwned verifies every entry in wireAuthorityProducers
// uses "api.gateway.v1" as the producer — the gateway is currently the only
// wire-authority-pinned producer. If a second non-gateway topic is added, it
// must update this test with an explicit allow-list entry.
func TestWireAuthorityAllGatewayOwned(t *testing.T) {
	const gatewayProducer = "api.gateway.v1"
	for topic, producer := range wireAuthorityProducers {
		if producer != gatewayProducer {
			t.Errorf("wireAuthorityProducers[%q] = %q; all current entries must be %q. "+
				"If adding a non-gateway topic, update this test with an explicit allow-list.",
				topic, producer, gatewayProducer)
		}
	}
}

// TestStaticAgentManifestGatewayShim verifies that api.gateway.v1 is in the
// static agent manifest so `swarmctl ps` always shows the gateway shim.
// Phase 9 §9.13 DoD: the gateway must appear in ps output regardless of
// whether a live dynamic registry entry exists in Redis.
func TestStaticAgentManifestGatewayShim(t *testing.T) {
	const wantID = "api.gateway.v1"
	wantSubs := map[string]bool{"predict.request.v1": true}
	wantPubs := map[string]bool{
		"api.request.v1":   true,
		"api.response.v1":  true,
		"predict.cancel.v1": true,
	}

	var found *staticAgentSpec
	for i := range staticAgentManifest {
		if staticAgentManifest[i].id == wantID {
			found = &staticAgentManifest[i]
			break
		}
	}
	if found == nil {
		t.Fatalf("staticAgentManifest missing %q (Phase 9 §9.13 requires it)", wantID)
	}
	if found.row.Name != wantID {
		t.Errorf("row.Name = %q; want %q", found.row.Name, wantID)
	}
	if found.hbKey != "agent:api.gateway.v1:heartbeat" {
		t.Errorf("hbKey = %q; want \"agent:api.gateway.v1:heartbeat\"", found.hbKey)
	}
	for _, s := range found.row.Subscribes {
		if str, ok := s.(string); ok && !wantSubs[str] {
			t.Errorf("unexpected subscribe topic %q", str)
		}
	}
	for _, p := range found.row.Publishes {
		if str, ok := p.(string); ok && !wantPubs[str] {
			t.Errorf("unexpected publish topic %q", str)
		}
	}
	for topic := range wantPubs {
		found := false
		for _, p := range staticAgentManifest[0].row.Publishes {
			if str, ok := p.(string); ok && str == topic {
				found = true
				break
			}
		}
		if !found {
			t.Errorf("api.gateway.v1 publish topics missing %q", topic)
		}
	}
}
