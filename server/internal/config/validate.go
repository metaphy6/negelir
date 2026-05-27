// Package config — §9.12 boot validator.
//
// ValidateBoot performs startup-time checks that require filesystem access or
// wall-clock comparisons. Load() calls this after Validate() passes.
//
// §9.12 boot-validator contract — all five checks:
//   (a) timeout chain inequality         — enforced by Validate(); not duplicated here.
//   (b) bcrypt cost >= 10                — enforced by Validate(); not duplicated here.
//   (c) api_request_timeout_ms >= 100   — enforced here (absolute floor).
//   (d) TLS certs present, readable, notAfter >= now+7d — enforced here (mTLS only).
//   (e) JWT keystore >= 1 .pub.pem file — enforced here (skipped if dir absent).
package config

import (
	"crypto/x509"
	"encoding/pem"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// ValidateBoot performs startup-time checks on cfg that require filesystem
// access or wall-clock comparisons. Load() calls this after Validate() passes.
//
// Checks enforced here (§9.12 bullets c-e):
//
//   (c) APIRequestTimeoutMs >= 100 ms — absolute floor independent of chain values.
//   (d) Every *.crt file in APITLSDir must exist, be readable, and not expire
//       within 7 days. Only runs when APIMTLSEnabled is true.
//   (e) APIJWTKeyDir must contain at least one *.pub.pem file if the directory
//       already exists on disk; absent dir = bootstrap not yet run, skip silently.
//
// Checks (a) and (b) are enforced by Validate() and are not repeated here.
func ValidateBoot(cfg *Config) error {
	// (c) Absolute floor on the API request timeout.
	if cfg.APIRequestTimeoutMs < 100 {
		return fmt.Errorf(
			"NEGELIR_API_REQUEST_TIMEOUT_MS=%d must be >= 100 ms (absolute boot floor)",
			cfg.APIRequestTimeoutMs,
		)
	}

	// (d) TLS cert expiry — only when mTLS is enabled.
	if cfg.APIMTLSEnabled && cfg.APITLSDir != "" {
		if err := validateTLSDir(cfg.APITLSDir); err != nil {
			return err
		}
	}

	// (e) JWT keystore must contain >= 1 public key file when the dir exists.
	if cfg.APIJWTKeyDir != "" {
		if err := validateJWTKeyDir(cfg.APIJWTKeyDir); err != nil {
			return err
		}
	}

	return nil
}

// validateTLSDir scans dir for all *.crt PEM files and refuses boot if any
// certificate is unreadable or expires within 7 days.
func validateTLSDir(dir string) error {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return fmt.Errorf("NEGELIR_API_TLS_DIR=%q: cannot read directory: %w", dir, err)
	}

	horizon := time.Now().Add(7 * 24 * time.Hour)
	checked := 0
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".crt") {
			continue
		}
		path := filepath.Join(dir, e.Name())
		data, readErr := os.ReadFile(path)
		if readErr != nil {
			return fmt.Errorf("NEGELIR_API_TLS_DIR: cannot read cert %q: %w", path, readErr)
		}
		if parseErr := checkPEMCerts(path, data, horizon); parseErr != nil {
			return parseErr
		}
		checked++
	}

	if checked == 0 {
		return fmt.Errorf(
			"NEGELIR_API_TLS_DIR=%q: no *.crt files found but NEGELIR_API_MTLS_ENABLED=true",
			dir,
		)
	}
	return nil
}

// checkPEMCerts parses all CERTIFICATE PEM blocks in data and returns an error
// if any certificate expires before horizon.
func checkPEMCerts(path string, data []byte, horizon time.Time) error {
	rest := data
	found := false
	for {
		var block *pem.Block
		block, rest = pem.Decode(rest)
		if block == nil {
			break
		}
		if block.Type != "CERTIFICATE" {
			continue
		}
		cert, parseErr := x509.ParseCertificate(block.Bytes)
		if parseErr != nil {
			return fmt.Errorf("cert %q: cannot parse DER block: %w", path, parseErr)
		}
		found = true
		if cert.NotAfter.Before(horizon) {
			return fmt.Errorf(
				"cert %q (subject %q): expires %s — less than 7 days from now; rotate before booting",
				path, cert.Subject.CommonName, cert.NotAfter.UTC().Format(time.RFC3339),
			)
		}
	}
	if !found {
		return fmt.Errorf("cert %q: no CERTIFICATE PEM block found", path)
	}
	return nil
}

// validateJWTKeyDir ensures the JWT key-store directory contains at least one
// *.pub.pem file. If the directory does not exist on disk the check is skipped
// silently — bootstrap has not run yet (that is make api.init's job).
func validateJWTKeyDir(dir string) error {
	entries, err := os.ReadDir(dir)
	if os.IsNotExist(err) {
		return nil // bootstrap not yet run — skip
	}
	if err != nil {
		return fmt.Errorf("NEGELIR_API_JWT_KEY_DIR=%q: cannot read directory: %w", dir, err)
	}

	for _, e := range entries {
		if !e.IsDir() && strings.HasSuffix(e.Name(), ".pub.pem") {
			return nil // at least one active public key exists
		}
	}

	return fmt.Errorf(
		"NEGELIR_API_JWT_KEY_DIR=%q: directory exists but contains no *.pub.pem files; run `make api.init` to bootstrap the key-store",
		dir,
	)
}
