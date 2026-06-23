package config

import (
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"testing"
)

// envExamplePath returns the absolute path to the repo's
// xops/env/.env.example, walking up from this file until the repo root
// (identified by the xops/env directory) is found.
func envExamplePath(t *testing.T) string {
	t.Helper()
	dir, err := os.Getwd()
	if err != nil {
		t.Fatalf("getwd: %v", err)
	}
	for i := 0; i < 8; i++ {
		candidate := filepath.Join(dir, "xops", "env", ".env.example")
		if _, err := os.Stat(candidate); err == nil {
			return candidate
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			break
		}
		dir = parent
	}
	t.Fatalf("xops/env/.env.example not found walking up from %s", dir)
	return ""
}

// envKeyRE matches the key on a `KEY=value` line.
var envKeyRE = regexp.MustCompile(`(?m)^([A-Z][A-Z0-9_]*)=`)

// sharedKeyRE matches `KEY=...   # shared` (with any spaces before the marker).
var sharedKeyRE = regexp.MustCompile(`(?m)^([A-Z][A-Z0-9_]*)=[^\n]*#\s*shared\b`)

func parseEnvExample(t *testing.T) (allKeys, sharedKeys map[string]struct{}) {
	t.Helper()
	body, err := os.ReadFile(envExamplePath(t))
	if err != nil {
		t.Fatalf("read .env.example: %v", err)
	}
	all := map[string]struct{}{}
	for _, m := range envKeyRE.FindAllStringSubmatch(string(body), -1) {
		all[m[1]] = struct{}{}
	}
	shared := map[string]struct{}{}
	for _, m := range sharedKeyRE.FindAllStringSubmatch(string(body), -1) {
		shared[m[1]] = struct{}{}
	}
	return all, shared
}

// TestEnvSync — every env key the Go Config binds must be documented in
// .env.example. This is the Go-side counterpart of the Python test in
// tests/test_config_sync.py.
func TestEnvSync(t *testing.T) {
	docs, _ := parseEnvExample(t)
	var missing []string
	for _, k := range EnvKeys() {
		if _, ok := docs[k]; !ok {
			missing = append(missing, k)
		}
	}
	if len(missing) > 0 {
		sort.Strings(missing)
		t.Fatalf("Go Config binds keys missing from .env.example: %v", missing)
	}
}

// TestSharedKeysAreMarked — any key consumed by both the Go server *and* the
// Python AI must carry a `# shared` comment in .env.example. Without that
// marker, the meta-test in test_config_sync.py will flag the key as
// "double-owned" (per ROADMAP §1.3).
//
// This test enumerates the canonical Python-owned env vars (those read in
// common/config/ai_pipeline.py) by scanning the source file at test time.
func TestSharedKeysAreMarked(t *testing.T) {
	docs, shared := parseEnvExample(t)

	// envExamplePath returns .../xops/env/.env.example; the repo root is
	// three levels up.
	root := filepath.Dir(filepath.Dir(filepath.Dir(envExamplePath(t))))
	pyPath := filepath.Join(root, "common", "config", "ai_pipeline.py")
	pyBody, err := os.ReadFile(pyPath)
	if err != nil {
		t.Fatalf("read %s: %v", pyPath, err)
	}
	pyKeyRE := regexp.MustCompile(`os\.getenv\(\s*["']([A-Z][A-Z0-9_]*)["']`)
	pyKeys := map[string]struct{}{}
	for _, m := range pyKeyRE.FindAllStringSubmatch(string(pyBody), -1) {
		pyKeys[m[1]] = struct{}{}
	}

	var unmarked []string
	for _, k := range EnvKeys() {
		if _, ok := pyKeys[k]; !ok {
			continue // Go-only, no marker required.
		}
		if _, ok := docs[k]; !ok {
			continue // already flagged by TestEnvSync.
		}
		if _, ok := shared[k]; !ok {
			unmarked = append(unmarked, k)
		}
	}
	if len(unmarked) > 0 {
		sort.Strings(unmarked)
		t.Fatalf("env keys read by BOTH Go and Python but missing `# shared` in .env.example: %s",
			strings.Join(unmarked, ", "))
	}
}
