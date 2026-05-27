package middleware

import (
	"bytes"
	"net/http"

	"github.com/gin-gonic/gin"
)

// etagBuf is a gin.ResponseWriter wrapper that buffers the response body so
// the ETagConditional middleware can inspect the ETag header AFTER the handler
// runs and downgrade the response to 304 when appropriate.
//
// Only Write/WriteString/WriteHeader/WriteHeaderNow are intercepted; all other
// gin.ResponseWriter methods delegate to the embedded writer.
type etagBuf struct {
	gin.ResponseWriter
	code    int
	body    bytes.Buffer
	written bool
}

func (b *etagBuf) WriteHeader(code int) {
	if !b.written {
		b.code = code
	}
}

func (b *etagBuf) WriteHeaderNow() {
	// Deferred — do nothing here; flush is called by ETagConditional.
}

func (b *etagBuf) Write(p []byte) (int, error) {
	b.written = true
	if b.code == 0 {
		b.code = http.StatusOK
	}
	return b.body.Write(p)
}

func (b *etagBuf) WriteString(s string) (int, error) {
	return b.Write([]byte(s))
}

func (b *etagBuf) Written() bool { return b.written }
func (b *etagBuf) Size() int     { return b.body.Len() }
func (b *etagBuf) Status() int {
	if b.code == 0 {
		return http.StatusOK
	}
	return b.code
}

// flush writes the captured status + body to the underlying writer.
func (b *etagBuf) flush() {
	if b.code > 0 {
		b.ResponseWriter.WriteHeader(b.code)
	}
	if b.body.Len() > 0 {
		b.ResponseWriter.Write(b.body.Bytes()) //nolint:errcheck
	}
}

// ETagConditional is a Gin middleware that implements RFC 7232 conditional
// GET via ETag / If-None-Match.
//
// Usage: register before the handler; the handler sets an ETag header via
// c.Header("ETag", value). When the request carries a matching If-None-Match
// the response is replaced with an empty 304 Not Modified.
//
// Only GET and HEAD requests are examined; all other methods pass through.
func ETagConditional() gin.HandlerFunc {
	return func(c *gin.Context) {
		if c.Request.Method != http.MethodGet && c.Request.Method != http.MethodHead {
			c.Next()
			return
		}

		inm := c.Request.Header.Get("If-None-Match")
		if inm == "" {
			// Fast path: no conditional header; skip buffering overhead.
			c.Next()
			return
		}

		// Buffer the response so we can inspect ETag before committing.
		buf := &etagBuf{ResponseWriter: c.Writer}
		c.Writer = buf
		c.Next()
		c.Writer = buf.ResponseWriter // restore before writing

		etag := buf.Header().Get("ETag")
		if etag != "" && (inm == etag || inm == "*") {
			// ETag matches: respond 304 with headers but no body.
			c.Writer.WriteHeader(http.StatusNotModified)
			return
		}
		buf.flush()
	}
}
