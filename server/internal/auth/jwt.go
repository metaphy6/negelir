package auth

// jwt.go — Phase 9 §9.2 JWT (RS256 + KID rotation)
//
// KeyStore manages RS256 key lifecycle:
//   - InitOrLoad: generates kid_001 on first run, loads active+retired keys.
//   - Sign: signs a JWT using the single active key (kid header included).
//   - Verify: accepts tokens whose kid is active or retired; falls back to
//     the DB on a cache miss (covers replicas that missed the mtime-poll).
//   - RotateKey: full §9.2 runbook — pending → active, old → retired → purged.
//
// Private key material lives on disk at dir/<kid>.priv.pem (mode 0400).
// DB is the source of truth; the in-memory cache is an optimisation.

import (
	"crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"encoding/pem"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"

	jwt "github.com/golang-jwt/jwt/v5"
)

// JWT key status values — must match the CHECK constraint in migration 014.
const (
	KeyStatusPending = "pending"
	KeyStatusActive  = "active"
	KeyStatusRetired = "retired"
	KeyStatusPurged  = "purged"
)

// ErrKeyUnreadable is returned when a private key file cannot be loaded, or
// when a verified token references a purged/unknown kid.
// The startup probe in cmd/api/main.go maps this to a boot-abort tagged
// "jwt_key_unreadable".
var ErrKeyUnreadable = errors.New("jwt_key_unreadable")

// KeyRecord mirrors one row of the jwt_keys table (migration 014).
type KeyRecord struct {
	KID          string
	Alg          string
	PubPEM       string
	PrivPEMPath  string
	Status       string
	GeneratedAt  time.Time
	RotatedInAt  *time.Time
	RotatedOutAt *time.Time
}

// KeyStoreDB is the minimal DB interface required by KeyStore.
// Production: backed by pgx. Tests: in-memory stub.
type KeyStoreDB interface {
	// GetKeysByStatus returns all records with the given status.
	GetKeysByStatus(status string) ([]KeyRecord, error)
	// GetKeyByKID returns the record for a specific kid, or (nil, nil) when absent.
	GetKeyByKID(kid string) (*KeyRecord, error)
	// InsertKey inserts a new key record (typically with status=pending).
	InsertKey(rec KeyRecord) error
	// UpdateKeyStatus atomically sets the status of kid and records ts in the
	// appropriate rotated_*_at column.
	UpdateKeyStatus(kid, status string, ts time.Time) error
	// ListAllKIDs returns every kid present in the store (for sequencing new kids).
	ListAllKIDs() ([]string, error)
}

// KeyStore manages the RS256 JWT key lifecycle for the API.
// Thread-safe: Sign, Verify, and RotateKey may be called concurrently.
type KeyStore struct {
	dir string
	db  KeyStoreDB

	mu          sync.RWMutex
	verify      map[string]*rsa.PublicKey // active + retired keys
	clockLeeway time.Duration             // max exp overshoot tolerated (default 0)
	activeKID   string
	activePriv  *rsa.PrivateKey
}

