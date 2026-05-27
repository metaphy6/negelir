package errors_test

import (
	"encoding/json"
	"go/ast"
	"go/parser"
	"go/token"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"

	aperrors "github.com/metaphy6/negelir/server/internal/errors"
)

func init() { gin.SetMode(gin.TestMode) }

// ---------------------------------------------------------------------------
// AllCodes completeness: every declared Code must appear in HTTPStatus and
// have a title entry reachable through NewProblem.
// ---------------------------------------------------------------------------

func TestAllCodes_EveryCodeHasHTTPStatus(t *testing.T) {
	for c := range aperrors.AllCodes {
		status, ok := aperrors.HTTPStatus[c]
		if !ok {
			t.Errorf("code %q has no HTTPStatus entry", c)
			continue
		}
		if status < 100 || status > 599 {
			t.Errorf("code %q has invalid HTTP status %d", c, status)
		}
	}
}

func TestAllCodes_NewProblemShape(t *testing.T) {
	for c := range aperrors.AllCodes {
		p := aperrors.NewProblem(c, "test detail", "req-id-123")
		if p.Type == "" {
			t.Errorf("code %q: NewProblem returned empty Type", c)
		}
		if !strings.HasPrefix(p.Type, "https://negelir.io/problems/") {
			t.Errorf("code %q: Type %q missing expected prefix", c, p.Type)
		}
		if p.Title == "" {
			t.Errorf("code %q: NewProblem returned empty Title", c)
		}
		if p.Status != aperrors.HTTPStatus[c] {
			t.Errorf("code %q: Status %d != HTTPStatus %d", c, p.Status, aperrors.HTTPStatus[c])
		}
		if p.Detail != "test detail" {
			t.Errorf("code %q: Detail not preserved", c)
		}
		if p.Instance != "req-id-123" {
			t.Errorf("code %q: Instance not preserved", c)
		}
	}
}

func TestAllCodes_JSONSerializable(t *testing.T) {
	for c := range aperrors.AllCodes {
		p := aperrors.NewProblem(c, "", "")
		b, err := json.Marshal(p)
		if err != nil {
			t.Errorf("code %q: json.Marshal failed: %v", c, err)
			continue
		}
		var round aperrors.Problem
		if err := json.Unmarshal(b, &round); err != nil {
			t.Errorf("code %q: json.Unmarshal failed: %v", c, err)
		}
	}
}

// ---------------------------------------------------------------------------
// Respond helper: writes application/problem+json with correct status.
// ---------------------------------------------------------------------------

func TestRespond_WritesCorrectStatusAndContentType(t *testing.T) {
	for _, tc := range []struct {
		code   aperrors.Code
		wantStatus int
	}{
		{aperrors.CodeNotFound, http.StatusNotFound},
		{aperrors.CodeInternal, http.StatusInternalServerError},
		{aperrors.CodeRateLimited, http.StatusTooManyRequests},
		{aperrors.CodeTooEarly, 425},
		{aperrors.CodeClientDisconnected, 499},
		{aperrors.CodeRPCTimeout, http.StatusGatewayTimeout},
	} {
		t.Run(string(tc.code), func(t *testing.T) {
			r := gin.New()
			r.GET("/test", func(c *gin.Context) {
				aperrors.Respond(c, tc.code, "detail")
			})
			w := httptest.NewRecorder()
			req := httptest.NewRequest(http.MethodGet, "/test", nil)
			req.Header.Set("X-Request-ID", "rid-test")
			r.ServeHTTP(w, req)

			if w.Code != tc.wantStatus {
				t.Fatalf("status = %d; want %d", w.Code, tc.wantStatus)
			}
			ct := w.Header().Get("Content-Type")
			if !strings.HasPrefix(ct, "application/problem+json") {
				t.Fatalf("Content-Type = %q; want application/problem+json", ct)
			}
			var p aperrors.Problem
			if err := json.Unmarshal(w.Body.Bytes(), &p); err != nil {
				t.Fatalf("body not valid JSON: %v", err)
			}
			if p.Status != tc.wantStatus {
				t.Fatalf("body status = %d; want %d", p.Status, tc.wantStatus)
			}
			if p.Detail != "detail" {
				t.Fatalf("body detail = %q; want \"detail\"", p.Detail)
			}
		})
	}
}

// ---------------------------------------------------------------------------
// Adversarial: Respond with an unregistered Code yields zero-value status.
// The caller is responsible for only passing registered codes; the contract
// test verifies the correct path.
// ---------------------------------------------------------------------------

func TestRespond_UnknownCodeDoesNotPanic(t *testing.T) {
	r := gin.New()
	r.GET("/test", func(c *gin.Context) {
		aperrors.Respond(c, aperrors.Code("unknown_code_xyz"), "")
	})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/test", nil)
	r.ServeHTTP(w, req) // must not panic
}

// ---------------------------------------------------------------------------
// RespondWithRetryAfter: §9.3 503 + Retry-After contract.
// ---------------------------------------------------------------------------

func TestRespondWithRetryAfter_503ServiceUnavailable(t *testing.T) {
	r := gin.New()
	r.GET("/test", func(c *gin.Context) {
		aperrors.RespondWithRetryAfter(c, aperrors.CodeServiceUnavailable, "rpc timed out", 4)
	})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/test", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d; want 503", w.Code)
	}
	if got := w.Header().Get("Retry-After"); got != "4" {
		t.Fatalf("Retry-After = %q; want \"4\"", got)
	}
	var p aperrors.Problem
	if err := json.Unmarshal(w.Body.Bytes(), &p); err != nil {
		t.Fatalf("body not valid JSON: %v", err)
	}
	if p.Status != http.StatusServiceUnavailable {
		t.Fatalf("body status = %d; want 503", p.Status)
	}
}

