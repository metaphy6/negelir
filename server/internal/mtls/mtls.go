// Package mtls provides TLS configuration and boot-probe helpers for mTLS
// connections from the API to internal services (Redis, Postgres, bus).
//
// Phase 9 §9.2 — mTLS to internal services.
// All internal dials use the Phase 2 internal CA (infra/mock/ca/root.crt).
// The boot probe must succeed for every service before the public listener
// opens; a TLS handshake failure triggers a hard refusal to start (loud, so
// the process does not silently fall back to plaintext).
package mtls

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"time"
)

// ServiceCerts holds the cert file paths for every internal service the API
// dials with mTLS.  The expected layout inside APITLSDir is:
//
//	ca.crt            — Phase 2 internal CA (copy of infra/mock/ca/root.crt)
//	client_redis.crt  — client cert for Redis (cache + bus)
//	client_redis.key
//	client_pg.crt     — client cert for Postgres
//	client_pg.key
//	client_bus.crt    — client cert for the Streams bus
//	client_bus.key
type ServiceCerts struct {
	CA       string
	RedisCrt string
	RedisKey string
	PgCrt    string
	PgKey    string
	BusCrt   string
	BusKey   string
}

// CertsFromDir builds a ServiceCerts whose paths all live under dir.
func CertsFromDir(dir string) ServiceCerts {
	j := func(name string) string { return filepath.Join(dir, name) }
	return ServiceCerts{
		CA:       j("ca.crt"),
		RedisCrt: j("client_redis.crt"),
		RedisKey: j("client_redis.key"),
		PgCrt:    j("client_pg.crt"),
		PgKey:    j("client_pg.key"),
		BusCrt:   j("client_bus.crt"),
		BusKey:   j("client_bus.key"),
	}
}

// LoadClientTLSConfig builds a *tls.Config that presents the client cert to
// the server and trusts only the CA at caPath as the root authority.
// All three paths must be readable; the key file must exist at mode 0400
// in production (the boot probe validates this before dialing).
func LoadClientTLSConfig(caPath, certPath, keyPath string) (*tls.Config, error) {
	caPEM, err := os.ReadFile(caPath)
	if err != nil {
		return nil, fmt.Errorf("mtls: read CA %s: %w", caPath, err)
	}
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(caPEM) {
		return nil, fmt.Errorf("mtls: no valid CA cert in %s", caPath)
	}
	cert, err := tls.LoadX509KeyPair(certPath, keyPath)
	if err != nil {
		return nil, fmt.Errorf("mtls: load client cert %s / %s: %w", certPath, keyPath, err)
	}
	return &tls.Config{
		Certificates: []tls.Certificate{cert},
		RootCAs:      pool,
		MinVersion:   tls.VersionTLS12,
		CipherSuites: PinnedCipherSuites(),
		// §9.17.8 — TLS session resumption for outbound mTLS connections.
		// LRU cache of 1024 session tickets reduces TLS handshake round-trips
		// to PG, Redis, and the bus after the first connection.
		ClientSessionCache: tls.NewLRUClientSessionCache(1024),
	}, nil
}

// ProbeAddr verifies that a mTLS connection can be established to addr
// (host:port) using tlsCfg.  It dials, completes the TLS handshake, then
// closes without sending application data.  Any handshake failure is returned
// as a non-nil error — callers MUST refuse to bind the public listener on
// error (do not silently fall back to a plaintext connection).
//
// A 5-second dial timeout and the context deadline bound the total time.
func ProbeAddr(ctx context.Context, addr string, tlsCfg *tls.Config) error {
	const dialTimeout = 5 * time.Second

	host, _, err := net.SplitHostPort(addr)
	if err != nil {
		return fmt.Errorf("mtls probe: parse addr %s: %w", addr, err)
	}
	cfg := tlsCfg.Clone()
	if cfg.ServerName == "" {
		cfg.ServerName = host
	}

	dialer := &net.Dialer{Timeout: dialTimeout}
	tcpConn, err := dialer.DialContext(ctx, "tcp", addr)
	if err != nil {
		return fmt.Errorf("mtls probe dial %s: %w", addr, err)
	}
	tlsConn := tls.Client(tcpConn, cfg)
	if err := tlsConn.HandshakeContext(ctx); err != nil {
		_ = tcpConn.Close()
		return fmt.Errorf("mtls probe TLS handshake %s: %w", addr, err)
	}
	_ = tlsConn.Close()
	return nil
}

// checkKeyMode returns an error if keyPath is not mode 0400.
// Callers use this before dialing to give a clear error message instead of
// a confusing "permission denied" from the TLS stack.
func checkKeyMode(keyPath string) error {
	info, err := os.Stat(keyPath)
	if err != nil {
		return fmt.Errorf("mtls: stat key %s: %w", keyPath, err)
	}
	mode := info.Mode().Perm()
	if mode != 0400 {
		return fmt.Errorf("mtls: key %s has mode %04o, want 0400", keyPath, mode)
	}
	return nil
}

// CheckKeyModes validates that every private key in certs is mode 0400.
// Called during the boot probe sequence before any connection is attempted.
func CheckKeyModes(certs ServiceCerts) error {
	for _, keyPath := range []string{certs.RedisKey, certs.PgKey, certs.BusKey} {
		if err := checkKeyMode(keyPath); err != nil {
			return err
		}
	}
	return nil
}
