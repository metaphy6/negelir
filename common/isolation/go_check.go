// Phase 18.1 §18.1 — Go isolation checker
// Reads policy.yaml and scans Go source files for os/exec.Command() invocations
// targeting forbidden binaries. Uses AST parsing for accuracy.
//
// Usage: go run common/isolation/go_check.go check-server
// References ledger #3.

package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"io/ioutil"
	"os"
	"path/filepath"
	"strings"

	"gopkg.in/yaml.v3"
)

// IsolationViolation mirrors the Python dataclass structure.
type IsolationViolation struct {
	File             string `json:"file"`
	Line             int    `json:"line"`
	ExecStmt         string `json:"exec_stmt"`
	SourceComponent  string `json:"source_component"`
	ForbiddenBinary  string `json:"forbidden_binary"`
	LedgerRef        int    `json:"ledger_ref"`
	SuggestedFix     string `json:"suggested_fix"`
}

// PolicyFile represents the YAML policy structure.
type PolicyFile struct {
	SchemaVersion         string                      `yaml:"schema_version"`
	LastAuditedAt         string                      `yaml:"last_audited_at"`
	Components            map[string]ComponentPolicy `yaml:"components"`
	CrossComponentAllowed map[string][]string        `yaml:"cross_component_allowed"`
}

// ComponentPolicy defines allowed/forbidden imports for a component.
type ComponentPolicy struct {
	AllowedExternalImports []string `yaml:"allowed_external_imports"`
	ForbiddenImports       []string `yaml:"forbidden_imports"`
}

var (
	repoRoot = ""
	policy   *PolicyFile
)

func init() {
	// Determine repo root by walking up from current directory until ROADMAP.md is found
	var err error
	repoRoot, err = findRepoRoot()
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error finding repo root: %v\n", err)
		os.Exit(1)
	}

	// Load policy.yaml
	policyPath := filepath.Join(repoRoot, "ai", "common", "isolation", "policy.yaml")
	if policy, err = loadPolicy(policyPath); err != nil {
		fmt.Fprintf(os.Stderr, "Error loading policy: %v\n", err)
		os.Exit(1)
	}
}

func findRepoRoot() (string, error) {
	cwd, err := os.Getwd()
	if err != nil {
		return "", err
	}

	for {
		roadmapPath := filepath.Join(cwd, "docs", "planning", "ROADMAP.md")
		if _, err := os.Stat(roadmapPath); err == nil {
			return cwd, nil
		}

		parent := filepath.Dir(cwd)
		if parent == cwd {
			return "", fmt.Errorf("could not find repo root (no ROADMAP.md found)")
		}
		cwd = parent
	}
}

func loadPolicy(path string) (*PolicyFile, error) {
	data, err := ioutil.ReadFile(path)
	if err != nil {
		return nil, err
	}

	var p PolicyFile
	if err := yaml.Unmarshal(data, &p); err != nil {
		return nil, err
	}
	return &p, nil
}

// Forbidden binaries that should never be executed from Go code.
var forbiddenBinaries = []string{
	"python",
	"python3",
	"python2",
	"pytest",
	"xgboost",
	"torch",
	"pip",
	"pip3",
}

// isForbiddenBinary checks if a string matches any forbidden binary pattern.
func isForbiddenBinary(name string) bool {
	// Strip path and extension
	base := filepath.Base(name)
	base = strings.TrimSuffix(base, ".exe") // Windows

	for _, forbidden := range forbiddenBinaries {
		if base == forbidden || strings.HasPrefix(base, forbidden+".") {
			return true
		}
	}
	return false
}

