package mtls_test

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/rsa"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"math/big"
	"net"
	"os"
	"path/filepath"
	"runtime"
	"testing"
	"time"

	"github.com/metaphy6/negelir/server/internal/mtls"
)

// repoCA returns the path to the Phase 2 internal CA directory
// (infra/mock/ca/) by walking up from this test file.
func repoCADir(t *testing.T) string {
	t.Helper()
	_, file, _, _ := runtime.Caller(0)
	dir := filepath.Dir(file)
	for i := 0; i < 8; i++ {
		candidate := filepath.Join(dir, "infra", "mock", "ca")
		if _, err := os.Stat(candidate); err == nil {
			return candidate
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			break
		}
		dir = parent
	}
	t.Fatal("infra/mock/ca not found walking up from test file")
	return ""
}

// loadRepoCA parses the in-repo Phase 2 CA cert and key for test use.
func loadRepoCA(t *testing.T) (*x509.Certificate, *rsa.PrivateKey) {
	t.Helper()
	caDir := repoCADir(t)

	caPEM, err := os.ReadFile(filepath.Join(caDir, "root.crt"))
	if err != nil {
		t.Fatalf("read repo CA cert: %v", err)
	}
	block, _ := pem.Decode(caPEM)
	if block == nil {
		t.Fatal("decode repo CA cert PEM")
	}
	caCert, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		t.Fatalf("parse repo CA cert: %v", err)
	}

	keyPEM, err := os.ReadFile(filepath.Join(caDir, "root.key"))
	if err != nil {
		t.Fatalf("read repo CA key: %v", err)
	}
	keyBlock, _ := pem.Decode(keyPEM)
	if keyBlock == nil {
		t.Fatal("decode repo CA key PEM")
	}
	parsed, err := x509.ParsePKCS8PrivateKey(keyBlock.Bytes)
	if err != nil {
		t.Fatalf("parse repo CA key: %v", err)
	}
	rsaKey, ok := parsed.(*rsa.PrivateKey)
	if !ok {
		t.Fatalf("repo CA key is not RSA (got %T)", parsed)
	}
	return caCert, rsaKey
}

// issueCert generates an ECDSA key pair and issues a cert signed by the
// supplied CA, writing the cert + key PEM to tmp files.  Returns (certPath, keyPath).
func issueCert(t *testing.T, caCert *x509.Certificate, caKey *rsa.PrivateKey, cn string, isServer bool) (certPath, keyPath string) {
	t.Helper()
	priv, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatalf("generate key: %v", err)
	}
	serial, _ := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 128))
	tmpl := &x509.Certificate{
		SerialNumber: serial,
		Subject:      pkix.Name{CommonName: cn},
		NotBefore:    time.Now().Add(-time.Minute),
		NotAfter:     time.Now().Add(24 * time.Hour),
	}
	if isServer {
		tmpl.IPAddresses = []net.IP{net.ParseIP("127.0.0.1")}
		tmpl.KeyUsage = x509.KeyUsageDigitalSignature
		tmpl.ExtKeyUsage = []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth}
	} else {
		tmpl.KeyUsage = x509.KeyUsageDigitalSignature
		tmpl.ExtKeyUsage = []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth}
	}
	certDER, err := x509.CreateCertificate(rand.Reader, tmpl, caCert, &priv.PublicKey, caKey)
	if err != nil {
		t.Fatalf("create cert: %v", err)
	}

	dir := t.TempDir()
	certFile := filepath.Join(dir, cn+".crt")
	keyFile := filepath.Join(dir, cn+".key")

	certOut, _ := os.Create(certFile)
	_ = pem.Encode(certOut, &pem.Block{Type: "CERTIFICATE", Bytes: certDER})
	certOut.Close()

	keyDER, _ := x509.MarshalECPrivateKey(priv)
	keyOut, _ := os.OpenFile(keyFile, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0400)
	_ = pem.Encode(keyOut, &pem.Block{Type: "EC PRIVATE KEY", Bytes: keyDER})
	keyOut.Close()

	return certFile, keyFile
}

// startMTLSServer starts a TLS server that requires client certs verified
// against caCert.  Returns the listener address.
func startMTLSServer(t *testing.T, serverTLSCfg *tls.Config) string {
	t.Helper()
	ln, err := tls.Listen("tcp", "127.0.0.1:0", serverTLSCfg)
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	t.Cleanup(func() { _ = ln.Close() })
	go func() {
		for {
			conn, err := ln.Accept()
			if err != nil {
				return
			}
			go func(c net.Conn) {
				// Complete the TLS handshake before closing so the
				// client-side handshake does not receive an EOF.
				if tlsC, ok := c.(*tls.Conn); ok {
					_ = tlsC.Handshake()
				}
				_ = c.Close()
			}(conn)
		}
	}()
	return ln.Addr().String()
}

