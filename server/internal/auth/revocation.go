package auth

// revocation.go — Phase 9 §9.2 Server-driven access-token revocation.
//
// Each explicitly revoked JTI is stored in Redis:
//
//	auth:rev:<jti>  →  "1"  (TTL = remaining token life)
//
// Cardinality is tracked via a sorted set so LRU eviction is O(log N):
//
//	auth:rev:idx  →  ZADD score=unix_micro member=jti
//
// When ZCARD auth:rev:idx exceeds cfg.api_revocation_set_max, the oldest
// entries (lowest score) are evicted (individual key + index member deleted).
//
// Pressure alert: when cardinality > 80% of the cap the injected AlertFunc
// fires sec.alert.v1{kind=jti_revocation_set_pressure, severity=warn}.
//
// IsRevoked is called on every authenticated request via a single Redis
// EXISTS call (sub-ms latency).

import (
	"context"
	"fmt"
	"time"
)

// revIndexKey is the sorted-set key used for cardinality tracking and LRU eviction.
const revIndexKey = "auth:rev:idx"

func revKey(jti string) string { return "auth:rev:" + jti }

// RevocationRedis is the minimal Redis interface required by RevocationStore.
// Production: backed by go-redis. Tests: in-memory stub.
type RevocationRedis interface {
	// Exists reports whether key is present in Redis.
	Exists(ctx context.Context, key string) (bool, error)
	// Set stores key → value with the given TTL. TTL 0 means no expiry.
	Set(ctx context.Context, key, value string, ttl time.Duration) error
	// Del removes a key. Must not error on a missing key.
	Del(ctx context.Context, key string) error
	// ZAdd adds member with score to sorted set key.
	ZAdd(ctx context.Context, key string, score float64, member string) error
	// ZCard returns the cardinality of sorted set key.
	ZCard(ctx context.Context, key string) (int64, error)
	// ZRangeByRank returns members in rank range [start, stop] (0-based, inclusive).
	ZRangeByRank(ctx context.Context, key string, start, stop int64) ([]string, error)
	// ZRemRangeByRank removes members in rank range [start, stop].
	ZRemRangeByRank(ctx context.Context, key string, start, stop int64) error
}

// RevocationAlertFunc is called when the deny-set crosses the 80% pressure
// threshold. kind is always "jti_revocation_set_pressure"; severity is "warn".
type RevocationAlertFunc func(ctx context.Context, kind, severity string)

// RevocationStore manages the per-JTI revocation deny-set in Redis.
// Thread-safe: all methods may be called concurrently.
type RevocationStore struct {
	redis   RevocationRedis
	max     int64
	alertFn RevocationAlertFunc
}

// NewRevocationStore creates a RevocationStore.
// max is cfg.api_revocation_set_max (default 10000 when ≤ 0).
// alertFn may be nil to disable pressure alerting.
func NewRevocationStore(r RevocationRedis, max int64, alertFn RevocationAlertFunc) *RevocationStore {
	if max <= 0 {
		max = 10000
	}
	return &RevocationStore{redis: r, max: max, alertFn: alertFn}
}

// Revoke adds jti to the revocation deny-set with TTL = remaining token life.
// When remaining ≤ 0 the call is a no-op (the token is already expired).
//
// After writing, the cap is enforced (oldest entries evicted) and a pressure
// alert fires when cardinality > 80% of max.
func (s *RevocationStore) Revoke(ctx context.Context, jti string, remaining time.Duration) error {
	if remaining <= 0 {
		return nil // token already expired; deny-set entry would be useless
	}

	if err := s.redis.Set(ctx, revKey(jti), "1", remaining); err != nil {
		return fmt.Errorf("revocation.Revoke: set key: %w", err)
	}

	score := float64(time.Now().UnixMicro())
	if err := s.redis.ZAdd(ctx, revIndexKey, score, jti); err != nil {
		// Non-fatal: individual key still exists; cardinality tracking is best-effort.
		_ = err
	}

	// Enforce cap: evict oldest entries when over limit.
	count, cardErr := s.redis.ZCard(ctx, revIndexKey)
	if cardErr == nil && count > s.max {
		excess := count - s.max
		victims, rangeErr := s.redis.ZRangeByRank(ctx, revIndexKey, 0, excess-1)
		if rangeErr == nil {
			_ = s.redis.ZRemRangeByRank(ctx, revIndexKey, 0, excess-1)
			for _, v := range victims {
				_ = s.redis.Del(ctx, revKey(v))
			}
			count = s.max
		}
	}

	// Pressure alert when cardinality > 80% of cap.
	if cardErr == nil && s.alertFn != nil {
		threshold := int64(float64(s.max) * 0.8)
		if count > threshold {
			s.alertFn(ctx, "jti_revocation_set_pressure", "warn")
		}
	}

	return nil
}

// IsRevoked reports whether the given JTI has been explicitly revoked.
// Uses a single Redis EXISTS call; suitable for the per-request hot path.
func (s *RevocationStore) IsRevoked(ctx context.Context, jti string) (bool, error) {
	revoked, err := s.redis.Exists(ctx, revKey(jti))
	if err != nil {
		return false, fmt.Errorf("revocation.IsRevoked: %w", err)
	}
	return revoked, nil
}

// CheckPressure returns the current deny-set cardinality and fires the pressure
// alert when cardinality > 80% of max. Safe to call from health endpoints.
func (s *RevocationStore) CheckPressure(ctx context.Context) (int64, error) {
	count, err := s.redis.ZCard(ctx, revIndexKey)
	if err != nil {
		return 0, fmt.Errorf("revocation.CheckPressure: %w", err)
	}
	threshold := int64(float64(s.max) * 0.8)
	if count > threshold && s.alertFn != nil {
		s.alertFn(ctx, "jti_revocation_set_pressure", "warn")
	}
	return count, nil
}