// InitOrLoad initialises a KeyStore backed by dir/db.
//
// On first run (no active key in db), generates kid_001, writes the RSA-2048
// key pair atomically to disk, and promotes the key to active.
//
// Returns a wrapped ErrKeyUnreadable when the active key's private file is
// missing or corrupt — the caller must treat this as a boot-abort.
func InitOrLoad(dir string, db KeyStoreDB) (*KeyStore, error) {
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return nil, fmt.Errorf("jwt keystore mkdir %q: %w", dir, err)
	}

	ks := &KeyStore{
		dir:    dir,
		db:     db,
		verify: make(map[string]*rsa.PublicKey),
	}

	active, err := db.GetKeysByStatus(KeyStatusActive)
	if err != nil {
		return nil, fmt.Errorf("jwt keystore: load active keys: %w", err)
	}

	// First run: generate kid_001 and activate it.
	if len(active) == 0 {
		kid, err := nextKID(db)
		if err != nil {
			return nil, fmt.Errorf("jwt keystore: determine initial kid: %w", err)
		}
		if err := ks.generateKey(kid); err != nil {
			return nil, fmt.Errorf("jwt keystore: generate initial key: %w", err)
		}
		now := time.Now().UTC()
		if err := db.UpdateKeyStatus(kid, KeyStatusActive, now); err != nil {
			return nil, fmt.Errorf("jwt keystore: activate initial key: %w", err)
		}
		active, err = db.GetKeysByStatus(KeyStatusActive)
		if err != nil {
			return nil, fmt.Errorf("jwt keystore: reload after init: %w", err)
		}
	}

	if len(active) != 1 {
		return nil, fmt.Errorf("jwt keystore: expected exactly 1 active key, got %d", len(active))
	}

	// Load active private key into memory.
	priv, err := loadPrivKey(active[0].PrivPEMPath)
	if err != nil {
		return nil, fmt.Errorf("%w: %s: %v", ErrKeyUnreadable, active[0].KID, err)
	}
	pub, err := parsePublicKeyPEM(active[0].PubPEM)
	if err != nil {
		return nil, fmt.Errorf("jwt keystore: parse active pub pem for %q: %w", active[0].KID, err)
	}
	ks.activeKID = active[0].KID
	ks.activePriv = priv
	ks.verify[active[0].KID] = pub

	// Load retired keys (public only) so tokens signed before rotation still verify.
	retired, err := db.GetKeysByStatus(KeyStatusRetired)
	if err != nil {
		return nil, fmt.Errorf("jwt keystore: load retired keys: %w", err)
	}
	for _, rec := range retired {
		rpub, perr := parsePublicKeyPEM(rec.PubPEM)
		if perr != nil {
			continue // best-effort: a corrupted retired pub key must not block startup
		}
		ks.verify[rec.KID] = rpub
	}

	return ks, nil
}

// Sign creates a signed RS256 JWT with the provided MapClaims.
// The token header carries the kid of the current active signing key.
func (ks *KeyStore) Sign(claims jwt.MapClaims) (string, error) {
	ks.mu.RLock()
	kid := ks.activeKID
	priv := ks.activePriv
	ks.mu.RUnlock()

	if priv == nil {
		return "", errors.New("jwt keystore: no active signing key loaded")
	}
	t := jwt.NewWithClaims(jwt.SigningMethodRS256, claims)
	t.Header["kid"] = kid
	return t.SignedString(priv)
}

// SetClockLeeway configures the maximum amount of clock drift tolerated when
// validating the exp and nbf claims. Must be called before concurrent use
// (typically once during server startup, from the loaded Config).
// Zero (the default) means strict exp/nbf validation with no tolerance.
// Values > 300 s should be blocked by config.Validate before reaching here.
func (ks *KeyStore) SetClockLeeway(d time.Duration) {
	ks.mu.Lock()
	ks.clockLeeway = d
	ks.mu.Unlock()
}

