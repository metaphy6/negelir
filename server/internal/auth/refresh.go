package auth

// refresh.go -- Phase 9 §9.2 Token shape: refresh-token store.
//
// Refresh tokens are opaque 32-byte random values encoded as base64url
// (no padding). They are stored in Redis under the key:
//
//	auth:refresh:<sha256(token)[:16]>   -->  <userID>\n<scopes>
//
// TTL = cfg.api_refresh_ttl_s (default 30 days).
//
// Single-use rotation: on every /v1/auth/refresh call the old token is
// superseded and a NEW token is issued. The old token is preserved under
//
//	auth:refresh:prev:<sha256(old)[:16]>  -->  <sha256(new)[:16]>
//
// with TTL = cfg.api_refresh_replay_grace_s (default 30 s).
// Within the grace window the old token is accepted ONCE (idempotency for
// network retries); accepting it consumes the prev record (GETDEL) so a
// second replay after consumption --> ErrTokenRevoked + caller emits alert.
//
// Logout: delete auth:refresh:<key>.

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"fmt"
	"time"
)

// ErrTokenRevoked is returned when a refresh token does not exist and there
// is no active grace-period prev record. The caller should respond 401 and
// emit a sec.alert.v1{kind=refresh_token_replay} event.
var ErrTokenRevoked = errors.New("token_revoked")

// ErrTokenReplay is returned when the grace-period prev record for a
// superseded token is found and consumed. The caller should issue an
// idempotent response using the new-token-key hint.
var ErrTokenReplay = errors.New("token_replay_within_grace")

// RefreshRedis is the minimal Redis interface required by RefreshStore.
// Production: backed by go-redis. Tests: in-memory stub.
type RefreshRedis interface {
	// Set stores key-->value with the given TTL.
	Set(ctx context.Context, key, value string, ttl time.Duration) error
	// GetDel atomically gets the value and deletes the key.
	// Returns ("", nil) when the key does not exist.
	GetDel(ctx context.Context, key string) (string, error)
	// Get returns the value for key.
	// Returns ("", nil) when the key does not exist.
	Get(ctx context.Context, key string) (string, error)
	// Del removes the key. Does not error on missing key.
	Del(ctx context.Context, key string) error
}

// RefreshStore issues, rotates, and revokes refresh tokens via Redis.
type RefreshStore struct {
	redis    RefreshRedis
	ttl      time.Duration
	graceTTL time.Duration
}

// NewRefreshStore creates a RefreshStore using the given Redis client and TTLs.
func NewRefreshStore(r RefreshRedis, tokenTTL, graceTTL time.Duration) *RefreshStore {
	return &RefreshStore{redis: r, ttl: tokenTTL, graceTTL: graceTTL}
}

// Issue mints a new refresh token and stores it in Redis.
// The token is a 32-byte random value encoded as base64url (no padding).
// The stored value is "<userID>\n<scopes>" so the caller can reconstruct
// the user context on the next /v1/auth/refresh call.
func (s *RefreshStore) Issue(ctx context.Context, userID, scopes string) (string, error) {
	token, err := randomToken()
	if err != nil {
		return "", fmt.Errorf("refresh.Issue: generate token: %w", err)
	}
	key := activeKey(token)
	val := userID + "\n" + scopes
	if err := s.redis.Set(ctx, key, val, s.ttl); err != nil {
		return "", fmt.Errorf("refresh.Issue: store token: %w", err)
	}
	return token, nil
}

// Validate checks whether token is an active refresh token and returns the
// stored value ("<userID>\n<scopes>").
//
// If the active record is missing:
//   - If a grace-period prev record exists it is consumed (GETDEL) and
//     ErrTokenReplay is returned with the new-token-key hint.
//   - Otherwise ErrTokenRevoked is returned (caller must emit alert).
func (s *RefreshStore) Validate(ctx context.Context, token string) (value string, newKeyHint string, err error) {
	key := activeKey(token)
	val, err := s.redis.Get(ctx, key)
	if err != nil {
		return "", "", fmt.Errorf("refresh.Validate: redis get: %w", err)
	}
	if val != "" {
		return val, "", nil
	}

	// Active record missing -- check for a grace-period prev record.
	pk := prevKey(token)
	newKey, err := s.redis.GetDel(ctx, pk)
	if err != nil {
		return "", "", fmt.Errorf("refresh.Validate: redis getdel prev: %w", err)
	}
	if newKey != "" {
		return "", newKey, ErrTokenReplay
	}

	return "", "", ErrTokenRevoked
}

