package api_test

// §9.0 cross-phase forward contracts — boundary tests.
//
// This file asserts the contracts enumerated in docs/design/phase9/sections/
// 00-forward-phase-cross-phase-alignment.md under the "Cross-phase forward
// contracts re-asserted" bullet. Each test maps to a named section:
//
//   TestSLATimeoutConstraint  — §3.3 API request timeout ≥ full prediction path
//   TestNoSecReimplInAPIPackage — §7  API package imports sec, never re-implements it
//
// Tests are file-system / AST based and require no running service.

import (
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/metaphy6/negelir/server/internal/config"
)

// repoRoot walks up from the test working directory until AGENTS.md is found.
func repoRoot(t *testing.T) string {
	t.Helper()
	dir, err := os.Getwd()
	if err != nil {
		t.Fatalf("getwd: %v", err)
	}
	for {
		if _, err := os.Stat(filepath.Join(dir, "AGENTS.md")); err == nil {
			return dir
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			t.Fatal("could not find repo root (AGENTS.md)")
		}
		dir = parent
	}
}

// TestSLATimeoutConstraint — §3.3
//
// cfg.api_request_timeout_ms must be ≥ consensus_window_ms +
// proofreader_quorum_window_ms + api_consensus_overhead_ms + api_transit_jitter_ms.
// Config.Validate() enforces this; the test drives it from both ends.
func TestSLATimeoutConstraint(t *testing.T) {
	t.Run("defaults_satisfy_constraint", func(t *testing.T) {
		// Default config (no env overrides) must pass Validate().
		cfg, err := config.Load()
		if err != nil {
			t.Fatalf("config.Load with defaults: %v", err)
		}
		min := cfg.ConsensusWindowMs + cfg.ProofreaderQuorumWindowMs + cfg.APIConsensusOverheadMs + cfg.APITransitJitterMs
		if cfg.APIRequestTimeoutMs < min {
			t.Fatalf("default APIRequestTimeoutMs=%d < sum=%d (constraint violated at defaults)",
				cfg.APIRequestTimeoutMs, min)
		}
	})

	t.Run("too_short_timeout_rejected", func(t *testing.T) {
		// Set timeout to exactly (min - 1) and confirm Validate rejects it.
		t.Setenv("NEGELIR_API_REQUEST_TIMEOUT_MS", "1") // 1 ms < any plausible sum
		_, err := config.Load()
		if err == nil {
			t.Fatal("expected Validate to return error for NEGELIR_API_REQUEST_TIMEOUT_MS=1, got nil")
		}
		if !strings.Contains(err.Error(), "NEGELIR_API_REQUEST_TIMEOUT_MS") {
			t.Fatalf("error message should mention NEGELIR_API_REQUEST_TIMEOUT_MS, got: %v", err)
		}
	})

	t.Run("exact_minimum_accepted", func(t *testing.T) {
		// Timeout == sum of all four parts is the minimum acceptable value.
		// Use explicit env so the test is independent of default values.
		t.Setenv("NEGELIR_CONSENSUS_WINDOW_MS", "100")
		t.Setenv("NEGELIR_API_CONSENSUS_OVERHEAD_MS", "50")
		t.Setenv("NEGELIR_PROOFREADER_QUORUM_WINDOW_MS", "25")
		t.Setenv("NEGELIR_API_TRANSIT_JITTER_MS", "10")
		t.Setenv("NEGELIR_API_REQUEST_TIMEOUT_MS", "185") // == 100 + 50 + 25 + 10
		_, err := config.Load()
		if err != nil {
			t.Fatalf("exact-minimum timeout should pass Validate, got: %v", err)
		}
	})
}

// TestProfileIDResolutionBoundary — §9.15 Phase 13a forward contract
//
// Every place a profile_id is stamped on a bus envelope in the server package
// MUST route through api.ResolveProfileID.  The AST scan checks that no
// composite literal or map literal stamps a "ProfileID" or "profile_id" key
// outside of profile.go itself without calling ResolveProfileID.
func TestProfileIDResolutionBoundary(t *testing.T) {
	root := repoRoot(t)
	serverDir := filepath.Join(root, "server")

	var goFiles []string
	err := filepath.Walk(serverDir, func(path string, info os.FileInfo, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if info.IsDir() {
			return nil
		}
		if !strings.HasSuffix(path, ".go") {
			return nil
		}
		base := filepath.Base(path)
		// profile.go is the canonical home of the raw mapping; tests are excluded.
		// The calibration package uses ProfileID as a domain storage key
		// (CalibrationTable), not as a bus envelope field, so it is excluded
		// from the bus-envelope stamping check (§9.15 Phase 13a intent).
		if base == "profile.go" || strings.HasSuffix(base, "_test.go") {
			return nil
		}
		if strings.Contains(filepath.ToSlash(path), "/internal/calibration/") {
			return nil
		}
		goFiles = append(goFiles, path)
		return nil
	})
	if err != nil {
		t.Fatalf("walk server dir %s: %v", serverDir, err)
	}

	fset := token.NewFileSet()
	for _, goFile := range goFiles {
		src, readErr := os.ReadFile(goFile)
		if readErr != nil {
			t.Fatalf("read %s: %v", goFile, readErr)
		}
		f, parseErr := parser.ParseFile(fset, goFile, src, 0)
		if parseErr != nil {
			continue // skip generated / malformed files
		}
		rel := func(abs string) string {
			r, rerr := filepath.Rel(root, abs)
			if rerr != nil {
				return abs
			}
			return r
		}
		ast.Inspect(f, func(n ast.Node) bool {
			kv, ok := n.(*ast.KeyValueExpr)
			if !ok {
				return true
			}
			var keyName string
			switch k := kv.Key.(type) {
			case *ast.Ident:
				keyName = k.Name
			case *ast.BasicLit:
				keyName = strings.Trim(k.Value, `"`)
			}
			if keyName != "ProfileID" && keyName != "profile_id" {
				return true
			}
			// Value must be a call expression whose function is ResolveProfileID.
			call, callOK := kv.Value.(*ast.CallExpr)
			if !callOK {
				pos := fset.Position(kv.Pos())
				t.Errorf("§9.15 violation: %s:%d — %s stamped without calling ResolveProfileID",
					rel(goFile), pos.Line, keyName)
				return true
			}
			var fnName string
			switch fn := call.Fun.(type) {
			case *ast.Ident:
				fnName = fn.Name
			case *ast.SelectorExpr:
				fnName = fn.Sel.Name
			}
			if fnName != "ResolveProfileID" {
				pos := fset.Position(kv.Pos())
				t.Errorf("§9.15 violation: %s:%d — %s set via %s, not ResolveProfileID",
					rel(goFile), pos.Line, keyName, fnName)
			}
			return true
		})
	}
}

