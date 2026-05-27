package middleware

import (
	"net/http"
	"net/http/httptest"
	"regexp"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
)

// uuidv7Re matches the canonical UUID string format (8-4-4-4-12 hex groups)
// and additionally checks that the version nibble is 7 and the variant
// nibble is in {8,9,a,b} (RFC 4122 variant 10xxxxxx).
var uuidv7Re = regexp.MustCompile(
	`^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`,
)

// newRIDRouter builds a minimal Gin engine with RequestID applied.
func newRIDRouter(h gin.HandlerFunc) *gin.Engine {
	r := gin.New()
	r.Use(RequestID())
	r.GET("/ping", h)
	return r
}

// TestRequestID_EchoesClientSupplied verifies that a client-supplied
// X-Request-ID is echoed back unchanged in the response header.
func TestRequestID_EchoesClientSupplied(t *testing.T) {
	r := newRIDRouter(func(c *gin.Context) { c.Status(http.StatusOK) })

	const supplied = "my-custom-request-id"
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/ping", nil)
	req.Header.Set("X-Request-ID", supplied)
	r.ServeHTTP(w, req)

	got := w.Header().Get("X-Request-ID")
	if got != supplied {
		t.Fatalf("X-Request-ID echoed = %q; want %q", got, supplied)
	}
}

// TestRequestID_MintsWhenAbsent verifies that when no X-Request-ID is
// supplied the middleware mints one and sets it on the response.
func TestRequestID_MintsWhenAbsent(t *testing.T) {
	r := newRIDRouter(func(c *gin.Context) { c.Status(http.StatusOK) })

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/ping", nil)
	r.ServeHTTP(w, req)

	got := w.Header().Get("X-Request-ID")
	if got == "" {
		t.Fatal("X-Request-ID response header is empty; want minted UUIDv7")
	}
}

// TestRequestID_MintedIsUUIDv7 verifies that the minted ID conforms to
// UUIDv7: version nibble = 7, variant nibble in {8,9,a,b}.
func TestRequestID_MintedIsUUIDv7(t *testing.T) {
	r := newRIDRouter(func(c *gin.Context) { c.Status(http.StatusOK) })

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/ping", nil)
	r.ServeHTTP(w, req)

	got := w.Header().Get("X-Request-ID")
	if !uuidv7Re.MatchString(got) {
		t.Fatalf("minted X-Request-ID %q does not match UUIDv7 pattern", got)
	}
}

// TestRequestID_SetInContext verifies that ContextKeyRequestID in the
// Gin context matches the response X-Request-ID header.
func TestRequestID_SetInContext(t *testing.T) {
	var contextID string
	r := newRIDRouter(func(c *gin.Context) {
		v, _ := c.Get(ContextKeyRequestID)
		contextID, _ = v.(string)
		c.Status(http.StatusOK)
	})

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/ping", nil)
	r.ServeHTTP(w, req)

	headerID := w.Header().Get("X-Request-ID")
	if contextID == "" {
		t.Fatal("ContextKeyRequestID not set in Gin context")
	}
	if contextID != headerID {
		t.Fatalf("context ID %q != header ID %q", contextID, headerID)
	}
}

// TestRequestID_Sortable verifies that two consecutively minted UUIDv7s
// sort lexicographically in creation order (timestamp prefix guarantee).
//
// UUIDv7 ordering is only guaranteed when the two IDs are generated in
// different milliseconds (the 48-bit timestamp prefix sorts correctly).
// Within the same millisecond the random fields are independent, so no
// ordering guarantee holds.  The test waits >1 ms between minting to
// exercise the cross-millisecond claim.
func TestRequestID_Sortable(t *testing.T) {
	a := newUUIDv7()
	time.Sleep(2 * time.Millisecond) // ensure different ms timestamp prefix
	b := newUUIDv7()
	if a == "" || b == "" {
		t.Fatal("newUUIDv7 returned empty string")
	}
	if !uuidv7Re.MatchString(a) {
		t.Fatalf("first UUID %q does not match UUIDv7 pattern", a)
	}
	if !uuidv7Re.MatchString(b) {
		t.Fatalf("second UUID %q does not match UUIDv7 pattern", b)
	}
	// Different milliseconds: a must sort strictly before b.
	if a >= b {
		t.Fatalf("UUIDv7 ordering violated: %q >= %q (expected a < b across different ms)", a, b)
	}
}

// TestRequestID_EchoNotOverwritten verifies that a supplied X-Request-ID
// is stored verbatim in the context (not a freshly minted UUID).
func TestRequestID_EchoNotOverwritten(t *testing.T) {
	const supplied = "echo-check-42"
	var contextID string
	r := newRIDRouter(func(c *gin.Context) {
		v, _ := c.Get(ContextKeyRequestID)
		contextID, _ = v.(string)
		c.Status(http.StatusOK)
	})

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/ping", nil)
	req.Header.Set("X-Request-ID", supplied)
	r.ServeHTTP(w, req)

	if contextID != supplied {
		t.Fatalf("context ID %q; want %q (supplied value should be echoed into context)", contextID, supplied)
	}
}
