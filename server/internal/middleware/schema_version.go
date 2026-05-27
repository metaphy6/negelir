package middleware

// schema_version.go -- Phase 9 section 9.11 schema-version stamping.
//
// SchemaVersionMiddleware wraps the Gin response writer to buffer the entire
// response body, then injects meta.schema_version into every JSON response
// object before flushing to the wire.
//
// Contract:
//   - Content-Type application/json or application/problem+json whose body
//     begins with '{': meta.schema_version is injected additively.
//   - If meta already exists and already contains schema_version: no-op.
//   - If meta already exists but lacks schema_version: the field is merged in
//     while all existing meta fields are preserved.
//   - Non-object JSON, non-JSON, and empty bodies: passed through unchanged.
//   - HTTP status from the handler is always preserved.
//
// Placement: register near the front of the chain (after RequestID) so both
// success and error (application/problem+json) responses are stamped.
//
// Limitation: streaming responses (SSE) are not supported; the entire body is
// buffered in memory. Do not register on streaming routes.

import (
	"bytes"
	"encoding/json"
	"net/http"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
)

// schemaBodyWriter buffers the response body and captures the status code
// set by the handler chain. The real write to the wire is deferred until the
// middleware flushes after c.Next() returns.
type schemaBodyWriter struct {
	gin.ResponseWriter
	buf    bytes.Buffer
	status int
}

func (w *schemaBodyWriter) Write(b []byte) (int, error)       { return w.buf.Write(b) }
func (w *schemaBodyWriter) WriteString(s string) (int, error) { return w.buf.WriteString(s) }
func (w *schemaBodyWriter) WriteHeaderNow()                   {}
func (w *schemaBodyWriter) Written() bool                     { return false }
func (w *schemaBodyWriter) Size() int                         { return w.buf.Len() }

func (w *schemaBodyWriter) WriteHeader(code int) {
	if code > 0 {
		w.status = code
	}
}

// SchemaVersionMiddleware returns a Gin middleware that injects
// {"meta": {"schema_version": schemaVersion}} into every JSON response body.
// schemaVersion should be cfg.APISchemaVersion (NEGELIR_API_SCHEMA_VERSION).
func SchemaVersionMiddleware(schemaVersion int) gin.HandlerFunc {
	return func(c *gin.Context) {
		bw := &schemaBodyWriter{ResponseWriter: c.Writer}
		c.Writer = bw

		c.Next()

		status := bw.status
		if status == 0 {
			status = http.StatusOK
		}

		body := bw.buf.Bytes()
		ct := bw.ResponseWriter.Header().Get("Content-Type")

		if isJSONContentType(ct) && len(body) > 0 && body[0] == '{' {
			if injected, ok := injectSchemaVersion(body, schemaVersion); ok {
				if bw.ResponseWriter.Header().Get("Content-Length") != "" {
					bw.ResponseWriter.Header().Set("Content-Length", strconv.Itoa(len(injected)))
				}
				body = injected
			}
		}

		// Set the captured status on the underlying gin.ResponseWriter, then
		// write the body. Gin's Write() calls WriteHeaderNow() internally so
		// the HTTP status line is flushed before the first body byte.
		bw.ResponseWriter.WriteHeader(status)
		bw.ResponseWriter.Write(body) //nolint:errcheck
	}
}

// isJSONContentType reports whether ct is application/json or
// application/problem+json (RFC 7807).
func isJSONContentType(ct string) bool {
	return strings.HasPrefix(ct, "application/json") ||
		strings.HasPrefix(ct, "application/problem+json")
}

// injectSchemaVersion unmarshals body as a JSON object and merges in
// meta.schema_version. Returns (modified, true) on success, or (nil, false)
// when body is not a valid JSON object.
func injectSchemaVersion(body []byte, version int) ([]byte, bool) {
	var obj map[string]json.RawMessage
	if err := json.Unmarshal(body, &obj); err != nil {
		return nil, false
	}

	if existing, ok := obj["meta"]; ok {
		var meta map[string]json.RawMessage
		if err := json.Unmarshal(existing, &meta); err == nil {
			if _, alreadySet := meta["schema_version"]; !alreadySet {
				sv, _ := json.Marshal(version)
				meta["schema_version"] = json.RawMessage(sv)
				if newMeta, err := json.Marshal(meta); err == nil {
					obj["meta"] = json.RawMessage(newMeta)
				}
			}
		}
	} else {
		sv, _ := json.Marshal(version)
		raw := append(append([]byte(`{"schema_version":`), sv...), '}')
		obj["meta"] = json.RawMessage(raw)
	}

	out, err := json.Marshal(obj)
	if err != nil {
		return nil, false
	}
	return out, true
}
