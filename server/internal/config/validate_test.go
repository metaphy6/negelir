package config

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"math/big"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// writeSelfSignedCert generates a minimal self-signed PEM certificate with the
// given notAfter time and writes it to dir/filename. Returns the file path.
func writeSelfSignedCert(t *testing.T, dir, filename string, notAfter time.Time) string {
	t.Helper()
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatalf("writeSelfSignedCert: generate key: %v", err)
	}
	tmpl := &x509.Certificate{
		SerialNumber: big.NewInt(1),
		Subject:      pkix.Name{CommonName: "test"},
		NotBefore:    time.Now().Add(-1 * time.Hour),
		NotAfter:     notAfter,
	}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, &key.PublicKey, key)
	if err != nil {
		t.Fatalf("writeSelfSignedCert: create cert: %v", err)
	}
	path := filepath.Join(dir, filename)
	f, err := os.Create(path)
	if err != nil {
		t.Fatalf("writeSelfSignedCert: create file: %v", err)
	}
	defer f.Close()
	if err := pem.Encode(f, &pem.Block{Type: "CERTIFICATE", Bytes: der}); err != nil {
		t.Fatalf("writeSelfSignedCert: encode pem: %v", err)
	}
	return path
}

// --- (c) APIRequestTimeoutMs >= 100 floor ---

// TestValidateBootRequestTimeoutFloorRejected — (c): ValidateBoot must reject
// APIRequestTimeoutMs < 100 regardless of timeout chain values.
func TestValidateBootRequestTimeoutFloorRejected(t *testing.T) {
	cfg := &Config{
		APIRequestTimeoutMs: 50,
		APIMTLSEnabled:      false,
		APIJWTKeyDir:        "",
	}
	if err := ValidateBoot(cfg); err == nil {
		t.Fatal("expected error for APIRequestTimeoutMs=50, got nil")
	}
}

// TestValidateBootRequestTimeoutFloorAccepts100 — (c) happy path: exactly 100 ms passes.
func TestValidateBootRequestTimeoutFloorAccepts100(t *testing.T) {
	cfg := &Config{
		APIRequestTimeoutMs: 100,
		APIMTLSEnabled:      false,
		APIJWTKeyDir:        "",
	}
	if err := ValidateBoot(cfg); err != nil {
		t.Errorf("ValidateBoot with APIRequestTimeoutMs=100 should pass, got: %v", err)
	}
}

// --- (d) TLS cert expiry ---

// TestValidateBootTLSCertExpiringSoon — (d): ValidateBoot must refuse boot when
// a *.crt in APITLSDir expires in fewer than 7 days.
func TestValidateBootTLSCertExpiringSoon(t *testing.T) {
	dir := t.TempDir()
	// Write a cert expiring in 3 days — inside the 7-day refusal window.
	writeSelfSignedCert(t, dir, "ca.crt", time.Now().Add(3*24*time.Hour))
	cfg := &Config{
		APIRequestTimeoutMs: 2500,
		APIMTLSEnabled:      true,
		APITLSDir:           dir,
		APIJWTKeyDir:        "",
	}
	if err := ValidateBoot(cfg); err == nil {
		t.Fatal("expected error for near-expiry cert, got nil")
	}
}

// TestValidateBootTLSCertValid — (d) happy path: cert expires in 30 days.
func TestValidateBootTLSCertValid(t *testing.T) {
	dir := t.TempDir()
	writeSelfSignedCert(t, dir, "ca.crt", time.Now().Add(30*24*time.Hour))
	cfg := &Config{
		APIRequestTimeoutMs: 2500,
		APIMTLSEnabled:      true,
		APITLSDir:           dir,
		APIJWTKeyDir:        "",
	}
	if err := ValidateBoot(cfg); err != nil {
		t.Errorf("ValidateBoot with valid cert should pass, got: %v", err)
	}
}

// TestValidateBootTLSMissingDir — (d): ValidateBoot must refuse when mTLS is
// enabled but the TLS directory does not exist.
func TestValidateBootTLSMissingDir(t *testing.T) {
	cfg := &Config{
		APIRequestTimeoutMs: 2500,
		APIMTLSEnabled:      true,
		APITLSDir:           filepath.Join(t.TempDir(), "nonexistent_tls"),
		APIJWTKeyDir:        "",
	}
	if err := ValidateBoot(cfg); err == nil {
		t.Fatal("expected error for missing TLS dir with mTLS enabled, got nil")
	}
}

