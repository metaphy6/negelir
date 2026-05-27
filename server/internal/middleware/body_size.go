package middleware

import (
	"bytes"
	"errors"
	"io"
	"net/http"

	"github.com/gin-gonic/gin"

	aperrors "github.com/metaphy6/negelir/server/internal/errors"
)

// BodySizeCap returns a Gin middleware that enforces a hard limit on the
// incoming request body size. It wraps c.Request.Body with
// http.MaxBytesReader, eagerly reads and buffers the entire body before
// the handler runs, and — if the body exceeds maxBytes — aborts with
// 413 application/problem+json.
//
// On success the body is replaced with an io.NopCloser over a bytes.Reader
// so downstream handlers can still read it normally.
//
// This is a defense-in-depth measure (bcrypt-bomb / RAM-exhaustion defense)
// applied BEFORE handler dispatch, as specified in §9.1.
func BodySizeCap(maxBytes int64) gin.HandlerFunc {
	return func(c *gin.Context) {
		if c.Request.Body == nil || c.Request.Body == http.NoBody {
			// Normalise nil / empty body to an empty readable stream so
			// downstream handlers never see a nil Body.
			c.Request.Body = io.NopCloser(bytes.NewReader(nil))
			c.Next()
			return
		}

		c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, maxBytes)
		buf, err := io.ReadAll(c.Request.Body)
		if err != nil {
			var maxErr *http.MaxBytesError
			if errors.As(err, &maxErr) {
				aperrors.Respond(c, aperrors.CodePayloadTooLarge,
					"request body exceeds the allowed size limit")
				c.Abort()
				return
			}
			aperrors.Respond(c, aperrors.CodeInternal, "failed to read request body")
			c.Abort()
			return
		}

		// Replace with a rewound reader so handlers receive a full body.
		c.Request.Body = io.NopCloser(bytes.NewReader(buf))
		c.Next()
	}
}
