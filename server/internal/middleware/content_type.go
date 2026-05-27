package middleware

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
)

// legalContentTypes is the closed set of Content-Type values that Phase 9
// handlers are allowed to produce.  "application/json" covers the
// charset-qualified variant because we match by prefix.
var legalContentTypePrefixes = []string{
	"application/json",
	"application/problem+json",
}

// illegalContentTypePrefixes are prefixes that MUST never appear on a
// Phase 9 response — rejected at the response-writer level so that a
// handler bug or accidental Gin default cannot leak HTML/plain text.
var illegalContentTypePrefixes = []string{
	"text/html",
	"text/plain",
}

// problemEnvelope is the RFC 7807 body written when the enforcing writer
// intercepts an illegal content-type.
type problemEnvelope struct {
	Type     string `json:"type"`
	Title    string `json:"title"`
	Status   int    `json:"status"`
	Detail   string `json:"detail,omitempty"`
	Instance string `json:"instance,omitempty"`
}

// enforcingWriter wraps gin.ResponseWriter.  On the first Write or
// WriteString call it checks the already-set Content-Type header.
// If the content-type is text/html or text/plain the original body is
// discarded and a 500 application/problem+json body is written instead.
type enforcingWriter struct {
	gin.ResponseWriter
	intercepted bool
	reqID       string
}

// Write intercepts the first write to the body and enforces the
// content-type policy.
func (w *enforcingWriter) Write(b []byte) (int, error) {
	if !w.intercepted {
		w.intercepted = true
		if err := w.checkContentType(); err != nil {
			return len(b), nil // illegal body consumed / discarded
		}
	}
	return w.ResponseWriter.Write(b)
}

// WriteString is the string variant used by gin.Context.String — routes
// through Write so the same interception logic fires.
func (w *enforcingWriter) WriteString(s string) (int, error) {
	return w.Write([]byte(s))
}

// checkContentType inspects the current Content-Type header.  If it is
// illegal it resets the status to 500, sets the problem+json content-type,
// and writes an RFC 7807 body.  Returns a non-nil error when the type was
// illegal (Write discards the original body on non-nil).
func (w *enforcingWriter) checkContentType() error {
	ct := strings.ToLower(strings.TrimSpace(w.Header().Get("Content-Type")))
	for _, illegal := range illegalContentTypePrefixes {
		if strings.HasPrefix(ct, illegal) {
			// Override the response in-place before the first byte is flushed.
			w.Header().Set("Content-Type", "application/problem+json")
			w.ResponseWriter.WriteHeader(http.StatusInternalServerError)
			body, _ := json.Marshal(problemEnvelope{
				Type:     "https://negelir.io/problems/internal",
				Title:    "Illegal response content-type",
				Status:   http.StatusInternalServerError,
				Detail:   fmt.Sprintf("handler produced %q; only application/json or application/problem+json are permitted", ct),
				Instance: w.reqID,
			})
			_, _ = w.ResponseWriter.Write(body)
			return fmt.Errorf("illegal content-type: %s", ct)
		}
	}
	return nil
}

// EnforceContentType returns a Gin middleware that wraps every response
// writer with enforcingWriter.  Any response whose Content-Type begins with
// text/html or text/plain is replaced by a 500 application/problem+json
// body before the first byte reaches the socket.
//
// Legal values (§9.1 content-type discipline):
//   - application/json; charset=utf-8   (normal responses)
//   - application/problem+json          (RFC 7807 error bodies)
func EnforceContentType() gin.HandlerFunc {
	return func(c *gin.Context) {
		ew := &enforcingWriter{
			ResponseWriter: c.Writer,
			reqID:          c.GetHeader("X-Request-ID"),
		}
		c.Writer = ew
		c.Next()
	}
}
