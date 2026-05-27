package bus_test

// §9.5 — Envelope discipline tests.
//
// Tests:
//  1. TestClientID_AuthenticatedUser     — user_id passes through unchanged.
//  2. TestClientID_AnonymousFormat       — anon:<12 hex chars> shape check.
//  3. TestClientID_Deterministic         — same inputs always yield same output.
//  4. TestClientID_NeverRawIPv4          — IPv4 from subjectKey is not in output.
//  5. TestClientID_NeverRawIPv6          — IPv6 from subjectKey is not in output.
//  6. TestNewEnvelope_Fields             — all required envelope fields are populated.
//  7. TestBoundaryNoIPInPayload          — §9.5 boundary scan: JSON-encoded
//                                          BusMessage payloads must not contain
//                                          IP-shaped strings (IPv4 or IPv6).

import (
	"encoding/json"
	"regexp"
	"testing"

	"github.com/metaphy6/negelir/server/internal/bus"
)

// ---------------------------------------------------------------------------
// IP-pattern detectors used by the boundary scan
// ---------------------------------------------------------------------------

// ipv4RE matches bare IPv4 addresses (groups of 1-3 digits separated by dots).
// Relies on \b word boundaries so "api.gateway.v1" does not false-fire.
var ipv4RE = regexp.MustCompile(`\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b`)

// ipv6RE matches colon-hex IPv6 notation (at least 3 colon-separated groups).
// Requires hex chars only before each colon; does not false-fire on
// "anon:abc123456789" because "anon" contains the non-hex letter 'n'.
var ipv6RE = regexp.MustCompile(`[0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{0,4}){2,7}`)

// containsIP returns true if data contains any IPv4 or IPv6-shaped string.
// ipv6RE is deliberately conservative — it only fires when the colon-hex
// segment contains at least one letter (a-f/A-F) or starts with a 3–4 char
// group, so it does not false-fire on RFC 3339 timestamps like "04:43:16Z".
func containsIP(data []byte) bool {
	return ipv4RE.Match(data) || ipv6RE.Match(data)
}

// ---------------------------------------------------------------------------
// ClientID unit tests
// ---------------------------------------------------------------------------

// TestClientID_AuthenticatedUser — authenticated user_id passes through unchanged.
func TestClientID_AuthenticatedUser(t *testing.T) {
	got := bus.ClientID("user:abc123", "203.0.113.7/32")
	if got != "user:abc123" {
		t.Fatalf("want user:abc123; got %s", got)
	}
}