// TestNoSecReimplInAPIPackage — §7
//
// The api package must import server/internal/sec for all security gating.
// It must NOT contain inline re-implementations of: sanitize, pattern matching,
// rate-limiting, or denylist logic. The AST scan looks for the tell-tale
// function and type names the sec package owns.
func TestNoSecReimplInAPIPackage(t *testing.T) {
	root := repoRoot(t)
	apiDir := filepath.Join(root, "server", "internal", "api")

	// Forbidden identifiers: any re-implementation of sec.* names in the api
	// package body would introduce one of these. The list mirrors the exported
	// surface of server/internal/sec/ that the gateway uses.
	forbidden := []string{
		"SanitizeText",
		"RuleSet",
		"CompiledRule",
		"ParseRules",
		"GCRABucket",
		"NewGCRABucket",
		"SecondaryBucket",
		"DenylistCheck",
		"NormalizeTurkish",
		"LowercaseTurkish",
	}

	fset := token.NewFileSet()
	pkgs, err := parser.ParseDir(fset, apiDir, func(fi os.FileInfo) bool {
		return !strings.HasSuffix(fi.Name(), "_test.go")
	}, 0)
	if err != nil {
		t.Fatalf("parse api dir %s: %v", apiDir, err)
	}

	for _, pkg := range pkgs {
		for fname, f := range pkg.Files {
			ast.Inspect(f, func(n ast.Node) bool {
				ident, ok := n.(*ast.Ident)
				if !ok {
					return true
				}
				for _, bad := range forbidden {
					if ident.Name == bad {
						pos := fset.Position(ident.Pos())
						t.Errorf("§7 violation: %s at %s:%d — use server/internal/sec instead of re-implementing",
							ident.Name, filepath.Base(fname), pos.Line)
					}
				}
				return true
			})
		}
	}
}

// TestReadyzToleratesConsensusAbsence — §9.15 Phase 14 K8s forward contract.
//
// The readyzHandler function in server/cmd/api/main.go MUST NOT reference
// "consensus" anywhere in its body. consensus.v1 runs at replicas:1 (§5.3
// single-publication guarantee); it is never a co-location requirement for
// an API pod. The readyz probe checks only PG + Redis.
//
// The AST scan isolates the readyzHandler function declaration and verifies
// that no identifier, selector, or string literal contains "consensus"
// (case-insensitive) within that function's body.
func TestReadyzToleratesConsensusAbsence(t *testing.T) {
	root := repoRoot(t)
	mainFile := filepath.Join(root, "server", "cmd", "api", "main.go")

	src, err := os.ReadFile(mainFile)
	if err != nil {
		t.Fatalf("read %s: %v", mainFile, err)
	}
	fset := token.NewFileSet()
	f, err := parser.ParseFile(fset, mainFile, src, 0)
	if err != nil {
		t.Fatalf("parse %s: %v", mainFile, err)
	}

	// Locate the readyzHandler function declaration.
	var readyzFn *ast.FuncDecl
	for _, decl := range f.Decls {
		fn, ok := decl.(*ast.FuncDecl)
		if ok && fn.Name.Name == "readyzHandler" {
			readyzFn = fn
			break
		}
	}
	if readyzFn == nil {
		t.Fatal("readyzHandler function not found in server/cmd/api/main.go — required by §9.15 Phase 14 forward contract")
	}

	// Scan the body for any reference to "consensus" (case-insensitive).
	ast.Inspect(readyzFn.Body, func(n ast.Node) bool {
		if n == nil {
			return false
		}
		check := func(s string) {
			if strings.Contains(strings.ToLower(s), "consensus") {
				pos := fset.Position(n.Pos())
				t.Errorf("§9.15 Phase 14 violation: readyzHandler references 'consensus' at line %d — "+
					"readyz must NOT check consensus.v1 co-location (it runs replicas:1 off this pod)",
					pos.Line)
			}
		}
		switch node := n.(type) {
		case *ast.Ident:
			check(node.Name)
		case *ast.BasicLit:
			check(node.Value)
		case *ast.SelectorExpr:
			check(node.Sel.Name)
		}
		return true
	})
}