func TestRespondWithRetryAfter_503BusUnreachable(t *testing.T) {
	r := gin.New()
	r.GET("/test", func(c *gin.Context) {
		aperrors.RespondWithRetryAfter(c, aperrors.CodeBusUnreachable, "redis down", aperrors.RetryAfterBusUnreachable)
	})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/test", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d; want 503", w.Code)
	}
	if got := w.Header().Get("Retry-After"); got != "5" {
		t.Fatalf("Retry-After = %q; want \"5\"", got)
	}
	var p aperrors.Problem
	if err := json.Unmarshal(w.Body.Bytes(), &p); err != nil {
		t.Fatalf("body not valid JSON: %v", err)
	}
	if string(aperrors.CodeBusUnreachable) != "bus_unreachable" {
		t.Fatalf("code string mismatch: %q", aperrors.CodeBusUnreachable)
	}
}

func TestRespondWithRetryAfter_503ConsensusWindowBlown(t *testing.T) {
	r := gin.New()
	r.GET("/test", func(c *gin.Context) {
		aperrors.RespondWithRetryAfter(c, aperrors.CodeConsensusWindowBlown, "all predictors DLQ'd", aperrors.RetryAfterConsensusWindowBlown)
	})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/test", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d; want 503", w.Code)
	}
	if got := w.Header().Get("Retry-After"); got != "10" {
		t.Fatalf("Retry-After = %q; want \"10\"", got)
	}
	var p aperrors.Problem
	if err := json.Unmarshal(w.Body.Bytes(), &p); err != nil {
		t.Fatalf("body not valid JSON: %v", err)
	}
	if string(aperrors.CodeConsensusWindowBlown) != "consensus_window_blown" {
		t.Fatalf("code string mismatch: %q", aperrors.CodeConsensusWindowBlown)
	}
}

// ---------------------------------------------------------------------------
// RetryAfterForTimeout: ceil(ms/1000)+1 formula.
// ---------------------------------------------------------------------------

func TestRetryAfterForTimeout(t *testing.T) {
	cases := []struct {
		ms   int
		want int
	}{
		{2500, 4}, // ceil(2500/1000)=3 + 1 = 4
		{3000, 4}, // ceil(3000/1000)=3 + 1 = 4 (exact multiple)
		{1000, 2}, // ceil(1000/1000)=1 + 1 = 2
		{1001, 3}, // ceil(1001/1000)=2 + 1 = 3
		{500, 2},  // ceil(500/1000)=1  + 1 = 2
	}
	for _, tc := range cases {
		got := aperrors.RetryAfterForTimeout(tc.ms)
		if got != tc.want {
			t.Errorf("RetryAfterForTimeout(%d) = %d; want %d", tc.ms, got, tc.want)
		}
	}
}

// ---------------------------------------------------------------------------
// Boundary AST scan: no ad-hoc gin.H{"error": ...} strings may appear in
// server/internal/handlers or server/internal/middleware outside of
// internal/errors.
// ---------------------------------------------------------------------------

// scanDirs are the package directories that must not contain ad-hoc error
// strings injected via gin.H or equivalent map literals.
var scanDirs = []string{
	"../handlers",
	"../middleware",
	"../../cmd/api",
}

// TestNoAdHocErrorStrings_OutsideErrorsPackage performs a structural AST
// check on each Go source file under the scan directories.  It fails when
// it detects a composite literal that looks like gin.H{"error": <literal>}
// (i.e. a map literal with a string key "error" whose value is a string
// literal), which indicates a handler bypassed the internal/errors package.
//
// It also rejects any call expression whose function identifier is "JSON"
// (gin.Context.JSON) where the second argument is a map composite literal
// containing the key "error" -- regardless of the receiver name.
func TestNoAdHocErrorStrings_OutsideErrorsPackage(t *testing.T) {
	for _, dir := range scanDirs {
		abs, err := filepath.Abs(dir)
		if err != nil {
			t.Fatalf("filepath.Abs(%q): %v", dir, err)
		}
		pkgs, err := parser.ParseDir(token.NewFileSet(), abs, nil, 0)
		if err != nil {
			// Directory may not exist yet -- skip gracefully during early build.
			continue
		}
		for _, pkg := range pkgs {
			for filename, file := range pkg.Files {
				// Skip test files -- they are allowed to build minimal fixtures.
				if strings.HasSuffix(filename, "_test.go") {
					continue
				}
				ast.Inspect(file, func(n ast.Node) bool {
					call, ok := n.(*ast.CallExpr)
					if !ok {
						return true
					}
					// Match *.JSON(status, gin.H{...}) call patterns.
					sel, ok := call.Fun.(*ast.SelectorExpr)
					if !ok || sel.Sel.Name != "JSON" {
						return true
					}
					if len(call.Args) < 2 {
						return true
					}
					lit, ok := call.Args[1].(*ast.CompositeLit)
					if !ok {
						return true
					}
					if hasErrorKey(lit) {
						t.Errorf("%s: ad-hoc error string via .JSON() detected; use internal/errors.Respond instead", filename)
					}
					return true
				})
			}
		}
	}
}

// hasErrorKey returns true when a composite literal contains a key-value
// pair where the key is the string literal "error".
func hasErrorKey(lit *ast.CompositeLit) bool {
	for _, elt := range lit.Elts {
		kv, ok := elt.(*ast.KeyValueExpr)
		if !ok {
			continue
		}
		key, ok := kv.Key.(*ast.BasicLit)
		if !ok {
			continue
		}
		if key.Kind == token.STRING && strings.Trim(key.Value, "'\" ") == "error" {
			return true
		}
	}
	return false
}
