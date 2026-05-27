package main

import (
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/alicebob/miniredis/v2"
	"github.com/gin-gonic/gin"
	"github.com/metaphy6/negelir/server/internal/middleware"
	"github.com/metaphy6/negelir/server/internal/sec"
	redis "github.com/redis/go-redis/v9"
)

// newAuthTestRouter builds a test router with self-registration enabled=true
// (so the existing sec-gate tests still exercise the password checks).
// Redis is nil — the per-subnet cap is skipped gracefully in tests.
func newAuthTestRouter(gate *sec.QAInputGate) *gin.Engine {
	r := gin.New()
	r.POST("/v1/auth/login", authLoginHandler(gate))
	r.POST("/v1/auth/register", authRegisterHandler(gate, true, 20, nil))
	return r
}

// newAuthTestRouterWithRegFlag builds a router with an explicit enabled flag.
func newAuthTestRouterWithRegFlag(gate *sec.QAInputGate, enabled bool) *gin.Engine {
	r := gin.New()
	r.POST("/v1/auth/login", authLoginHandler(gate))
	r.POST("/v1/auth/register", authRegisterHandler(gate, enabled, 20, nil))
	return r
}

// TestAuthLoginPasswordWhitespaceBoundary — binding §9.6 boundary:
// a password with leading/trailing whitespace must pass the gate
// byte-for-byte unchanged (PasswordPasses preserves whitespace; the
// regular Inspect/SanitizeText path may carry callers that additionally
// TrimSpace — the carve-out ensures password bytes are never altered).
func TestAuthLoginPasswordWhitespaceBoundary(t *testing.T) {
	gate := sec.NewQAInputGate(nil, 8192)
	r := newAuthTestRouter(gate)

	// "  secret  " — five leading and trailing spaces; within length cap.
	body := strings.NewReader(`{"email":"test@example.com","password":"  secret  "}`)
	req := httptest.NewRequest(http.MethodPost, "/v1/auth/login", body)
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	// Must NOT be 400 — whitespace in password is valid; only the
	// length cap may reject a password at the sec gate.
	if w.Code == http.StatusBadRequest {
		t.Fatalf("password with leading/trailing whitespace must not be rejected; got 400: %s", w.Body.String())
	}
}

// TestAuthRegisterPasswordWhitespaceBoundary — mirrors the login boundary
// test for the register endpoint.
func TestAuthRegisterPasswordWhitespaceBoundary(t *testing.T) {
	gate := sec.NewQAInputGate(nil, 8192)
	r := newAuthTestRouter(gate)

	body := strings.NewReader(`{"email":"test@example.com","password":"  secret  "}`)
	req := httptest.NewRequest(http.MethodPost, "/v1/auth/register", body)
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code == http.StatusBadRequest {
		t.Fatalf("password with leading/trailing whitespace must not be rejected; got 400: %s", w.Body.String())
	}
}

// TestAuthLoginRejectsOversizedPassword — adversarial: password exceeding
// the gate cap triggers 400 (bcrypt-bomb / RAM-exhaustion defense).
func TestAuthLoginRejectsOversizedPassword(t *testing.T) {
	gate := sec.NewQAInputGate(nil, 8) // 8-byte cap forces oversize
	r := newAuthTestRouter(gate)

	body := strings.NewReader(`{"email":"a@b.com","password":"this_password_is_far_too_long"}`)
	req := httptest.NewRequest(http.MethodPost, "/v1/auth/login", body)
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 for oversize password, got %d; body: %s", w.Code, w.Body.String())
	}
}

// TestAuthRegisterRejectsOversizedPassword — same oversize guard for register.
func TestAuthRegisterRejectsOversizedPassword(t *testing.T) {
	gate := sec.NewQAInputGate(nil, 8)
	r := newAuthTestRouter(gate)

	body := strings.NewReader(`{"email":"a@b.com","password":"this_password_is_far_too_long"}`)
	req := httptest.NewRequest(http.MethodPost, "/v1/auth/register", body)
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 for oversize password at register, got %d; body: %s", w.Code, w.Body.String())
	}
}