// Verify parses and validates a signed RS256 JWT.
// A token is accepted when its kid has status active or retired.
// Purged/unknown kids return a wrapped ErrKeyUnreadable.
//
// On a cache miss the verifier falls back to a DB lookup — this covers replicas
// that missed the mtime-poll window (the poll is an optimisation, DB is truth).
func (ks *KeyStore) Verify(tokenStr string) (jwt.MapClaims, error) {
	ks.mu.RLock()
	leeway := ks.clockLeeway
	ks.mu.RUnlock()

	p := jwt.NewParser(jwt.WithLeeway(leeway))
	token, err := p.ParseWithClaims(
		tokenStr,
		jwt.MapClaims{},
		func(t *jwt.Token) (interface{}, error) {
			if _, ok := t.Method.(*jwt.SigningMethodRSA); !ok {
				return nil, fmt.Errorf("unexpected signing method: %v", t.Header["alg"])
			}
			kidRaw, ok := t.Header["kid"]
			if !ok {
				return nil, errors.New("jwt: missing kid header")
			}
			kid, ok := kidRaw.(string)
			if !ok {
				return nil, errors.New("jwt: kid header is not a string")
			}

			// Fast path: in-memory cache.
			ks.mu.RLock()
			pub, found := ks.verify[kid]
			ks.mu.RUnlock()
			if found {
				return pub, nil
			}

			// DB fallback: replica may not have polled the keystore dir yet.
			rec, dbErr := ks.db.GetKeyByKID(kid)
			if dbErr != nil {
				return nil, fmt.Errorf("jwt: db lookup for kid %q: %w", kid, dbErr)
			}
			if rec == nil {
				return nil, fmt.Errorf("%w: unknown kid %q", ErrKeyUnreadable, kid)
			}
			if rec.Status == KeyStatusPurged || rec.Status == KeyStatusPending {
				return nil, fmt.Errorf("%w: kid %q has status %q", ErrKeyUnreadable, kid, rec.Status)
			}
			pub, parseErr := parsePublicKeyPEM(rec.PubPEM)
			if parseErr != nil {
				return nil, fmt.Errorf("jwt: parse pub pem for kid %q: %w", kid, parseErr)
			}
			// Cache the key to avoid repeated DB lookups.
			ks.mu.Lock()
			ks.verify[kid] = pub
			ks.mu.Unlock()
			return pub, nil
		},
	)
	if err != nil {
		return nil, err
	}
	if !token.Valid {
		return nil, errors.New("jwt: invalid token")
	}
	claims, ok := token.Claims.(jwt.MapClaims)
	if !ok {
		return nil, errors.New("jwt: unexpected claims type")
	}
	return claims, nil
}

// RotateKey implements the §9.2 rotation runbook:
//
//	generate kid_NNN (pending)
//	→ warmWait (60 s in production, 0 in tests)
//	→ flip to active (old active → retired)
//	→ grace wait (cfg.api_jwt_retired_grace_s)
//	→ purge (zeroize + remove priv file, status=purged, remove from cache)
//
// Designed to be invoked by the `make api.rotate-jwt-key` operator tool.
func (ks *KeyStore) RotateKey(warmWait, grace time.Duration) error {
	newKID, err := nextKID(ks.db)
	if err != nil {
		return fmt.Errorf("rotate: determine next kid: %w", err)
	}

	if err := ks.generateKey(newKID); err != nil {
		return fmt.Errorf("rotate: generate %q: %w", newKID, err)
	}

	if warmWait > 0 {
		time.Sleep(warmWait)
	}

	oldActives, err := ks.db.GetKeysByStatus(KeyStatusActive)
	if err != nil {
		return fmt.Errorf("rotate: lookup active keys: %w", err)
	}

	now := time.Now().UTC()
	if err := ks.db.UpdateKeyStatus(newKID, KeyStatusActive, now); err != nil {
		return fmt.Errorf("rotate: activate %q: %w", newKID, err)
	}
	for _, old := range oldActives {
		if err := ks.db.UpdateKeyStatus(old.KID, KeyStatusRetired, now); err != nil {
			return fmt.Errorf("rotate: retire %q: %w", old.KID, err)
		}
	}

	// Load new active key into memory.
	newPrivPath := filepath.Join(ks.dir, newKID+".priv.pem")
	priv, err := loadPrivKey(newPrivPath)
	if err != nil {
		return fmt.Errorf("%w: %s: %v", ErrKeyUnreadable, newKID, err)
	}
	pubData, err := os.ReadFile(filepath.Join(ks.dir, newKID+".pub.pem"))
	if err != nil {
		return fmt.Errorf("rotate: read pub pem for %q: %w", newKID, err)
	}
	pub, err := parsePublicKeyPEM(string(pubData))
	if err != nil {
		return fmt.Errorf("rotate: parse pub pem for %q: %w", newKID, err)
	}
	ks.mu.Lock()
	ks.activeKID = newKID
	ks.activePriv = priv
	ks.verify[newKID] = pub
	// Retired keys remain in verify until the grace period elapses.
	ks.mu.Unlock()

	if grace > 0 {
		time.Sleep(grace)
	}

	// Purge: zeroize priv file, update DB, remove from verify cache.
	for _, old := range oldActives {
		privPath := filepath.Join(ks.dir, old.KID+".priv.pem")
		zeroizeAndRemove(privPath)
		if err := ks.db.UpdateKeyStatus(old.KID, KeyStatusPurged, time.Now().UTC()); err != nil {
			return fmt.Errorf("rotate: purge %q: %w", old.KID, err)
		}
		ks.mu.Lock()
		delete(ks.verify, old.KID)
		ks.mu.Unlock()
	}
	return nil
}

