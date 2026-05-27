package middleware

import (
	"context"
	"fmt"
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/redis/go-redis/v9"
)

// CacheGenStore is the minimal Redis GET surface needed for generation-aware
// cache reads. *redis.Client satisfies it via RedisCacheGen.
//
// Conventions:
//   - Get returns ("", redis.Nil) on a cache miss.
//   - Get returns ("", err) on a Redis communication fault.
type CacheGenStore interface {
	Get(ctx context.Context, key string) (string, error)
}

// RedisCacheGen adapts a *redis.Client to CacheGenStore.
type RedisCacheGen struct{ C *redis.Client }

// Get delegates to the underlying Redis client.
func (r *RedisCacheGen) Get(ctx context.Context, key string) (string, error) {
	return r.C.Get(ctx, key).Result()
}

// CacheGenKeyFor returns the Redis key holding the generation counter for k.
// This key is written by the Phase 4 CacheInvalidationReactor.
//
// Pattern: cache:<k>:gen
func CacheGenKeyFor(k string) string {
	return fmt.Sprintf("cache:%s:gen", k)
}

// CacheEntryKeyFor returns the Redis key for a cached response body at gen.
//
// Pattern: cache.v1:<k>:<gen>
func CacheEntryKeyFor(k, gen string) string {
	return fmt.Sprintf("cache.v1:%s:%s", k, gen)
}

// requestCacheKey derives the cache lookup key from a gin.Context.
// Uses the full URL path (query string excluded).
func requestCacheKey(c *gin.Context) string {
	return c.Request.URL.Path
}

// CacheGenCheck returns a Gin middleware that implements generation-aware cache
// reads compatible with the Phase 4 CacheInvalidationReactor.
//
// For GET requests:
//  1. Derive cache key k from the request path.
//  2. Read the current generation from cache:<k>:gen (set by Phase 4).
//  3. Read the cached entry from cache.v1:<k>:<gen>.
//  4. Cache HIT  -> write X-Cache: hit, serve body, abort handler chain.
//  5. Stale gen (entry absent for current gen) or no gen ->
//     write X-Cache: bypass, fall through to the handler.
//
// Non-GET requests always fall through without touching the cache.
//
// Fail-open: any Redis error sets X-Cache: bypass and continues.
func CacheGenCheck(store CacheGenStore) gin.HandlerFunc {
	return func(c *gin.Context) {
		if c.Request.Method != http.MethodGet {
			c.Next()
			return
		}

		k := requestCacheKey(c)
		ctx := c.Request.Context()

		// Read current generation counter.
		gen, err := store.Get(ctx, CacheGenKeyFor(k))
		if err != nil || gen == "" {
			// No gen key (never invalidated) or Redis fault -> bypass.
			c.Header("X-Cache", "bypass")
			c.Next()
			return
		}

		// Read cached entry for current generation.
		entry, err := store.Get(ctx, CacheEntryKeyFor(k, gen))
		if err != nil || entry == "" {
			// Stale gen (entry missing) or Redis fault -> bypass.
			c.Header("X-Cache", "bypass")
			c.Next()
			return
		}

		// Cache hit: serve from cache.
		c.Header("X-Cache", "hit")
		c.String(http.StatusOK, "%s", entry)
		c.Abort()
	}
}