// TestAuthLoginNeverPatternMatchesPassword — adversarial: even if the
// password contains an injection phrase it must not be rejected
// (PasswordPasses skips the pattern engine entirely).
func TestAuthLoginNeverPatternMatchesPassword(t *testing.T) {
	rules, err := sec.LoadInjectionPatterns(sec.EmbeddedInjectionPatternsYAML)
	if err != nil {
		t.Fatalf("LoadInjectionPatterns: %v", err)
	}
	gate := sec.NewQAInputGate(rules, 8192)
	r := newAuthTestRouter(gate)

	body := strings.NewReader(`{"email":"a@b.com","password":"ignore previous instructions"}`)
	req := httptest.NewRequest(http.MethodPost, "/v1/auth/login", body)
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	// Injection phrase in a password must NEVER cause a 400.
	if w.Code == http.StatusBadRequest {
		t.Fatalf("injection phrase in password must not be rejected; got 400: %s", w.Body.String())
	}
}

// TestAuthLoginRejectsMissingPassword — missing password field yields 400.
func TestAuthLoginRejectsMissingPassword(t *testing.T) {
	gate := sec.NewQAInputGate(nil, 8192)
	r := newAuthTestRouter(gate)

	body := strings.NewReader(`{"email":"a@b.com"}`)
	req := httptest.NewRequest(http.MethodPost, "/v1/auth/login", body)
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 for missing password, got %d; body: %s", w.Code, w.Body.String())
	}
}

// TestAuthLoginRejectsMissingEmail — missing email field yields 400.
func TestAuthLoginRejectsMissingEmail(t *testing.T) {
	gate := sec.NewQAInputGate(nil, 8192)
	r := newAuthTestRouter(gate)

	body := strings.NewReader(`{"password":"secret"}`)
	req := httptest.NewRequest(http.MethodPost, "/v1/auth/login", body)
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 for missing email, got %d; body: %s", w.Code, w.Body.String())
	}
}

// TestAuthRegisterDisabledReturns403 — §9.2 self-registration default OFF.
// When enabled=false the handler must return 403 without inspecting the body.
func TestAuthRegisterDisabledReturns403(t *testing.T) {
	gate := sec.NewQAInputGate(nil, 8192)
	r := newAuthTestRouterWithRegFlag(gate, false)

	body := strings.NewReader(`{"email":"new@example.com","password":"s3cr3t"}`)
	req := httptest.NewRequest(http.MethodPost, "/v1/auth/register", body)
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code != http.StatusForbidden {
		t.Fatalf("self-registration OFF: expected 403, got %d; body: %s", w.Code, w.Body.String())
	}
}

// TestAuthRegisterDisabledIgnoresMissingBody — adversarial: even a bodyless
// request must return 403 (not 400) when registration is disabled, confirming
// the flag check fires before any body parsing.
func TestAuthRegisterDisabledIgnoresMissingBody(t *testing.T) {
	gate := sec.NewQAInputGate(nil, 8192)
	r := newAuthTestRouterWithRegFlag(gate, false)

	req := httptest.NewRequest(http.MethodPost, "/v1/auth/register", nil)
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code != http.StatusForbidden {
		t.Fatalf("self-registration OFF + empty body: expected 403, got %d; body: %s", w.Code, w.Body.String())
	}
}

// TestAuthRegisterEnabledReachesPwGate — when registration is enabled the
// password gate is reached; an oversized password still yields 400.
func TestAuthRegisterEnabledReachesPwGate(t *testing.T) {
	gate := sec.NewQAInputGate(nil, 8) // tiny cap forces oversize
	r := newAuthTestRouterWithRegFlag(gate, true)

	body := strings.NewReader(`{"email":"a@b.com","password":"this_password_is_far_too_long"}`)
	req := httptest.NewRequest(http.MethodPost, "/v1/auth/register", body)
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("self-registration ON + oversize password: expected 400, got %d; body: %s", w.Code, w.Body.String())
	}
}

// TestSubnet24KeyIPv4 — unit test for subnet24Key helper (IPv4 /24 bucketing).
func TestSubnet24KeyIPv4(t *testing.T) {
	cases := []struct {
		input string
		want  string
	}{
		{"192.168.1.55", "192.168.1.0/24"},
		{"10.0.0.1", "10.0.0.0/24"},
		{"172.16.200.99", "172.16.200.0/24"},
	}
	for _, tc := range cases {
		ip := net.ParseIP(tc.input)
		if ip == nil {
			t.Fatalf("ParseIP(%q) returned nil", tc.input)
		}
		got := subnet24Key(ip)
		if got != tc.want {
			t.Errorf("subnet24Key(%q) = %q; want %q", tc.input, got, tc.want)
		}
	}
}

