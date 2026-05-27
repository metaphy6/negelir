package api_test

// wire_authority_test.go — §9.14 Wire-authority boundary (Phase 3.6 enumerative).
//
// TestAPIGatewaySoleWriterAPIRequestV1 — registry walk; api.request.v1 sole producer.
//
// Two-part assertion:
//  1. Registry walk: parse server/cmd/swarmctl/main.go and confirm that
//     wireAuthorityProducers contains exactly one entry for "api.request.v1"
//     with value "api.gateway.v1".
//  2. Codebase scan: walk all non-test Go files in server/ and assert that
//     "api.request.v1" as a string literal appears only in permitted packages
//     (cmd/swarmctl — the registry definition, internal/api — the gateway,
//     internal/middleware — the AuditEmitter).  No other component may carry
//     the literal, preventing an accidental second publisher.

import (
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/metaphy6/negelir/server/internal/rpc"
)

// apiGWServerRoot walks up from the test working directory to find server/.
func apiGWServerRoot(t *testing.T) string {
	t.Helper()
	cwd, err := os.Getwd()
	if err != nil {
		t.Fatalf("getwd: %v", err)
	}
	dir := cwd
	for {
		if filepath.Base(dir) == "server" {
			return dir
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			break
		}
		dir = parent
	}
	// Fallback: look for server/ below cwd (e.g. when cwd is repo root).
	candidate := filepath.Join(cwd, "server")
	if _, statErr := os.Stat(candidate); statErr == nil {
		return candidate
	}
	t.Fatal("could not find server/ directory (walked up from " + cwd + ")")
	return ""
}