// ─── internal helpers ────────────────────────────────────────────────────────

func (ks *KeyStore) generateKey(kid string) error {
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		return fmt.Errorf("rsa.GenerateKey: %w", err)
	}
	pubPEM := pem.EncodeToMemory(&pem.Block{
		Type:  "RSA PUBLIC KEY",
		Bytes: x509.MarshalPKCS1PublicKey(&key.PublicKey),
	})
	privPEM := pem.EncodeToMemory(&pem.Block{
		Type:  "RSA PRIVATE KEY",
		Bytes: x509.MarshalPKCS1PrivateKey(key),
	})
	pubPath := filepath.Join(ks.dir, kid+".pub.pem")
	privPath := filepath.Join(ks.dir, kid+".priv.pem")
	if err := atomicWrite(pubPath, pubPEM, 0o644); err != nil {
		return fmt.Errorf("write pub pem: %w", err)
	}
	if err := atomicWrite(privPath, privPEM, 0o400); err != nil {
		return fmt.Errorf("write priv pem: %w", err)
	}
	return ks.db.InsertKey(KeyRecord{
		KID:         kid,
		Alg:         "RS256",
		PubPEM:      string(pubPEM),
		PrivPEMPath: privPath,
		Status:      KeyStatusPending,
		GeneratedAt: time.Now().UTC(),
	})
}

func nextKID(db KeyStoreDB) (string, error) {
	kids, err := db.ListAllKIDs()
	if err != nil {
		return "", fmt.Errorf("ListAllKIDs: %w", err)
	}
	maxSeq := 0
	for _, k := range kids {
		var n int
		if _, err := fmt.Sscanf(k, "kid_%d", &n); err == nil && n > maxSeq {
			maxSeq = n
		}
	}
	return fmt.Sprintf("kid_%03d", maxSeq+1), nil
}

func loadPrivKey(path string) (*rsa.PrivateKey, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	block, _ := pem.Decode(data)
	if block == nil || block.Type != "RSA PRIVATE KEY" {
		return nil, errors.New("failed to decode RSA PRIVATE KEY PEM block")
	}
	return x509.ParsePKCS1PrivateKey(block.Bytes)
}

func parsePublicKeyPEM(pemStr string) (*rsa.PublicKey, error) {
	block, _ := pem.Decode([]byte(pemStr))
	if block == nil {
		return nil, errors.New("failed to decode public key PEM block")
	}
	return x509.ParsePKCS1PublicKey(block.Bytes)
}

func atomicWrite(path string, data []byte, mode os.FileMode) error {
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, mode); err != nil {
		return err
	}
	if err := os.Chmod(tmp, mode); err != nil {
		os.Remove(tmp) //nolint:errcheck
		return err
	}
	return os.Rename(tmp, path)
}

func zeroizeAndRemove(path string) {
	// chmod to 0o600 first so we can open for writing; the file was created
	// 0o400 (owner-read-only) and os.OpenFile(O_WRONLY) would fail without this.
	_ = os.Chmod(path, 0o600) //nolint:errcheck // best-effort; proceed regardless
	f, err := os.OpenFile(path, os.O_WRONLY, 0)
	if err == nil {
		fi, err := f.Stat()
		if err == nil {
			noise := make([]byte, fi.Size())
			rand.Read(noise) //nolint:errcheck // best-effort; failure still removes file
			f.Write(noise)   //nolint:errcheck
		}
		f.Close()
	}
	os.Remove(path) //nolint:errcheck // always attempt removal, even if zeroize failed
}
