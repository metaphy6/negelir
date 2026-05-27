package bootstrap

import (
	"context"
	"fmt"
	"time"

	"github.com/redis/go-redis/v9"

	"github.com/metaphy6/negelir/server/internal/config"
)

// RedisClients holds the two distinct Redis client instances required by SS9.17.3.
//   - CacheClient: high-throughput cache reads/writes; PoolTimeout=100ms (fail fast -> MISS).
//   - BusClient:   Redis Streams XREAD BLOCK; ReadTimeout = request_timeout + 500ms.
//
// MaxRetries=0 on both: retries belong in the resilience layer (SS9.17.4), not silently
// in the driver.
type RedisClients struct {
	CacheClient *redis.Client
	BusClient   *redis.Client
}

// Close shuts down both clients gracefully.
func (r *RedisClients) Close() error {
	var firstErr error
	if err := r.CacheClient.Close(); err != nil {
		firstErr = fmt.Errorf("cacheClient.Close: %w", err)
	}
	if err := r.BusClient.Close(); err != nil {
		if firstErr != nil {
			return fmt.Errorf("%w; busClient.Close: %v", firstErr, err)
		}
		return fmt.Errorf("busClient.Close: %w", err)
	}
	return firstErr
}

// Ping verifies both clients can reach Redis. Returns the first error.
func (r *RedisClients) Ping(ctx context.Context) error {
	if err := r.CacheClient.Ping(ctx).Err(); err != nil {
		return fmt.Errorf("cacheClient.Ping: %w", err)
	}
	if err := r.BusClient.Ping(ctx).Err(); err != nil {
		return fmt.Errorf("busClient.Ping: %w", err)
	}
	return nil
}

// NewRedisClients creates cacheClient and busClient per SS9.17.3.
// Both clients are initialised at process start and shared for the
// lifetime of the server -- never create a new client per request.
func NewRedisClients(cfg *config.Config) *RedisClients {
	addr := cfg.EffectiveRedisURL()

	// cacheClient: PoolSize=cfg.APIRedisCachePoolSize (default 50), MinIdleConns=10,
	// PoolTimeout=100ms (fail fast -- fall through to MISS rather than queue).
	// MaxRetries=0: retries owned by the resilience layer (SS9.17.4).
	cacheClient := redis.NewClient(&redis.Options{
		Addr:         addr,
		PoolSize:     cfg.APIRedisCachePoolSize,
		MinIdleConns: 10,
		PoolTimeout:  100 * time.Millisecond,
		MaxRetries:   0,
	})

	// busClient: for XREAD reply streams. PoolSize=cfg.APIRedisBusPoolSize (default 20).
	// ReadTimeout = api_request_timeout_ms + 500ms (covers XREAD BLOCK budget).
	// MaxRetries=0: retries owned by the resilience layer (SS9.17.4).
	busReadTimeout := time.Duration(cfg.APIRequestTimeoutMs+500) * time.Millisecond
	busClient := redis.NewClient(&redis.Options{
		Addr:        addr,
		PoolSize:    cfg.APIRedisBusPoolSize,
		ReadTimeout: busReadTimeout,
		MaxRetries:  0,
	})

	return &RedisClients{
		CacheClient: cacheClient,
		BusClient:   busClient,
	}
}
