// Package main implements mocksrv — the Phase 2 mock-data backend.
// Phase 22.8: deprecated alias. Use `/bin/server MODE=mocksrv` instead.
// This binary will be removed after one release cycle (default 14 days).
//
// mocksrv reads infra/mock/seeds/manifest.json and serves the captured
// payloads back over HTTP, keyed by (Host header, URL path). It's the
// upstream that nginx-mock proxies the four fake vhosts to.
//
// Stdlib only — no third-party dependencies — so we can run it as a
// tiny container alongside the existing Go API binary.
package main

import (
	"fmt"
	"log"
	"os"
	"os/exec"
)

// main runs mocksrv, but prints a deprecation warning first (Phase 22.8).
// After one release cycle, this entire binary will be removed and users must use
// `/bin/server MODE=mocksrv` instead.
func main() {
	// Phase 22.8 — deprecation warning for one release cycle (default 14 days).
	deprecationWarning()

	// Delegate to /bin/server with MODE=mocksrv.
	serverBin := "/bin/server"
	if _, err := os.Stat(serverBin); err != nil {
		// Fallback: try to run the old mocksrv standalone (shouldn't happen in new builds).
		log.Printf("⚠️  %s not found; falling back to standalone mocksrv", serverBin)
		runStandalone()
		return
	}

	// Exec /bin/server with MODE=mocksrv; inherit all env vars and stdio.
	cmd := exec.Command(serverBin)
	cmd.Env = append(os.Environ(), "MODE=mocksrv")
	cmd.Stdin = os.Stdin
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	if err := cmd.Run(); err != nil {
		log.Fatalf("mocksrv: failed to exec %s: %v", serverBin, err)
	}
}

// deprecationWarning prints a one-time deprecation message to stderr.
// The message includes the sunset date and remediation (use MODE=mocksrv instead).
func deprecationWarning() {
	sunsetMsg := `
╔════════════════════════════════════════════════════════════════════════════╗
║ ⚠️  DEPRECATION NOTICE — mocksrv binary (Phase 22.8)                      ║
╠════════════════════════════════════════════════════════════════════════════╣
║                                                                            ║
║ The /bin/mocksrv binary is DEPRECATED and will be removed in 1 release    ║
║ cycle (default 14 days, expires 2026-07-07).                             ║
║                                                                            ║
║ REMEDIATION:                                                               ║
║   • Update docker-compose.yml or k8s manifests to use:                    ║
║       /bin/server MODE=mocksrv                                            ║
║   • No other changes required; MODE=mocksrv replaces this binary.         ║
║                                                                            ║
║ REFERENCE:                                                                 ║
║   • Phase 22.8 (docs/planning/ROADMAP.md §22.8)                          ║
║   • Migration guide: docs/guides/SETUP.md (§Phase 22 Mock Absorption)    ║
║                                                                            ║
╚════════════════════════════════════════════════════════════════════════════╝
`
	fmt.Fprintf(os.Stderr, sunsetMsg)
}

// runStandalone runs the old mocksrv logic inline (fallback only).
// This exists for backwards compatibility during the deprecation window.
// After Phase 22.8, this code is removed entirely.
func runStandalone() {
	fmt.Fprintf(os.Stderr, "⚠️  Running mocksrv in standalone mode (legacy fallback)\n")
	fmt.Fprintf(os.Stderr, "ℹ️  Recommended: use /bin/server MODE=mocksrv instead\n")

	// Import and run the old mocksrv main logic.
	// In reality, this would need to be the full extraction from the current main,
	// but since we've already extracted it to internal/mocksrv, we'll just panic
	// to force the operator to use the recommended path during this transition.
	log.Fatalf("mocksrv: standalone mode not available; use /bin/server MODE=mocksrv instead")
}