// TestAPIGatewaySoleWriterAPIRequestV1 — §9.14 wire-authority boundary.
//
// Asserts that api.request.v1 is declared in the swarmctl registry with
// "api.gateway.v1" as its sole producer, and that no other non-test server
// source file contains the literal outside permitted packages.
func TestAPIGatewaySoleWriterAPIRequestV1(t *testing.T) {
	serverRoot := apiGWServerRoot(t)
	const topic = "api.request.v1"
	const wantProducer = "api.gateway.v1"

	// ── Part 1: registry walk ──────────────────────────────────────────────
	// Parse server/cmd/swarmctl/main.go with the Go AST and locate the
	// wireAuthorityProducers composite literal.  Extract every key→value pair
	// and assert that topic maps to wantProducer exactly once.
	swarmctlMainPath := filepath.Join(serverRoot, "cmd", "swarmctl", "main.go")
	src, err := os.ReadFile(swarmctlMainPath)
	if err != nil {
		t.Fatalf("read %s: %v", swarmctlMainPath, err)
	}
	fset := token.NewFileSet()
	regAST, err := parser.ParseFile(fset, swarmctlMainPath, src, 0)
	if err != nil {
		t.Fatalf("parse %s: %v", swarmctlMainPath, err)
	}

	type kv struct{ key, val string }
	var entries []kv

	// Collect entries from var wireAuthorityProducers = map[string]string{...}
	ast.Inspect(regAST, func(n ast.Node) bool {
		vs, ok := n.(*ast.ValueSpec)
		if !ok {
			return true
		}
		for i, name := range vs.Names {
			if name.Name != "wireAuthorityProducers" {
				continue
			}
			if i >= len(vs.Values) {
				continue
			}
			compLit, ok := vs.Values[i].(*ast.CompositeLit)
			if !ok {
				continue
			}
			for _, elt := range compLit.Elts {
				pair, ok := elt.(*ast.KeyValueExpr)
				if !ok {
					continue
				}
				kLit, kOK := pair.Key.(*ast.BasicLit)
				vLit, vOK := pair.Value.(*ast.BasicLit)
				if kOK && vOK {
					entries = append(entries, kv{
						key: strings.Trim(kLit.Value, `"`),
						val: strings.Trim(vLit.Value, `"`),
					})
				}
			}
		}
		return true
	})

	if len(entries) == 0 {
		t.Fatal("wireAuthorityProducers map not found or empty in " +
			"server/cmd/swarmctl/main.go; was it renamed or moved?")
	}

	countForTopic := 0
	producerForTopic := ""
	for _, e := range entries {
		if e.key == topic {
			countForTopic++
			producerForTopic = e.val
		}
	}
	switch {
	case countForTopic == 0:
		t.Errorf("§9.14 wire-authority registry: topic %q absent from "+
			"wireAuthorityProducers; must be declared with producer %q",
			topic, wantProducer)
	case countForTopic > 1:
		t.Errorf("§9.14 wire-authority registry: topic %q appears %d times in "+
			"wireAuthorityProducers; must appear exactly once",
			topic, countForTopic)
	case producerForTopic != wantProducer:
		t.Errorf("§9.14 wire-authority registry: wireAuthorityProducers[%q] = %q; "+
			"want %q (sole producer)",
			topic, producerForTopic, wantProducer)
	}

	// ── Part 2: codebase scan ──────────────────────────────────────────────
	// Walk all non-test Go files in server/ and assert that the literal
	// "api.request.v1" only appears in permitted packages.  Any other
	// occurrence would indicate a component that could publish to the topic
	// without going through the gateway.
	allowedPrefixes := []string{
		filepath.Join("cmd", "swarmctl") + string(os.PathSeparator),       // registry
		filepath.Join("internal", "api") + string(os.PathSeparator),       // gateway
		filepath.Join("internal", "middleware") + string(os.PathSeparator), // AuditEmitter
	}
	var violations []string
	walkErr := filepath.WalkDir(serverRoot, func(path string, d fs.DirEntry, e error) error {
		if e != nil || d.IsDir() {
			return e
		}
		if filepath.Ext(path) != ".go" || strings.HasSuffix(path, "_test.go") {
			return nil
		}
		rel, _ := filepath.Rel(serverRoot, path)
		for _, prefix := range allowedPrefixes {
			if strings.HasPrefix(rel, prefix) {
				return nil
			}
		}
		fset2 := token.NewFileSet()
		f, parseErr := parser.ParseFile(fset2, path, nil, 0)
		if parseErr != nil {
			return nil // skip files that fail to parse
		}
		ast.Inspect(f, func(n ast.Node) bool {
			lit, ok := n.(*ast.BasicLit)
			if !ok {
				return true
			}
			if strings.Contains(lit.Value, topic) {
				violations = append(violations, rel)
			}
			return true
		})
		return nil
	})
	if walkErr != nil {
		t.Fatalf("WalkDir(%s): %v", serverRoot, walkErr)
	}
	if len(violations) > 0 {
		t.Errorf("§9.14 wire-authority codebase scan: literal %q found outside "+
			"permitted packages in non-test server source "+
			"(sole producer must be api.gateway.v1):\n  %s",
			topic, strings.Join(violations, "\n  "))
	}
}