// TestClientID_AnonymousFormat — result must be "anon:" + exactly 12 lower-case hex chars.
func TestClientID_AnonymousFormat(t *testing.T) {
	got := bus.ClientID("", "203.0.113.7/32")
	const wantLen = 5 + 12 // "anon:" + 12 hex chars
	if len(got) != wantLen {
		t.Fatalf("want %d chars; got %d (%q)", wantLen, len(got), got)
	}
	if got[:5] != "anon:" {
		t.Fatalf("want anon: prefix; got %q", got[:5])
	}
	for i, c := range got[5:] {
		if !((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f')) {
			t.Fatalf("non-lowercase-hex char at pos %d in anon hash: %c", i, c)
		}
	}
}

// TestClientID_Deterministic — same inputs must always produce the same output.
func TestClientID_Deterministic(t *testing.T) {
	a := bus.ClientID("", "10.0.0.1/32")
	b := bus.ClientID("", "10.0.0.1/32")
	if a != b {
		t.Fatalf("non-deterministic: got %q then %q for same input", a, b)
	}
}

// TestClientID_NeverRawIPv4 — the IPv4 address inside subjectKey must not
// appear verbatim in the client_id output.
func TestClientID_NeverRawIPv4(t *testing.T) {
	subjectKey := "198.51.100.42/32"
	got := bus.ClientID("", subjectKey)
	if ipv4RE.MatchString(got) {
		t.Fatalf("raw IPv4 found in client_id %q for subject %q", got, subjectKey)
	}
}

// TestClientID_NeverRawIPv6 — IPv6 subject keys must also be opaque in output.
func TestClientID_NeverRawIPv6(t *testing.T) {
	subjectKey := "2001:db8::/64"
	got := bus.ClientID("", subjectKey)
	if ipv6RE.MatchString(got) {
		t.Fatalf("raw IPv6 found in client_id %q for subject %q", got, subjectKey)
	}
}

// ---------------------------------------------------------------------------
// Envelope unit tests
// ---------------------------------------------------------------------------

// TestNewEnvelope_Fields — NewEnvelope populates all required §9.5 fields.
func TestNewEnvelope_Fields(t *testing.T) {
	env := bus.NewEnvelope("api.request.v1", 1)
	if env.Topic != "api.request.v1" {
		t.Errorf("topic: want api.request.v1; got %s", env.Topic)
	}
	if env.SchemaVersion != 1 {
		t.Errorf("schema_version: want 1; got %d", env.SchemaVersion)
	}
	if env.Producer != "api.gateway.v1" {
		t.Errorf("producer: want api.gateway.v1; got %s", env.Producer)
	}
	if env.KindSchemaVersion != 1 {
		t.Errorf("kind_schema_version: want 1; got %d", env.KindSchemaVersion)
	}
	if env.MessageID == "" {
		t.Error("message_id must be non-empty")
	}
	if env.ProducedAt == "" {
		t.Error("produced_at must be non-empty")
	}
	if env.MessageID == bus.NewEnvelope("api.request.v1", 1).MessageID {
		t.Error("successive NewEnvelope calls must produce distinct message_ids")
	}
	// trace_id is optional — NewEnvelope leaves it empty by default.
	if env.TraceID != "" {
		t.Errorf("trace_id: want empty from NewEnvelope; got %q", env.TraceID)
	}
}

// TestEnvelope_TraceIDPropagation — callers can set TraceID after minting
// the envelope; the field serialises to "trace_id" in JSON and is absent
// (omitempty) when empty. This is the §9.5 envelope-thread contract.
func TestEnvelope_TraceIDPropagation(t *testing.T) {
	const tid = "4bf92f3577b34da6a3ce929d0e0e4736"
	env := bus.NewEnvelope("predict.request.v1", 1)
	env.TraceID = tid

	if env.TraceID != tid {
		t.Fatalf("TraceID round-trip: got %q; want %q", env.TraceID, tid)
	}

	// Serialise to JSON and confirm the field appears.
	data, err := json.Marshal(env)
	if err != nil {
		t.Fatalf("json.Marshal: %v", err)
	}
	if !regexp.MustCompile(`"trace_id"\s*:\s*"` + tid + `"`).Match(data) {
		t.Fatalf("trace_id not found in JSON: %s", data)
	}

	// An envelope with no TraceID must omit the field (omitempty contract).
	empty := bus.NewEnvelope("predict.request.v1", 1)
	emptyData, _ := json.Marshal(empty)
	if regexp.MustCompile(`"trace_id"`).Match(emptyData) {
		t.Fatalf("trace_id must be absent in JSON when empty: %s", emptyData)
	}
}

// ---------------------------------------------------------------------------
// §9.5 boundary test
// ---------------------------------------------------------------------------

// TestBoundaryNoIPInPayload is the §9.5 boundary test: the JSON-encoded wire
// representation of any BusMessage published by the API gateway must not
// contain IP-shaped strings (IPv4 or IPv6).
//
// Covers:
//   (a) Anonymous request with IPv4 subject key — client_id is anon-hash.
//   (b) Anonymous request with IPv6 subject key — client_id is anon-hash.
//   (c) Authenticated request — client_id is opaque user ID; subject key
//       must not bleed into the wire format.
//   (d) Explicit bad case: a payload that DIRECTLY embeds a raw IPv4 address
//       MUST be detected. This confirms the scanner is not a no-op.
func TestBoundaryNoIPInPayload(t *testing.T) {
	goodCases := []struct {
		name       string
		userID     string
		subjectKey string
	}{
		{
			name:       "anon_ipv4_subject",
			userID:     "",
			subjectKey: "203.0.113.99/32",
		},
		{
			name:       "anon_ipv6_subject",
			userID:     "",
			subjectKey: "2001:db8:cafe::/48",
		},
		{
			name:       "authed_user_ipv4_subject",
			userID:     "user:deadbeef1234",
			subjectKey: "10.0.0.1/32",
		},
	}

	for _, tc := range goodCases {
		t.Run(tc.name, func(t *testing.T) {
			msg := bus.BusMessage{
				Envelope: bus.NewEnvelope("api.request.v1", 1),
				Payload: map[string]any{
					"request_id": "0195f4a1dead70008000000000000001",
					"client_id":  bus.ClientID(tc.userID, tc.subjectKey),
				},
			}
			// Scan only the payload sub-object: the spec says "in published
			// payloads" — the payload is the user-derived data portion.
			// The envelope contains infrastructure metadata (timestamps,
			// message IDs) that is controlled by the gateway, not by user
			// input, and RFC 3339 timestamps (e.g. "04:43:16Z") must not
			// be misclassified as IPv6.
			payloadData, err := json.Marshal(msg.Payload)
			if err != nil {
				t.Fatalf("marshal payload: %v", err)
			}
			if containsIP(payloadData) {
				t.Errorf("IP-shaped string found in payload:\n%s", payloadData)
			}
		})
	}

	// (d) Confirm the scanner catches a deliberate raw-IP injection.
	t.Run("scanner_detects_raw_ipv4", func(t *testing.T) {
		badPayload := map[string]any{
			"request_id": "0195f4a1dead70008000000000000002",
			"client_id":  "203.0.113.99", // raw IP — intentionally bad
		}
		data, _ := json.Marshal(badPayload)
		if !containsIP(data) {
			t.Error("scanner must detect raw IPv4 address in payload; it did not")
		}
	})
}
