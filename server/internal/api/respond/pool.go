// Package respond provides Phase 9 response-shaping helpers.
//
// §9.17.2 zero-allocation discipline: this file adds pool.go, which backs
// every JSON response through a sync.Pool of (*bytes.Buffer, *json.Encoder)
// pairs, keeping per-request allocations at ≤ 4 on the cache-hit path.
package respond

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"sync"

	"github.com/metaphy6/negelir/server/internal/api/headers"
)

// maxPooledCap is the buffer capacity ceiling for pool retention.
// Buffers whose capacity exceeds 64 KiB after encoding are dropped rather
// than returned to the pool, preventing a single large QA reply from
// pinning 1 MiB of heap on the goroutine that handled it.
const maxPooledCap = 64 << 10 // 64 KiB

// copyBufSize is the size of copy buffers handed to io.CopyBuffer.
// Using a pooled 32 KiB buffer avoids the per-call allocation that bare
// io.Copy would incur (it allocates a fresh 32 KiB buffer per call).
const copyBufSize = 32 << 10 // 32 KiB

// encoderBuf pairs a bytes.Buffer with a json.Encoder that writes to it.
// Pooling both together avoids allocating a new json.Encoder per request.
// After acquiring from the pool, call buf.Reset() before re-use; the encoder
// still points at the same (now empty) buffer and its internal type-encoder
// cache is warm, keeping Encode() allocation-free on repeated calls.
type encoderBuf struct {
	buf *bytes.Buffer
	enc *json.Encoder
}

// bufPool is the central pool of (bytes.Buffer, json.Encoder) pairs.
// SetEscapeHTML(false) is set once at creation; re-pooled encoders retain it.
var bufPool = sync.Pool{
	New: func() any {
		buf := &bytes.Buffer{}
		enc := json.NewEncoder(buf)
		enc.SetEscapeHTML(false)
		return &encoderBuf{buf: buf, enc: enc}
	},
}

// copyBufPool is a pool of 32 KiB byte slices used by Copy.
var copyBufPool = sync.Pool{
	New: func() any {
		b := make([]byte, copyBufSize)
		return &b
	},
}

// JSON encodes payload to JSON and writes it to w with the given HTTP status
// code. It acquires a pooled (bytes.Buffer, json.Encoder) pair to avoid
// per-request allocations on the cache-hit hot path.
//
// Allocation contract (§9.17.2): ≤ 4 allocs per call on a warm pool with a
// simple struct payload. Verified by TestRespondZeroAlloc.
//
// Buffers whose capacity exceeds maxPooledCap (64 KiB) after encoding are
// dropped rather than returned to the pool.
func JSON(w http.ResponseWriter, status int, payload any) error {
	eb := bufPool.Get().(*encoderBuf)
	eb.buf.Reset()

	if err := eb.enc.Encode(payload); err != nil {
		// Do not return a failed encoder to the pool: enc.err is now set and
		// all future Encode calls on the same encoder would immediately error.
		return err
	}

	w.Header().Set(headers.ContentType, headers.MIMEApplicationJSON)
	w.WriteHeader(status)
	_, writeErr := w.Write(eb.buf.Bytes())

	if eb.buf.Cap() <= maxPooledCap {
		bufPool.Put(eb)
	}
	// Oversize buffer is not returned: it will be GC'd, preventing pool bloat.

	return writeErr
}

// Copy writes src to dst using a pooled 32 KiB scratch buffer, satisfying the
// §9.17.2 requirement that streaming responses MUST NOT use bare io.Copy
// (which allocates a fresh 32 KiB buffer on every call).
//
// Use this instead of io.Copy for any response body that is streamed rather
// than buffered (e.g. the future /v1/leagues/.../export.csv endpoint).
func Copy(dst io.Writer, src io.Reader) (int64, error) {
	bufPtr := copyBufPool.Get().(*[]byte)
	n, err := io.CopyBuffer(dst, src, *bufPtr)
	copyBufPool.Put(bufPtr)
	return n, err
}