// Rotate supersedes oldToken with a freshly minted token.
//
//  1. Validates oldToken (active or within-grace).
//  2. Mints newToken, stores it with the full TTL.
//  3. Drops the active record for oldToken.
//  4. Stores a prev record (grace TTL) mapping oldToken --> newToken key.
//
// Returns ErrTokenRevoked when oldToken is neither active nor within grace.
func (s *RefreshStore) Rotate(ctx context.Context, oldToken string) (string, error) {
	oldKey := activeKey(oldToken)

	oldVal, err := s.redis.Get(ctx, oldKey)
	if err != nil {
		return "", fmt.Errorf("refresh.Rotate: get old token: %w", err)
	}

	var userID, scopes string
	if oldVal != "" {
		userID, scopes = splitVal(oldVal)
	} else {
		// No active record -- check for a prev (grace) record.
		pk := prevKey(oldToken)
		newKeyHint, gerr := s.redis.GetDel(ctx, pk)
		if gerr != nil {
			return "", fmt.Errorf("refresh.Rotate: getdel prev: %w", gerr)
		}
		if newKeyHint == "" {
			return "", ErrTokenRevoked
		}
		// Token was already rotated within grace; fetch the replacement value.
		newVal, gerr := s.redis.Get(ctx, "auth:refresh:"+newKeyHint)
		if gerr != nil || newVal == "" {
			return "", ErrTokenRevoked
		}
		userID, scopes = splitVal(newVal)
	}

	// Mint the new token.
	newToken, err := randomToken()
	if err != nil {
		return "", fmt.Errorf("refresh.Rotate: generate new token: %w", err)
	}
	newKey := activeKey(newToken)
	if err := s.redis.Set(ctx, newKey, userID+"\n"+scopes, s.ttl); err != nil {
		return "", fmt.Errorf("refresh.Rotate: store new token: %w", err)
	}

	// Store prev record for grace-window idempotency.
	newKeyShort := tokenKey(newToken)
	if serr := s.redis.Set(ctx, prevKey(oldToken), newKeyShort, s.graceTTL); serr != nil {
		_ = serr // non-fatal: worst-case a retry in grace window gets 401
	}

	// Delete the old active record.
	if oldVal != "" {
		_ = s.redis.Del(ctx, oldKey) // best-effort; TTL expires naturally
	}

	return newToken, nil
}

// Revoke removes the active refresh token from Redis (logout).
// Does not error on a missing key.
func (s *RefreshStore) Revoke(ctx context.Context, token string) error {
	if err := s.redis.Del(ctx, activeKey(token)); err != nil {
		return fmt.Errorf("refresh.Revoke: %w", err)
	}
	return nil
}

// -- internal helpers --------------------------------------------------------

// randomToken returns a 32-byte random value encoded as base64url (no padding).
func randomToken() (string, error) {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(b), nil
}

// tokenKey returns the first 16 hex chars of SHA-256(token).
// Used as the Redis key suffix to avoid storing the raw token in key names.
func tokenKey(token string) string {
	sum := sha256.Sum256([]byte(token))
	return hex.EncodeToString(sum[:8]) // 8 bytes = 16 hex chars
}

// activeKey returns the full Redis key for an active refresh token.
func activeKey(token string) string { return "auth:refresh:" + tokenKey(token) }

// prevKey returns the full Redis key for a grace-period prev record.
func prevKey(token string) string { return "auth:refresh:prev:" + tokenKey(token) }

// splitVal splits the stored value "<userID>\n<scopes>" into its parts.
func splitVal(val string) (userID, scopes string) {
	for i, c := range val {
		if c == '\n' {
			return val[:i], val[i+1:]
		}
	}
	return val, ""
}
