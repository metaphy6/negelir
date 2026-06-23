// Package bus implements the Phase 3 wire-envelope discipline for every bus
// message published by the API gateway (§9.5 binding spec).
//
// Wire shape mirrors the Python SDK JsonCodec output (swarm/sdk/codec.py)
// so swarm consumers can decode API-published messages without adaptation:
//
//	{"envelope": {...}, "payload": {...}}
//
// # Envelope fields
//
//	message_id          — random 32-hex UUID (uuid4-hex compatible)
//	topic               — Redis Stream name (e.g. "predict.cancel.v1")
//	schema_version      — always 1; consumers refuse higher values
//	produced_at         — RFC 3339 UTC timestamp
//	producer            — always "api.gateway.v1"
//	kind_schema_version — per-kind schema version; 1 for all current §9.x topics
//
// # client_id payload field
//
// Every payload published by the API gateway MUST include a client_id field.
// The value is derived via ClientID(userID, subjectKey):
//   - Authenticated:  the user ID as-is.
//   - Anonymous:      "anon:" + sha256(subjectKey)[:12 hex chars].
//     The subjectKey is the sec.SubjectKey masked form (e.g. "203.0.113.7/32"),
//     NEVER a raw IP address. Hashing it further ensures no IP-shaped string
//     can appear in the payload. See §7.6 and §9.5.
package bus

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"time"
)

// schemaVersion is the Phase 3 envelope schema version. Swarm consumers
// refuse any message whose schema_version exceeds their supported maximum.
const schemaVersion = 1

// Producer is the fixed producer identifier for all messages published by
// the API gateway. Exported so callers can reference it without repeating
// the literal string.
const Producer = "api.gateway.v1"

// Envelope is the Phase 3 per-message metadata wrapper. JSON field names
// are compatible with the Python SDK (swarm/sdk/types.py Envelope.as_dict)
// except that Go uses produced_at where Python uses created_at — the design
// doc §9.5 canonises produced_at for the Go gateway side.
type Envelope struct {
	MessageID         string `json:"message_id"`
	Topic             string `json:"topic"`
	SchemaVersion     int    `json:"schema_version"`
	ProducedAt        string `json:"produced_at"`
	Producer          string `json:"producer"`
	KindSchemaVersion int    `json:"kind_schema_version"`
	// TraceID is the 32-hex W3C trace_id component extracted from the incoming
	// Traceparent header (§9.5). It is set by callers via
	//   env.TraceID = middleware.ContextKeyTraceID value from the Gin context
	// so the trace threads through predict.request → vote → final → approved
	// → api.response.v1 without a separate correlation-ID lookup.
	// omitempty ensures backward compatibility: messages published without
	// trace context omit the field entirely.
	TraceID string `json:"trace_id,omitempty"`
}

// BusMessage is the top-level wire object: {"envelope": {...}, "payload": {...}}.
// It mirrors the Python SDK JsonCodec shape exactly so swarm agents can decode
// API-originated messages without adaptation.
type BusMessage struct {
	Envelope Envelope       `json:"envelope"`
	Payload  map[string]any `json:"payload"`
}

// NewEnvelope mints a fresh Envelope for topic.
//
//   - topic             — Redis Stream key (e.g. "predict.cancel.v1").
//   - kindSchemaVersion — per-kind schema revision; use 1 for all current
//     §9.x topics; bump only on backward-incompatible kind schema changes.
func NewEnvelope(topic string, kindSchemaVersion int) Envelope {
	return Envelope{
		MessageID:         newMessageID(),
		Topic:             topic,
		SchemaVersion:     schemaVersion,
		ProducedAt:        utcNow(),
		Producer:          Producer,
		KindSchemaVersion: kindSchemaVersion,
	}
}

// ClientID returns the client_id payload field for a bus message published
// by the API gateway.
//
// When userID is non-empty (authenticated request), it is returned unchanged.
//
// When userID is empty (anonymous request), subjectKey (the sec.SubjectKey
// masked form, e.g. "203.0.113.7/32") is hashed with SHA-256 and the first
// 12 hex characters are returned with an "anon:" prefix:
//
//	anon:abc123456789
//
// The raw subjectKey — which contains CIDR notation including dot-separated
// octets — is NEVER written to the payload. This upholds the §7.6 / §9.5
// invariant: no IP-shaped string may appear in any published payload.
// The boundary test in envelope_test.go enforces this at CI time.
func ClientID(userID, subjectKey string) string {
	if userID != "" {
		return userID
	}
	sum := sha256.Sum256([]byte(subjectKey))
	return "anon:" + hex.EncodeToString(sum[:])[:12]
}

// newMessageID returns a 32-hex-character random message ID compatible with
// the Python SDK uuid4().hex format (no dashes, lower-case hex).
func newMessageID() string {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		// crypto/rand.Read can only fail on catastrophic OS entropy exhaustion.
		panic("bus: crypto/rand.Read failed: " + err.Error())
	}
	return fmt.Sprintf("%x", b)
}

// utcNow returns the current UTC time as an RFC 3339 string.
func utcNow() string {
	return time.Now().UTC().Format(time.RFC3339)
}
