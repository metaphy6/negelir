package handlers_test

// §9.15 Phase 16 forward-contract boundary test.
//
// Contract: internal/handlers/predictions.go imports the CalibrationStore
// interface (internal/calibration), never any concrete backend
// (e.g. internal/calibration/memory or any future feed-plane impl).
//
// Rationale: swapping the Phase 9 in-memory backend for the Phase 16
// feed-plane backend must change 0 handler lines.  If predictions.go
// ever imports a concrete backend package directly, that invariant is
// broken and Phase 16 wiring becomes a handler-layer change.

import (
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// repoRootFromHandlers walks up until AGENTS.md is found.
func repoRootFromHandlers(t *testing.T) string {
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

// TestPredictionsHandlerImportsCalibrationInterface — §9.15 Phase 16 boundary.
//
// Asserts:
//  1. internal/handlers/predictions.go imports
//     "github.com/metaphy6/negelir/server/internal/calibration" (the interface pkg).
//  2. internal/handlers/predictions.go does NOT import any sub-package or
//     suffixed variant of the calibration package (e.g. ".../calibration/memory"
//     or any future ".../calibration/feed").
func TestPredictionsHandlerImportsCalibrationInterface(t *testing.T) {
	root := repoRootFromHandlers(t)
	predPath := filepath.Join(root, "server", "internal", "handlers", "predictions.go")

	src, err := os.ReadFile(predPath)
	if err != nil {
		t.Fatalf("read %s: %v", predPath, err)
	}

	fset := token.NewFileSet()
	f, err := parser.ParseFile(fset, predPath, src, 0)
	if err != nil {
		t.Fatalf("parse %s: %v", predPath, err)
	}

	const interfacePkg = "github.com/metaphy6/negelir/server/internal/calibration"

	importsInterface := false
	for _, imp := range f.Imports {
		path := strings.Trim(imp.Path.Value, `"`)
		if path == interfacePkg {
			importsInterface = true
			continue
		}
		// Fail on any deeper path (concrete backend).
		if strings.HasPrefix(path, interfacePkg+"/") {
			pos := fset.Position(imp.Pos())
			t.Errorf("§9.15 Phase 16 violation at %s:%d — "+
				"predictions.go imports concrete calibration backend %q; "+
				"use the CalibrationStore interface (injection via constructor), "+
				"not a concrete impl",
				predPath, pos.Line, path)
		}
	}

	if !importsInterface {
		t.Errorf("§9.15 Phase 16 violation — "+
			"predictions.go does not import the CalibrationStore interface package %q; "+
			"the handler must depend on the interface, not bypass it",
			interfacePkg)
	}
}

// TestPredictionsHandlerNoConcreteMentionInAST — §9.15 Phase 16 boundary (deep).
//
// Walks the full AST of predictions.go and asserts that no identifier
// or selector references the concrete InMemoryCalibrationStore type or any
// similarly-named concrete backend.  This catches cases where the type
// leaks via dot-import, type-assert, or inline construction.
func TestPredictionsHandlerNoConcreteMentionInAST(t *testing.T) {
	root := repoRootFromHandlers(t)
	predPath := filepath.Join(root, "server", "internal", "handlers", "predictions.go")

	src, err := os.ReadFile(predPath)
	if err != nil {
		t.Fatalf("read %s: %v", predPath, err)
	}

	fset := token.NewFileSet()
	f, err := parser.ParseFile(fset, predPath, src, 0)
	if err != nil {
		t.Fatalf("parse %s: %v", predPath, err)
	}

	forbidden := []string{
		"InMemoryCalibrationStore",
		// Extend this list when new concrete backends are introduced.
	}

	ast.Inspect(f, func(n ast.Node) bool {
		ident, ok := n.(*ast.Ident)
		if !ok {
			return true
		}
		for _, name := range forbidden {
			if ident.Name == name {
				pos := fset.Position(ident.Pos())
				t.Errorf("§9.15 Phase 16 violation at %s:%d — "+
					"predictions.go references concrete type %q directly; "+
					"the handler must only use the CalibrationStore interface",
					predPath, pos.Line, name)
			}
		}
		return true
	})
}
