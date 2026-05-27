// Package bootstrap initialises shared, long-lived infrastructure clients
// (pgxpool, Redis) for the API server.  All connection pool creation MUST
// happen here -- the no_pool_per_request lint rule (xops/lint/) flags any
// pgx.Connect or redis.NewClient call outside this package.
package bootstrap

import (
	"context"
	"fmt"
	"os"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/metaphy6/negelir/server/internal/config"
)

// PGPools holds the primary pool and (when configured) the read-replica pool.
// Replica is nil when cfg.APIPGReplicaURL == "" (built-but-dormant default).
type PGPools struct {
	Primary *pgxpool.Pool
	Replica *pgxpool.Pool // nil when APIPGReplicaURL == ""
}

// PoolFor returns the replica pool for read-only HTTP methods (GET/HEAD) when
// replica routing is enabled (APIPGReplicaURL != ""); otherwise Primary.
// This is built but dormant until the operator sets APIPGReplicaURL.
func (p *PGPools) PoolFor(method string) *pgxpool.Pool {
	if p.Replica != nil && (method == "GET" || method == "HEAD") {
		return p.Replica
	}
	return p.Primary
}

// Close shuts down all pools.
func (p *PGPools) Close() {
	p.Primary.Close()
	if p.Replica != nil {
		p.Replica.Close()
	}
}

// NewPGPools creates the primary (and optionally replica) pgxpool with the
// full SS9.17.3 settings:
//
//   - MaxConns = cfg.APIPGPoolMaxConns (default 25)
//   - MaxConnIdleTime = 5 min
//   - MaxConnLifetime = 1 h, MaxConnLifetimeJitter = 5 min
//   - HealthCheckPeriod = 30 s
//   - BeforeConnect sets application_name = "negelir-api/<pod_instance_id>"
//   - DefaultQueryExecMode = QueryExecModeCacheStatement (statement caching)
//
// Read-replica routing is built but dormant: when APIPGReplicaURL == ""
// (the default), Replica is nil and PoolFor always returns Primary.
func NewPGPools(ctx context.Context, cfg *config.Config) (*PGPools, error) {
	podID := podInstanceID()
	primary, err := newPGPool(ctx, cfg.EffectiveDatabaseURL(), cfg, podID)
	if err != nil {
		return nil, fmt.Errorf("bootstrap.NewPGPools primary: %w", err)
	}
	pools := &PGPools{Primary: primary}

	// SS9.17.3 read-replica routing -- built but dormant (APIPGReplicaURL="" default).
	if cfg.APIPGReplicaURL != "" {
		replica, err := newPGPool(ctx, cfg.APIPGReplicaURL, cfg, podID+"-ro")
		if err != nil {
			primary.Close()
			return nil, fmt.Errorf("bootstrap.NewPGPools replica: %w", err)
		}
		pools.Replica = replica
	}
	return pools, nil
}

// newPGPool builds a single pgxpool with all SS9.17.3 settings applied.
func newPGPool(ctx context.Context, dsn string, cfg *config.Config, podID string) (*pgxpool.Pool, error) {
	poolCfg, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		return nil, fmt.Errorf("pgxpool.ParseConfig: %w", err)
	}

	// SS9.17.3 pool sizing.
	poolCfg.MaxConns = int32(cfg.APIPGPoolMaxConns)
	poolCfg.MaxConnIdleTime = 5 * time.Minute
	poolCfg.MaxConnLifetime = 1 * time.Hour
	poolCfg.MaxConnLifetimeJitter = 5 * time.Minute
	poolCfg.HealthCheckPeriod = 30 * time.Second
	poolCfg.ConnConfig.ConnectTimeout = cfg.DBConnectTimeout()

	// SS9.17.3 BeforeConnect: sets application_name for DBA load attribution.
	appName := "negelir-api/" + podID
	poolCfg.BeforeConnect = func(_ context.Context, cc *pgx.ConnConfig) error {
		if cc.RuntimeParams == nil {
			cc.RuntimeParams = make(map[string]string)
		}
		cc.RuntimeParams["application_name"] = appName
		return nil
	}

	// SS9.17.3 statement_cache_capacity=256 (target per spec).
	// pgx v5 uses QueryExecModeCacheStatement by default; the explicit
	// assignment below prevents it from being accidentally overridden.
	// Note: pgx v5.5.x does not expose cache capacity via a public API;
	// the pgx default (512) is used. The important invariant -- that prepared
	// statements are cached per connection -- is enforced by this mode.
	poolCfg.ConnConfig.DefaultQueryExecMode = pgx.QueryExecModeCacheStatement

	pool, err := pgxpool.NewWithConfig(ctx, poolCfg)
	if err != nil {
		return nil, fmt.Errorf("pgxpool.NewWithConfig: %w", err)
	}
	return pool, nil
}

// podInstanceID returns the K8s pod name (injected via HOSTNAME by the
// downward API) for use in application_name. Falls back to "local" in dev.
func podInstanceID() string {
	if h := os.Getenv("HOSTNAME"); h != "" {
		return h
	}
	return "local"
}