// TestLoadClientTLSConfig_HappyPath verifies that LoadClientTLSConfig
// succeeds when the CA cert, client cert, and client key are all valid.
func TestLoadClientTLSConfig_HappyPath(t *testing.T) {
	caCert, caKey := loadRepoCA(t)
	caDir := repoCADir(t)
	caPath := filepath.Join(caDir, "root.crt")
	clientCrt, clientKey := issueCert(t, caCert, caKey, "test-client", false)

	cfg, err := mtls.LoadClientTLSConfig(caPath, clientCrt, clientKey)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg == nil {
		t.Fatal("want non-nil tls.Config")
	}
	if len(cfg.Certificates) != 1 {
		t.Fatalf("want 1 client cert, got %d", len(cfg.Certificates))
	}
}

// TestLoadClientTLSConfig_MissingCA verifies that a missing CA path returns
// an error (not a panic or silent success).
func TestLoadClientTLSConfig_MissingCA(t *testing.T) {
	caCert, caKey := loadRepoCA(t)
	clientCrt, clientKey := issueCert(t, caCert, caKey, "test-client", false)

	_, err := mtls.LoadClientTLSConfig("/nonexistent/ca.crt", clientCrt, clientKey)
	if err == nil {
		t.Fatal("want error for missing CA, got nil")
	}
}

// TestProbeAddr_HappyPath verifies that ProbeAddr succeeds when the test TLS
// server trusts the client cert (both signed by the in-repo CA).
func TestProbeAddr_HappyPath(t *testing.T) {
	caCert, caKey := loadRepoCA(t)
	caDir := repoCADir(t)
	caPath := filepath.Join(caDir, "root.crt")

	// Server: cert signed by in-repo CA; requires client cert from in-repo CA.
	serverCrt, serverKey := issueCert(t, caCert, caKey, "test-server", true)
	serverCert, err := tls.LoadX509KeyPair(serverCrt, serverKey)
	if err != nil {
		t.Fatalf("load server cert: %v", err)
	}
	caPool := x509.NewCertPool()
	caPEM, _ := os.ReadFile(caPath)
	caPool.AppendCertsFromPEM(caPEM)

	serverTLSCfg := &tls.Config{
		Certificates: []tls.Certificate{serverCert},
		ClientCAs:    caPool,
		ClientAuth:   tls.RequireAndVerifyClientCert,
		MinVersion:   tls.VersionTLS12,
	}
	addr := startMTLSServer(t, serverTLSCfg)

	// Client: cert signed by in-repo CA.
	clientCrt, clientKey := issueCert(t, caCert, caKey, "test-client", false)
	clientTLSCfg, err := mtls.LoadClientTLSConfig(caPath, clientCrt, clientKey)
	if err != nil {
		t.Fatalf("LoadClientTLSConfig: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := mtls.ProbeAddr(ctx, addr, clientTLSCfg); err != nil {
		t.Fatalf("ProbeAddr: %v", err)
	}
}

// TestProbeAddr_WrongCA verifies that ProbeAddr returns an error when the
// client uses a CA that the server does not trust (adversarial: wrong CA).
func TestProbeAddr_WrongCA(t *testing.T) {
	caCert, caKey := loadRepoCA(t)
	caDir := repoCADir(t)
	caPath := filepath.Join(caDir, "root.crt")

	// Server: trusts in-repo CA.
	serverCrt, serverKey := issueCert(t, caCert, caKey, "test-server", true)
	serverCert, err := tls.LoadX509KeyPair(serverCrt, serverKey)
	if err != nil {
		t.Fatalf("load server cert: %v", err)
	}
	caPool := x509.NewCertPool()
	caPEM, _ := os.ReadFile(caPath)
	caPool.AppendCertsFromPEM(caPEM)

	serverTLSCfg := &tls.Config{
		Certificates: []tls.Certificate{serverCert},
		ClientCAs:    caPool,
		ClientAuth:   tls.RequireAndVerifyClientCert,
		MinVersion:   tls.VersionTLS12,
	}
	addr := startMTLSServer(t, serverTLSCfg)

	// Client: signed by a *different* ephemeral CA — handshake must fail.
	wrongCAKey, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	wrongCASerial, _ := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 128))
	wrongCATmpl := &x509.Certificate{
		SerialNumber:          wrongCASerial,
		Subject:               pkix.Name{CommonName: "wrong-ca"},
		NotBefore:             time.Now().Add(-time.Minute),
		NotAfter:              time.Now().Add(24 * time.Hour),
		IsCA:                  true,
		BasicConstraintsValid: true,
		KeyUsage:              x509.KeyUsageCertSign | x509.KeyUsageCRLSign,
	}
	wrongCACertDER, _ := x509.CreateCertificate(rand.Reader, wrongCATmpl, wrongCATmpl, &wrongCAKey.PublicKey, wrongCAKey)
	wrongCACert, _ := x509.ParseCertificate(wrongCACertDER)

	dir := t.TempDir()
	wrongCAPath := filepath.Join(dir, "wrong-ca.crt")
	f, _ := os.Create(wrongCAPath)
	_ = pem.Encode(f, &pem.Block{Type: "CERTIFICATE", Bytes: wrongCACertDER})
	f.Close()

	clientKey, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	clientSerial, _ := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 128))
	clientTmpl := &x509.Certificate{
		SerialNumber: clientSerial,
		Subject:      pkix.Name{CommonName: "wrong-ca-client"},
		NotBefore:    time.Now().Add(-time.Minute),
		NotAfter:     time.Now().Add(24 * time.Hour),
		KeyUsage:     x509.KeyUsageDigitalSignature,
		ExtKeyUsage:  []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth},
	}
	clientCertDER, _ := x509.CreateCertificate(rand.Reader, clientTmpl, wrongCACert, &clientKey.PublicKey, wrongCAKey)
	clientCertPath := filepath.Join(dir, "wrong-client.crt")
	clientKeyPath := filepath.Join(dir, "wrong-client.key")
	cf, _ := os.Create(clientCertPath)
	_ = pem.Encode(cf, &pem.Block{Type: "CERTIFICATE", Bytes: clientCertDER})
	cf.Close()
	keyDER, _ := x509.MarshalECPrivateKey(clientKey)
	kf, _ := os.OpenFile(clientKeyPath, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0400)
	_ = pem.Encode(kf, &pem.Block{Type: "EC PRIVATE KEY", Bytes: keyDER})
	kf.Close()

	wrongPool := x509.NewCertPool()
	wrongPool.AppendCertsFromPEM(wrongCACertDER) // not a PEM but the test validates the error path
	wrongCACertPEM, _ := os.ReadFile(wrongCAPath)
	wrongPool2 := x509.NewCertPool()
	wrongPool2.AppendCertsFromPEM(wrongCACertPEM)
	wrongClientTLSCfg := &tls.Config{
		Certificates: func() []tls.Certificate {
			c, _ := tls.LoadX509KeyPair(clientCertPath, clientKeyPath)
			return []tls.Certificate{c}
		}(),
		RootCAs:    wrongPool2, // also wrong: server cert signed by in-repo CA
		MinVersion: tls.VersionTLS12,
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	err = mtls.ProbeAddr(ctx, addr, wrongClientTLSCfg)
	if err == nil {
		t.Fatal("want error for wrong CA, got nil")
	}
}