// TestAPIGatewaySoleWriterAPIResponseV1 — §9.14 wire-authority boundary.
//
// Asserts that api.response.v1 is declared in the swarmctl registry with
// "api.gateway.v1" as its sole producer, and that no other non-test server
// source file contains the literal outside permitted packages.
func TestAPIGatewaySoleWriterAPIResponseV1(t *testing.T) {
	serverRoot := apiGWServerRoot(t)
	const topic = "api.response.v1"
	const wantProducer = "api.gateway.v1"

	// ── Part 1: registry walk ──────────────────────────────────────────────
	swarmctlMainPath := filepath.Join(serverRoot, "cmd", "swarmctl", "main.go")
	src, err := os.ReadFile(swarmctlMainPath)
	if err != nil {
		t.Fatalf("read %s: %v", swarmctlMainPath, err)
	}
	fset := token.NewFileSet()
	regAST, err := parser.ParseFile(fset, swarmctlMainPath, src, 0)
	if err != nil {
		t.Fatalf("parse %s: %v", swarmctlMainPath, err)
	}

	type kv struct{ key, val string }
	var entries []kv

	ast.Inspect(regAST, func(n ast.Node) bool {
		vs, ok := n.(*ast.ValueSpec)
		if !ok {
			return true
		}
		for i, name := range vs.Names {
			if name.Name != "wireAuthorityProducers" {
				continue
			}
			if i >= len(vs.Values) {
				continue
			}
			compLit, ok := vs.Values[i].(*ast.CompositeLit)
			if !ok {
				continue
			}
			for _, elt := range compLit.Elts {
				pair, ok := elt.(*ast.KeyValueExpr)
				if !ok {
					continue
				}
				kLit, kOK := pair.Key.(*ast.BasicLit)
				vLit, vOK := pair.Value.(*ast.BasicLit)
				if kOK && vOK {
					entries = append(entries, kv{
						key: strings.Trim(kLit.Value, `"`),
						val: strings.Trim(vLit.Value, `"`),
					})
				}
			}
		}
		return true
	})

	if len(entries) == 0 {
		t.Fatal("wireAuthorityProducers map not found or empty in " +
			"server/cmd/swarmctl/main.go; was it renamed or moved?")
	}

	countForTopic := 0
	producerForTopic := ""
	for _, e := range entries {
		if e.key == topic {
			countForTopic++
			producerForTopic = e.val
		}
	}
	switch {
	case countForTopic == 0:
		t.Errorf("§9.14 wire-authority registry: topic %q absent from "+
			"wireAuthorityProducers; must be declared with producer %q",
			topic, wantProducer)
	case countForTopic > 1:
		t.Errorf("§9.14 wire-authority registry: topic %q appears %d times in "+
			"wireAuthorityProducers; must appear exactly once",
			topic, countForTopic)
	case producerForTopic != wantProducer:
		t.Errorf("§9.14 wire-authority registry: wireAuthorityProducers[%q] = %q; "+
			"want %q (sole producer)",
			topic, producerForTopic, wantProducer)
	}

	// ── Part 2: codebase scan ──────────────────────────────────────────────
	allowedPrefixes := []string{
		filepath.Join("cmd", "swarmctl") + string(os.PathSeparator),        // registry
		filepath.Join("internal", "api") + string(os.PathSeparator),        // gateway
		filepath.Join("internal", "middleware") + string(os.PathSeparator), // AuditEmitter
	}
	var violations []string
	walkErr := filepath.WalkDir(serverRoot, func(path string, d fs.DirEntry, e error) error {
		if e != nil || d.IsDir() {
			return e
		}
		if filepath.Ext(path) != ".go" || strings.HasSuffix(path, "_test.go") {
			return nil
		}
		rel, _ := filepath.Rel(serverRoot, path)
		for _, prefix := range allowedPrefixes {
			if strings.HasPrefix(rel, prefix) {
				return nil
			}
		}
		fset2 := token.NewFileSet()
		f, parseErr := parser.ParseFile(fset2, path, nil, 0)
		if parseErr != nil {
			return nil
		}
		ast.Inspect(f, func(n ast.Node) bool {
			lit, ok := n.(*ast.BasicLit)
			if !ok {
				return true
			}
			if strings.Contains(lit.Value, topic) {
				violations = append(violations, rel)
			}
			return true
		})
		return nil
	})
	if walkErr != nil {
		t.Fatalf("WalkDir(%s): %v", serverRoot, walkErr)
	}
	if len(violations) > 0 {
		t.Errorf("§9.14 wire-authority codebase scan: literal %q found outside "+
			"permitted packages in non-test server source "+
			"(sole producer must be api.gateway.v1):\n  %s",
			topic, strings.Join(violations, "\n  "))
	}
}

