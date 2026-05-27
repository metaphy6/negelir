// Package cursor provides opaque AES-256-GCM encrypted pagination cursors.
//
// Cursor wire format: base64url(nonce ‖ ciphertext+tag)
// Plaintext JSON:     {"table":…,"last_pk":…,"query_filter_hash":…,"expires_at_unix":…}
//
// Seal key must be exactly 32 bytes (AES-256). The key lives in
// data/api/cursor_key (mode 0400) and is rotated alongside JWT keys per §9.2.
//
// Error mapping:
//
//	ErrInvalidCursor → HTTP 400 invalid_cursor   (tampered, expired, wrong key)
//	ErrFilterDrift   → HTTP 409 cursor_filter_drift (filter hash mismatch mid-pagination)
package cursor

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
)

// ErrInvalidCursor is returned when a cursor cannot be authenticated,
// is expired, or was sealed with a key that is no longer active.
// HTTP callers should map this to 400 invalid_cursor.
var ErrInvalidCursor = errors.New("cursor: invalid or expired cursor")

// ErrFilterDrift is returned when the filter hash embedded in the cursor
// does not match the filter hash supplied by the current request.
// HTTP callers should map this to 409 cursor_filter_drift.
var ErrFilterDrift = errors.New("cursor: filter hash mismatch (cursor_filter_drift)")

// Payload is the plaintext body sealed inside every pagination cursor.
type Payload struct {
	Table           string `json:"table"`
	LastPK          string `json:"last_pk"`
	QueryFilterHash string `json:"query_filter_hash"`
	ExpiresAtUnix   int64  `json:"expires_at_unix"`
}

// Seal encrypts p with AES-256-GCM using key and returns a URL-safe,
// unpadded base64 string. key must be exactly 32 bytes.
func Seal(key []byte, p Payload) (string, error) {
	plain, err := json.Marshal(p)
	if err != nil {
		return "", fmt.Errorf("cursor.Seal: marshal: %w", err)
	}

	block, err := aes.NewCipher(key)
	if err != nil {
		return "", fmt.Errorf("cursor.Seal: new cipher: %w", err)
	}

	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return "", fmt.Errorf("cursor.Seal: new gcm: %w", err)
	}

	nonce := make([]byte, gcm.NonceSize())
	if _, err = io.ReadFull(rand.Reader, nonce); err != nil {
		return "", fmt.Errorf("cursor.Seal: nonce: %w", err)
	}

	// Seal appends the ciphertext+tag to nonce, resulting in nonce‖ct.
	blob := gcm.Seal(nonce, nonce, plain, nil)
	return base64.RawURLEncoding.EncodeToString(blob), nil
}

// Unseal decrypts an encoded cursor (produced by Seal), verifies the
// AES-GCM authentication tag, checks expiry against nowUnix, and confirms
// that the embedded filter hash matches filterHash.
//
//   - Tampered bytes, invalid base64, or wrong key → ErrInvalidCursor
//   - expires_at_unix < nowUnix                    → ErrInvalidCursor
//   - QueryFilterHash ≠ filterHash                 → ErrFilterDrift
func Unseal(key []byte, encoded string, nowUnix int64, filterHash string) (*Payload, error) {
	raw, err := base64.RawURLEncoding.DecodeString(encoded)
	if err != nil {
		return nil, ErrInvalidCursor
	}

	block, err := aes.NewCipher(key)
	if err != nil {
		// Wrong key length — treat as invalid, not a server error.
		return nil, ErrInvalidCursor
	}

	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, ErrInvalidCursor
	}

	ns := gcm.NonceSize()
	if len(raw) < ns {
		return nil, ErrInvalidCursor
	}

	nonce, ct := raw[:ns], raw[ns:]

	plain, err := gcm.Open(nil, nonce, ct, nil)
	if err != nil {
		// Covers: wrong key, tampered byte — AES-GCM authentication-tag failure.
		return nil, ErrInvalidCursor
	}

	var p Payload
	if err := json.Unmarshal(plain, &p); err != nil {
		return nil, ErrInvalidCursor
	}

	if p.ExpiresAtUnix < nowUnix {
		return nil, ErrInvalidCursor
	}

	if p.QueryFilterHash != filterHash {
		return nil, ErrFilterDrift
	}

	return &p, nil
}