// TestCheckKeyModes verifies that CheckKeyModes returns an error when a key
// file has wrong permissions.
func TestCheckKeyModes(t *testing.T) {
	caCert, caKey := loadRepoCA(t)
	_, redisKey := issueCert(t, caCert, caKey, "redis", false)
	_, pgKey := issueCert(t, caCert, caKey, "pg", false)
	_, busKey := issueCert(t, caCert, caKey, "bus", false)

	certs := mtls.ServiceCerts{
		RedisKey: redisKey,
		PgKey:    pgKey,
		BusKey:   busKey,
	}

	// All keys are written at 0400 by issueCert — should pass.
	if err := mtls.CheckKeyModes(certs); err != nil {
		t.Fatalf("unexpected error for 0400 keys: %v", err)
	}

	// Widen one key's permissions — should now fail.
	if err := os.Chmod(pgKey, 0644); err != nil {
		t.Fatalf("chmod: %v", err)
	}
	if err := mtls.CheckKeyModes(certs); err == nil {
		t.Fatal("want error for 0644 key, got nil")
	}
}

// TestCertsFromDir verifies that CertsFromDir produces the expected paths.
func TestCertsFromDir(t *testing.T) {
	dir := "/data/api/tls"
	certs := mtls.CertsFromDir(dir)

	for name, got := range map[string]string{
		"CA":       certs.CA,
		"RedisCrt": certs.RedisCrt,
		"RedisKey": certs.RedisKey,
		"PgCrt":    certs.PgCrt,
		"PgKey":    certs.PgKey,
		"BusCrt":   certs.BusCrt,
		"BusKey":   certs.BusKey,
	} {
		if filepath.Dir(got) != dir {
			t.Errorf("%s = %q, want dir prefix %q", name, got, dir)
		}
	}
}