// TestAPIGatewaySoleWriterPredictCancelV1 — §9.14 wire-authority boundary.
//
// Asserts that predict.cancel.v1 is declared in the swarmctl registry with
// "api.gateway.v1" as its sole producer, and that no other non-test server
// source file contains the literal outside permitted packages.
func TestAPIGatewaySoleWriterPredictCancelV1(t *testing.T) {
	serverRoot := apiGWServerRoot(t)
	const topic = rpc.CancelTopic
	const wantProducer = "api.gateway.v1"

	// ── Part 1: registry walk ──────────────────────────────────────────────
	swarmctlMainPath := filepath.Join(serverRoot, "cmd", "swarmctl", "main.go")
	src, err := os.ReadFile(swarmctlMainPath)
	if err != nil {
		t.Fatalf("read %s: %v", swarmctlMainPath, err)
	}
	fset := token.NewFileSet()
	regAST, err := parser.ParseFile(fset, swarmctlMainPath, src, 0)
	if err != nil {
		t.Fatalf("parse %s: %v", swarmctlMainPath, err)
	}

	type kv struct{ key, val string }
	var entries []kv

	ast.Inspect(regAST, func(n ast.Node) bool {
		vs, ok := n.(*ast.ValueSpec)
		if !ok {
			return true
		}
		for i, name := range vs.Names {
			if name.Name != "wireAuthorityProducers" {
				continue
			}
			if i >= len(vs.Values) {
				continue
			}
			compLit, ok := vs.Values[i].(*ast.CompositeLit)
			if !ok {
				continue
			}
			for _, elt := range compLit.Elts {
				pair, ok := elt.(*ast.KeyValueExpr)
				if !ok {
					continue
				}
				kLit, kOK := pair.Key.(*ast.BasicLit)
				vLit, vOK := pair.Value.(*ast.BasicLit)
				if kOK && vOK {
					entries = append(entries, kv{
						key: strings.Trim(kLit.Value, `"`),
						val: strings.Trim(vLit.Value, `"`),
					})
				}
			}
		}
		return true
	})

	if len(entries) == 0 {
		t.Fatal("wireAuthorityProducers map not found or empty in " +
			"server/cmd/swarmctl/main.go; was it renamed or moved?")
	}

	countForTopic := 0
	producerForTopic := ""
	for _, e := range entries {
		if e.key == topic {
			countForTopic++
			producerForTopic = e.val
		}
	}
	switch {
	case countForTopic == 0:
		t.Errorf("§9.14 wire-authority registry: topic %q absent from "+
			"wireAuthorityProducers; must be declared with producer %q",
			topic, wantProducer)
	case countForTopic > 1:
		t.Errorf("§9.14 wire-authority registry: topic %q appears %d times in "+
			"wireAuthorityProducers; must appear exactly once",
			topic, countForTopic)
	case producerForTopic != wantProducer:
		t.Errorf("§9.14 wire-authority registry: wireAuthorityProducers[%q] = %q; "+
			"want %q (sole producer)",
			topic, producerForTopic, wantProducer)
	}

	// ── Part 2: codebase scan ──────────────────────────────────────────────
	allowedPrefixes := []string{
		filepath.Join("cmd", "swarmctl") + string(os.PathSeparator),        // registry
		filepath.Join("internal", "api") + string(os.PathSeparator),        // gateway publisher
		filepath.Join("internal", "middleware") + string(os.PathSeparator), // AuditEmitter
		filepath.Join("internal", "rpc") + string(os.PathSeparator),        // CancelTopic constant / CancelPublisher
	}
	var violations []string
	walkErr := filepath.WalkDir(serverRoot, func(path string, d fs.DirEntry, e error) error {
		if e != nil || d.IsDir() {
			return e
		}
		if filepath.Ext(path) != ".go" || strings.HasSuffix(path, "_test.go") {
			return nil
		}
		rel, _ := filepath.Rel(serverRoot, path)
		for _, prefix := range allowedPrefixes {
			if strings.HasPrefix(rel, prefix) {
				return nil
			}
		}
		fset2 := token.NewFileSet()
		f, parseErr := parser.ParseFile(fset2, path, nil, 0)
		if parseErr != nil {
			return nil
		}
		ast.Inspect(f, func(n ast.Node) bool {
			lit, ok := n.(*ast.BasicLit)
			if !ok {
				return true
			}
			if strings.Contains(lit.Value, topic) {
				violations = append(violations, rel)
			}
			return true
		})
		return nil
	})
	if walkErr != nil {
		t.Fatalf("WalkDir(%s): %v", serverRoot, walkErr)
	}
	if len(violations) > 0 {
		t.Errorf("§9.14 wire-authority codebase scan: literal %q found outside "+
			"permitted packages in non-test server source "+
			"(sole producer must be api.gateway.v1):\n  %s",
			topic, strings.Join(violations, "\n  "))
	}
}