// TestValidateBootTLSNoCerts — (d): ValidateBoot must refuse when mTLS is
// enabled and the TLS directory has no *.crt files at all.
func TestValidateBootTLSNoCerts(t *testing.T) {
	dir := t.TempDir()
	// Write a .key file but no .crt.
	os.WriteFile(filepath.Join(dir, "client.key"), []byte("key material"), 0600)
	cfg := &Config{
		APIRequestTimeoutMs: 2500,
		APIMTLSEnabled:      true,
		APITLSDir:           dir,
		APIJWTKeyDir:        "",
	}
	if err := ValidateBoot(cfg); err == nil {
		t.Fatal("expected error for TLS dir with no *.crt files, got nil")
	}
}

// TestValidateBootTLSSkippedWhenDisabled — (d): ValidateBoot must NOT check TLS
// certs when APIMTLSEnabled is false, even if the dir has expired certs.
func TestValidateBootTLSSkippedWhenDisabled(t *testing.T) {
	dir := t.TempDir()
	// Write an already-expired cert — should be ignored.
	writeSelfSignedCert(t, dir, "ca.crt", time.Now().Add(-24*time.Hour))
	cfg := &Config{
		APIRequestTimeoutMs: 2500,
		APIMTLSEnabled:      false,
		APITLSDir:           dir,
		APIJWTKeyDir:        "",
	}
	if err := ValidateBoot(cfg); err != nil {
		t.Errorf("ValidateBoot should skip TLS checks when APIMTLSEnabled=false, got: %v", err)
	}
}

// --- (e) JWT keystore ---

// TestValidateBootJWTKeyDirAbsentSkips — (e) happy path: directory does not
// exist on disk — bootstrap not yet run; check is skipped silently.
func TestValidateBootJWTKeyDirAbsentSkips(t *testing.T) {
	cfg := &Config{
		APIRequestTimeoutMs: 2500,
		APIMTLSEnabled:      false,
		APIJWTKeyDir:        filepath.Join(t.TempDir(), "nonexistent_jwt"),
	}
	if err := ValidateBoot(cfg); err != nil {
		t.Errorf("ValidateBoot with absent JWT key dir should skip, got: %v", err)
	}
}

// TestValidateBootJWTKeyDirEmptyFails — (e): directory exists but contains no
// *.pub.pem files — boot must be refused.
func TestValidateBootJWTKeyDirEmptyFails(t *testing.T) {
	dir := t.TempDir()
	// Write a private-key file only — no .pub.pem.
	os.WriteFile(filepath.Join(dir, "key-001.priv.pem"), []byte("private key material"), 0400)
	cfg := &Config{
		APIRequestTimeoutMs: 2500,
		APIMTLSEnabled:      false,
		APIJWTKeyDir:        dir,
	}
	if err := ValidateBoot(cfg); err == nil {
		t.Fatal("expected error for JWT key dir with no .pub.pem files, got nil")
	}
}

// TestValidateBootJWTKeyDirHasActiveKey — (e) happy path: directory exists and
// contains at least one *.pub.pem file.
func TestValidateBootJWTKeyDirHasActiveKey(t *testing.T) {
	dir := t.TempDir()
	os.WriteFile(filepath.Join(dir, "key-001.pub.pem"), []byte("public key material"), 0644)
	cfg := &Config{
		APIRequestTimeoutMs: 2500,
		APIMTLSEnabled:      false,
		APIJWTKeyDir:        dir,
	}
	if err := ValidateBoot(cfg); err != nil {
		t.Errorf("ValidateBoot with valid JWT key dir should pass, got: %v", err)
	}
}

// TestValidateBootJWTEmptyDirFails — (e): directory exists and is completely
// empty — boot must be refused (dir present means bootstrap ran but left no keys).
func TestValidateBootJWTEmptyDirFails(t *testing.T) {
	dir := t.TempDir()
	cfg := &Config{
		APIRequestTimeoutMs: 2500,
		APIMTLSEnabled:      false,
		APIJWTKeyDir:        dir,
	}
	if err := ValidateBoot(cfg); err == nil {
		t.Fatal("expected error for completely empty JWT key dir, got nil")
	}
}
