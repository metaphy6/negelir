package auth

// export_test.go — test-only helpers that expose KeyStore internals.
// Compiled only during `go test`; not part of the production binary.

import "crypto/rsa"

// ClearVerifyCache empties the in-memory public-key cache.
// Used in TestVerify_DBFallback to simulate a replica that has not yet
// populated its local cache (mtime-poll window not yet elapsed).
func (ks *KeyStore) ClearVerifyCache() {
	ks.mu.Lock()
	defer ks.mu.Unlock()
	ks.verify = make(map[string]*rsa.PublicKey)
}