// TestAPIDoesNotPublishMaintOrSec — §9.14 wire-authority boundary (AST scan).
//
// Verifies that no non-test Go source file under server/internal/api/ or
// server/internal/handlers/ contains a string literal matching any of the
// forbidden topic prefixes: maint.*, sec.*, auth.*, payment.*.
//
// These topics are owned by distinct components (security gate, maintenance
// reactor, payment layer) and the API gateway must never publish to them
// directly.  An accidental literal would indicate scope creep or a
// misconfigured publish call.
func TestAPIDoesNotPublishMaintOrSec(t *testing.T) {
	serverRoot := apiGWServerRoot(t)

	// Directories to scan (relative to serverRoot).
	scanDirs := []string{
		filepath.Join(serverRoot, "internal", "api"),
		filepath.Join(serverRoot, "internal", "handlers"),
	}

	// Topic prefixes the API is forbidden from publishing to.
	forbiddenPrefixes := []string{"maint.", "sec.", "auth.", "payment."}

	var violations []string

	for _, dir := range scanDirs {
		// Directory may not exist yet; skip gracefully.
		if _, statErr := os.Stat(dir); os.IsNotExist(statErr) {
			continue
		}
		walkErr := filepath.WalkDir(dir, func(path string, d fs.DirEntry, e error) error {
			if e != nil || d.IsDir() {
				return e
			}
			if filepath.Ext(path) != ".go" || strings.HasSuffix(path, "_test.go") {
				return nil
			}
			fset := token.NewFileSet()
			f, parseErr := parser.ParseFile(fset, path, nil, 0)
			if parseErr != nil {
				return nil // skip unparseable files
			}
			rel, _ := filepath.Rel(serverRoot, path)
			ast.Inspect(f, func(n ast.Node) bool {
				lit, ok := n.(*ast.BasicLit)
				if !ok || lit.Kind != token.STRING {
					return true
				}
				val := strings.Trim(lit.Value, `"` + "`")
				for _, prefix := range forbiddenPrefixes {
					if strings.HasPrefix(val, prefix) {
						pos := fset.Position(lit.Pos())
						violations = append(violations,
							fmt.Sprintf("%s:%d — %s", rel, pos.Line, lit.Value))
					}
				}
				return true
			})
			return nil
		})
		if walkErr != nil {
			t.Fatalf("WalkDir(%s): %v", dir, walkErr)
		}
	}

	if len(violations) > 0 {
		t.Errorf("§9.14 wire-authority: API source files contain forbidden topic "+
			"literals (maint.* / sec.* / auth.* / payment.*); "+
			"API must not publish to these topics directly:\n  %s",
			strings.Join(violations, "\n  "))
	}
}