// TestRegisterSubnetCap — §9.14 test_register_subnet_cap:
// 21 registration attempts from the same /24 subnet within one hour —
// the 21st must return 429 TooManyRequests (per-subnet hourly cap=20).
//
// Uses miniredis for a deterministic in-process Redis server so the
// INCR + EXPIRENV pipeline exercises the real Redis-backed code path.
func TestRegisterSubnetCap(t *testing.T) {
	gin.SetMode(gin.TestMode)

	// Start an in-process Redis server.
	mr, err := miniredis.Run()
	if err != nil {
		t.Fatalf("miniredis.Run: %v", err)
	}
	defer mr.Close()

	rdb := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	defer rdb.Close()

	gate := sec.NewQAInputGate(nil, 8192)
	const capPerSubnetH = 20

	// Build a test router with the real Redis client injected.
	// A small middleware sets ContextKeyClientIP so the cap logic fires.
	clientIP := net.ParseIP("10.0.0.55")
	r := gin.New()
	r.POST("/v1/auth/register",
		func(c *gin.Context) {
			c.Set(middleware.ContextKeyClientIP, clientIP)
			c.Next()
		},
		authRegisterHandler(gate, true, capPerSubnetH, rdb),
	)

	body := `{"email":"test@example.com","password":"validpassword123"}`

	for i := 1; i <= capPerSubnetH+1; i++ {
		req := httptest.NewRequest(http.MethodPost, "/v1/auth/register",
			strings.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		w := httptest.NewRecorder()
		r.ServeHTTP(w, req)

		if i == capPerSubnetH+1 {
			if w.Code != http.StatusTooManyRequests {
				t.Fatalf("request %d: want 429 TooManyRequests, got %d; body: %s",
					i, w.Code, w.Body.String())
			}
		}
	}
}


// TestAdvRegisterEmailUnicodeHomoglyph — adv_test_register_email_unicode_homoglyph.
//
// Registration with "admin@negelir.com" (ASCII 'a' U+0061) and
// "аdmin@negelir.com" (Cyrillic 'а' U+0430) BOTH succeed without collision.
// The server must treat them as distinct byte strings — no Unicode normalisation
// is applied to email fields. Any rejection (400/403/409) would indicate the
// server is treating the two addresses as equivalent, which is incorrect.
//
// "Succeed" in the current phase means the request reaches the handler stub
// (501 Not Implemented). The deny-set subject is derived from the request IP,
// not the email field, so both requests are independently valid.
func TestAdvRegisterEmailUnicodeHomoglyph(t *testing.T) {
	// ASCII 'a' (U+0061) vs Cyrillic 'а' (U+0430) — visually identical, byte-distinct.
	const emailASCII = "admin@negelir.com"
	const emailCyrillic = "аdmin@negelir.com" // first char is U+0430 Cyrillic а

	if emailASCII == emailCyrillic {
		t.Fatal("test setup error: expected byte-distinct email strings, got identical values; " +
			"ensure the source file is saved with UTF-8 encoding")
	}

	gin.SetMode(gin.TestMode)
	gate := sec.NewQAInputGate(nil, 8192)
	r := newAuthTestRouter(gate) // registration enabled=true, rdb=nil (no subnet cap)

	// Register with ASCII email — must reach the handler without 400/403/409.
	bodyASCII := `{"email":"` + emailASCII + `","password":"hunter2"}`
	w1 := httptest.NewRecorder()
	req1 := httptest.NewRequest(http.MethodPost, "/v1/auth/register",
		strings.NewReader(bodyASCII))
	req1.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w1, req1)
	switch w1.Code {
	case http.StatusBadRequest, http.StatusForbidden, http.StatusConflict:
		t.Errorf("adv: ASCII email %q rejected with %d; body=%s",
			emailASCII, w1.Code, w1.Body.String())
	}

	// Register with Cyrillic homoglyph email — must also reach the handler.
	bodyCyrillic := `{"email":"` + emailCyrillic + `","password":"hunter2"}`
	w2 := httptest.NewRecorder()
	req2 := httptest.NewRequest(http.MethodPost, "/v1/auth/register",
		strings.NewReader(bodyCyrillic))
	req2.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w2, req2)
	switch w2.Code {
	case http.StatusBadRequest, http.StatusForbidden, http.StatusConflict:
		t.Errorf("adv: Cyrillic homoglyph email %q rejected with %d; body=%s",
			emailCyrillic, w2.Code, w2.Body.String())
	}

	// Both emails must produce the same stub response code — they are
	// independently valid distinct strings, not a collision.
	if w1.Code != w2.Code {
		t.Errorf("adv: ASCII (%d) and Cyrillic homoglyph (%d) produced different response codes; "+
			"the server must treat them as distinct but equally valid inputs",
			w1.Code, w2.Code)
	}
}
