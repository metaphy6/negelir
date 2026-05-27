// Package mtls -- inbound server TLS configuration (SS9.17.8).
//
// InboundServerTLSConfig returns a *tls.Config for the public HTTPS listener
// with:
//
//   - TLS 1.2 minimum (TLS 1.3 also accepted -- Go default).
//   - AEAD-only cipher suite list for the TLS 1.2 path.  TLS 1.3 ciphers
//     (AES-128-GCM-SHA256, AES-256-GCM-SHA384, CHACHA20-POLY1305-SHA256) are
//     always AEAD and non-configurable in Go's crypto/tls.
//   - SessionTicketKey read from Redis "api:tls:session_ticket_key" via the
//     make api.rotate-tls-session-key operator tool.
//
// AssertHTTP2NotDisabled refuses boot when GODEBUG=http2server=0 is set,
// which would silently disable HTTP/2 on TLS listeners.
package mtls

import (
	"crypto/tls"
	"fmt"
	"os"
	"strings"
)

// PinnedCipherSuites returns the AEAD-only TLS 1.2 cipher suite IDs per
// SS9.17.8.  TLS 1.3 suites are implicitly AEAD and cannot be restricted via
// this list in Go's crypto/tls.
func PinnedCipherSuites() []uint16 {
	return []uint16{
		tls.TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256,
		tls.TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384,
		tls.TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256,
		tls.TLS_ECDHE_ECDSA_WITH_AES_256_GCM_SHA384,
		tls.TLS_ECDHE_RSA_WITH_CHACHA20_POLY1305_SHA256,
		tls.TLS_ECDHE_ECDSA_WITH_CHACHA20_POLY1305_SHA256,
	}
}

// InboundServerTLSConfig returns a *tls.Config for the public HTTPS listener.
//
// sessionTicketKey is a 32-byte key for TLS session ticket resumption.
// Pass a zero value at first boot -- Go will generate a random key internally.
// The operator rotates it every 24h via `make api.rotate-tls-session-key`,
// which writes a new random key to Redis "api:tls:session_ticket_key".
//
// SS9.17.8 -- TLS session resumption (inbound) + cipher suite pin.
func InboundServerTLSConfig(sessionTicketKey [32]byte) *tls.Config {
	cfg := &tls.Config{
		MinVersion:   tls.VersionTLS12,
		CipherSuites: PinnedCipherSuites(),
	}
	var zero [32]byte
	if sessionTicketKey != zero {
		cfg.SessionTicketKey = sessionTicketKey //nolint:staticcheck // intentional session-ticket control
	}
	return cfg
}

// AssertHTTP2NotDisabled returns a non-nil error when GODEBUG contains
// "http2server=0", which disables HTTP/2 on all TLS net/http listeners.
// Boot callers must treat this as a hard refusal to start.
//
// SS9.17.8 -- "HTTP/2 enabled on inbound: explicitly assert at boot -- no
// H2_DISABLED accidental disablement."
func AssertHTTP2NotDisabled() error {
	godebug := os.Getenv("GODEBUG")
	for _, kv := range strings.Split(godebug, ",") {
		if strings.TrimSpace(kv) == "http2server=0" {
			return fmt.Errorf(
				"SS9.17.8 HTTP/2 boot assert: GODEBUG=%q contains "+
					`"http2server=0" -- HTTP/2 is disabled on TLS listeners; `+
					"remove this GODEBUG setting to proceed",
				godebug,
			)
		}
	}
	return nil
}