// TestAPIConsumesPredictApprovedNotPredictFinal — §9.14 wire-authority boundary.
//
// Two-part assertion:
//  1. Registry walk: parse server/cmd/swarmctl/main.go and confirm that
//     wireAuthorityConsumers maps "predict.approved.v1" to "api.gateway.v1".
//  2. Codebase scan: walk all non-test Go files in server/internal/api/ and
//     server/internal/handlers/ and assert that the literal "predict.final"
//     does NOT appear as a string literal.  The API must only consume the
//     proofreader-approved reply topic, never the raw swarm-internal one.
func TestAPIConsumesPredictApprovedNotPredictFinal(t *testing.T) {
	serverRoot := apiGWServerRoot(t)
	const approvedTopic = "predict.approved.v1"
	const wantConsumer = "api.gateway.v1"
	const forbiddenLiteral = "predict.final"

	// ── Part 1: registry walk ──────────────────────────────────────────────
	// Parse server/cmd/swarmctl/main.go with the Go AST and locate the
	// wireAuthorityConsumers composite literal.  Extract every key→value pair
	// and assert that approvedTopic maps to wantConsumer exactly once.
	swarmctlMainPath := filepath.Join(serverRoot, "cmd", "swarmctl", "main.go")
	src, err := os.ReadFile(swarmctlMainPath)
	if err != nil {
		t.Fatalf("read %s: %v", swarmctlMainPath, err)
	}
	fset := token.NewFileSet()
	regAST, err := parser.ParseFile(fset, swarmctlMainPath, src, 0)
	if err != nil {
		t.Fatalf("parse %s: %v", swarmctlMainPath, err)
	}

	type kv struct{ key, val string }
	var entries []kv

	// Collect entries from var wireAuthorityConsumers = map[string]string{...}
	ast.Inspect(regAST, func(n ast.Node) bool {
		vs, ok := n.(*ast.ValueSpec)
		if !ok {
			return true
		}
		for i, name := range vs.Names {
			if name.Name != "wireAuthorityConsumers" {
				continue
			}
			if i >= len(vs.Values) {
				continue
			}
			compLit, ok := vs.Values[i].(*ast.CompositeLit)
			if !ok {
				continue
			}
			for _, elt := range compLit.Elts {
				pair, ok := elt.(*ast.KeyValueExpr)
				if !ok {
					continue
				}
				kLit, kOK := pair.Key.(*ast.BasicLit)
				vLit, vOK := pair.Value.(*ast.BasicLit)
				if kOK && vOK {
					entries = append(entries, kv{
						key: strings.Trim(kLit.Value, `"`),
						val: strings.Trim(vLit.Value, `"`),
					})
				}
			}
		}
		return true
	})

	if len(entries) == 0 {
		t.Fatal("wireAuthorityConsumers map not found or empty in " +
			"server/cmd/swarmctl/main.go; was it renamed or moved?")
	}

	countForTopic := 0
	consumerForTopic := ""
	for _, e := range entries {
		if e.key == approvedTopic {
			countForTopic++
			consumerForTopic = e.val
		}
	}
	switch {
	case countForTopic == 0:
		t.Errorf("§9.14 wire-authority registry: topic %q absent from "+
			"wireAuthorityConsumers; must be declared with consumer %q",
			approvedTopic, wantConsumer)
	case countForTopic > 1:
		t.Errorf("§9.14 wire-authority registry: topic %q appears %d times in "+
			"wireAuthorityConsumers; must appear exactly once",
			approvedTopic, countForTopic)
	case consumerForTopic != wantConsumer:
		t.Errorf("§9.14 wire-authority registry: wireAuthorityConsumers[%q] = %q; "+
			"want %q (declared consumer)",
			approvedTopic, consumerForTopic, wantConsumer)
	}

	// ── Part 2: codebase scan ──────────────────────────────────────────────
	// Walk all non-test Go files in server/internal/api/ and
	// server/internal/handlers/ and assert that the literal "predict.final"
	// does not appear.  The API must never directly subscribe to the raw
	// swarm-internal prediction topic; it must use predict.approved.v1.
	scanDirs := []string{
		filepath.Join(serverRoot, "internal", "api"),
		filepath.Join(serverRoot, "internal", "handlers"),
	}

	var violations []string
	for _, dir := range scanDirs {
		if _, statErr := os.Stat(dir); os.IsNotExist(statErr) {
			continue
		}
		walkErr := filepath.WalkDir(dir, func(path string, d fs.DirEntry, e error) error {
			if e != nil || d.IsDir() {
				return e
			}
			if filepath.Ext(path) != ".go" || strings.HasSuffix(path, "_test.go") {
				return nil
			}
			fset2 := token.NewFileSet()
			f, parseErr := parser.ParseFile(fset2, path, nil, 0)
			if parseErr != nil {
				return nil // skip unparseable files
			}
			rel, _ := filepath.Rel(serverRoot, path)
			ast.Inspect(f, func(n ast.Node) bool {
				lit, ok := n.(*ast.BasicLit)
				if !ok || lit.Kind != token.STRING {
					return true
				}
				if strings.Contains(lit.Value, forbiddenLiteral) {
					pos := fset2.Position(lit.Pos())
					violations = append(violations,
						fmt.Sprintf("%s:%d — %s", rel, pos.Line, lit.Value))
				}
				return true
			})
			return nil
		})
		if walkErr != nil {
			t.Fatalf("WalkDir(%s): %v", dir, walkErr)
		}
	}

	if len(violations) > 0 {
		t.Errorf("§9.14 wire-authority codebase scan: literal %q found in "+
			"server/internal/api/ or server/internal/handlers/ non-test source; "+
			"API must consume predict.approved.v1 only (§9.3 boundary):\n  %s",
			forbiddenLiteral, strings.Join(violations, "\n  "))
	}
}