// scanGoFile walks an AST of a Go file looking for os/exec.Command calls
// with forbidden binary arguments.
func scanGoFile(filePath string) ([]IsolationViolation, error) {
	var violations []IsolationViolation

	src, err := ioutil.ReadFile(filePath)
	if err != nil {
		return nil, err
	}

	fset := token.NewFileSet()
	f, err := parser.ParseFile(fset, filePath, src, 0)
	if err != nil {
		// Skip files that don't parse (generated code, etc.)
		return nil, nil
	}

	ast.Inspect(f, func(n ast.Node) bool {
		call, ok := n.(*ast.CallExpr)
		if !ok {
			return true
		}

		// Match os/exec.Command(...) pattern
		if isExecCommand(call.Fun) {
			// Check the first argument (the command name)
			if len(call.Args) > 0 {
				if lit, ok := call.Args[0].(*ast.BasicLit); ok {
					cmdName := strings.Trim(lit.Value, `"`)
					if isForbiddenBinary(cmdName) {
						violations = append(violations, IsolationViolation{
							File:            filePath,
							Line:            fset.Position(call.Pos()).Line,
							ExecStmt:        fmt.Sprintf("exec.Command(\"%s\")", cmdName),
							SourceComponent: "server",
							ForbiddenBinary: cmdName,
							LedgerRef:       3,
							SuggestedFix:    fmt.Sprintf("Remove os/exec.Command call to %q from server code", cmdName),
						})
					}
				}
			}
		}

		return true
	})

	return violations, nil
}

// isExecCommand checks if an AST node represents an os/exec.Command call.
func isExecCommand(node ast.Expr) bool {
	sel, ok := node.(*ast.SelectorExpr)
	if !ok {
		return false
	}

	// Check if it's .Command
	if sel.Sel.Name != "Command" {
		return false
	}

	// Check if receiver is "exec" (assuming os/exec imported as exec or os)
	switch x := sel.X.(type) {
	case *ast.Ident:
		return x.Name == "exec" || x.Name == "os"
	default:
		return false
	}
}

// checkComponent walks all Go files in a component and scans for violations.
func checkComponent(component string) ([]IsolationViolation, error) {
	var violations []IsolationViolation

	searchPaths := []string{}
	if component == "server" {
		searchPaths = append(searchPaths, filepath.Join(repoRoot, "server"))
	} else {
		return nil, fmt.Errorf("unknown component: %s", component)
	}

	for _, searchPath := range searchPaths {
		if _, err := os.Stat(searchPath); os.IsNotExist(err) {
			continue
		}

		err := filepath.Walk(searchPath, func(path string, info os.FileInfo, err error) error {
			if err != nil {
				return err
			}

			if !info.IsDir() && strings.HasSuffix(path, ".go") && !strings.HasSuffix(path, "_test.go") {
				fileViolations, err := scanGoFile(path)
				if err != nil {
					// Skip unparseable files
					return nil
				}
				violations = append(violations, fileViolations...)
			}
			return nil
		})

		if err != nil {
			return nil, err
		}
	}

	return violations, nil
}

func main() {
	flag.Parse()
	args := flag.Args()

	if len(args) < 1 {
		fmt.Fprintf(os.Stderr, "Usage: go run common/isolation/go_check.go check-<component>\n")
		fmt.Fprintf(os.Stderr, "Example: go run common/isolation/go_check.go check-server\n")
		os.Exit(1)
	}

	cmd := args[0]

	var component string
	if strings.HasPrefix(cmd, "check-") {
		component = strings.TrimPrefix(cmd, "check-")
	} else {
		fmt.Fprintf(os.Stderr, "Unknown command: %s\n", cmd)
		os.Exit(1)
	}

	violations, err := checkComponent(component)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}

	for _, v := range violations {
		// Human-readable output
		fmt.Printf("%s:%d: %s violates %s isolation\n",
			v.File, v.Line, v.ExecStmt, v.SourceComponent)
	}

	// Also output JSON for CI consumption
	if len(violations) > 0 {
		data, _ := json.MarshalIndent(violations, "", "  ")
		fmt.Printf("\nJSON Output:\n%s\n", string(data))
		os.Exit(len(violations))
	}

	os.Exit(0)
}
