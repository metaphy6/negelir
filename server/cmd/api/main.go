//go:build !wasm

/*
Negelir Go Middleware Server
Fetches data from external sources, stores to PostgreSQL, caches in Redis.
Serves REST API for the AI module.
*/
package main

import (
	"context"
	"crypto/rand"
	"encoding/json"
	"fmt"
	"log"
	"mime"
	"net/http"
	_ "net/http/pprof" // §9.17.10: registers /debug/pprof/* handlers on http.DefaultServeMux (unused here — we register on metricsMux selectively)
	"os"
	"os/signal"
	"runtime"
	"runtime/debug"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/redis/go-redis/v9"
	_ "go.uber.org/automaxprocs" // Phase 9 §9.17.1: sets GOMAXPROCS from cgroup CPU quota at init time.
	"golang.org/x/net/http2/h2c"

	"github.com/metaphy6/negelir/server/internal/api"
	"github.com/metaphy6/negelir/server/internal/auth"
	"github.com/metaphy6/negelir/server/internal/bootstrap"
	"github.com/metaphy6/negelir/server/internal/calibration"
	"github.com/metaphy6/negelir/server/internal/config"
	aperrors "github.com/metaphy6/negelir/server/internal/errors"
	"github.com/metaphy6/negelir/server/internal/handlers"
	"github.com/metaphy6/negelir/server/internal/metrics"
	"github.com/metaphy6/negelir/server/internal/middleware"
	"github.com/metaphy6/negelir/server/internal/mtls"
	"github.com/metaphy6/negelir/server/internal/profiling"
	runtimetuning "github.com/metaphy6/negelir/server/internal/runtime"
	"github.com/metaphy6/negelir/server/internal/sec"
	apitcp "github.com/metaphy6/negelir/server/internal/tcp"
	"github.com/metaphy6/negelir/server/internal/telemetry"
)

func main() {
	fmt.Println("\xf0\x9f\x9a\x80 Negelir Middleware Server starting...")
	cfg, err := config.Load()
	if err != nil {
		log.Fatalf("\xe2\x9d\x8c Config error: %v", err)
	}

	// Phase 9 §9.17.1 — Go runtime tuning (refuse-to-start gates).
	// automaxprocs already fired at package init (see import side-effect above).
	// Log the effective GOMAXPROCS so operators can verify cgroup-based tuning.
	log.Printf("runtime.gomaxprocs=%d source=cgroup|env|default", runtime.GOMAXPROCS(0))

	// §9.17.1 — GOMEMLIMIT: derive from cgroup when cfg.APIGoMemLimitMiB == 0.
	{
		var memLimitBytes int64
		if cfg.APIGoMemLimitMiB > 0 {
			memLimitBytes = int64(cfg.APIGoMemLimitMiB) << 20
		} else {
			var probeErr error
			memLimitBytes, probeErr = runtimetuning.DefaultGoMemLimitBytes()
			if probeErr != nil {
				// Refuse boot: unbounded heap is forbidden.
				log.Fatalf("\xe2\x9d\x8c §9.17.1 GOMEMLIMIT: cgroup unreadable AND api_go_mem_limit_mib=0 (unbounded heap forbidden): %v", probeErr)
			}
		}
		debug.SetMemoryLimit(memLimitBytes)
		log.Printf("runtime.gomemlimit=%d bytes (%.1f MiB)", memLimitBytes, float64(memLimitBytes)/(1<<20))
	}

	// §9.17.1 — GOGC: use configured value (default 50; Go default 100 is too lazy
	// for our JSON encode + Redis pipeline allocation pattern).
	debug.SetGCPercent(cfg.APIGoGCPercent)
	log.Printf("runtime.gogc=%d", cfg.APIGoGCPercent)

	// §9.17.1 — heap baseline boot probe. Asserts < 32 MiB before any request.
	{
		runtime.GC()
		var ms runtime.MemStats
		runtime.ReadMemStats(&ms)
		heapMiB := ms.HeapInuse >> 20
		if heapMiB > 32 {
			log.Fatalf("\xe2\x9d\x8c §9.17.1 heap baseline %d MiB exceeds 32 MiB limit (check for large init-time allocations)", heapMiB)
		}
		log.Printf("runtime.heap_baseline=%d MiB (OK, limit=32 MiB)", heapMiB)
	}

	// Phase 9 §9.4 — OpenAPI extensions boot gate. Refuses to start if any
	// operation in the embedded spec is missing a required Phase 9 extension
	// (x-rate-cost, x-tier-required, x-idempotent-mutation). This catches
	// spec drift before any request is served.
	if err := api.BootValidateSpec(); err != nil {
		log.Fatalf("❌ OpenAPI spec validation: %v", err)
	}

	// Phase 13.1 — Load league catalog at boot.
	// Computes catalog_sha256 for etag headers and caches in memory.
	if err := initCatalog(); err != nil {
		log.Fatalf("❌ Catalog init: %v", err)
	}

	// Phase 9 §9.2 — bcrypt startup probe. Refuses boot if cost=cfg.APIBcryptCost
	// produces a hash in under auth.MinBcryptDuration (100 ms), which would
	// indicate the deployment target is too fast for the configured cost.
	if _, probeErr := auth.ProbeBcryptCost(cfg.APIBcryptCost); probeErr != nil {
		log.Fatalf("\xe2\x9d\x8c bcrypt probe failed: %v", probeErr)
	}

	// Phase 9 §9.17.8 — HTTP/2 boot assert.
	// Refuses to start when GODEBUG=http2server=0 would silently disable
	// HTTP/2 on TLS listeners, violating the §9.17.8 contract.
	if err := mtls.AssertHTTP2NotDisabled(); err != nil {
		log.Fatalf("\xe2\x9d\x8c %v", err)
	}
	log.Printf("runtime.http2=enabled (GODEBUG check passed)")

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Phase 9 §9.8 — OTLP trace export.  When cfg.TelemetryOTLPEndpoint is
	// empty, Init is a deliberate no-op (no goroutines, no connections).
	// When set, spans are exported to the configured OTLP gRPC collector.
	// NEGELIR_SERVICE_VERSION is an optional env var for the service.version
	// resource attribute; defaults to "unknown" when unset.
	svcVersion := os.Getenv("NEGELIR_SERVICE_VERSION")
	if svcVersion == "" {
		svcVersion = "unknown"
	}
	traceShutdown, traceErr := telemetry.Init(ctx, cfg.TelemetryOTLPEndpoint, svcVersion)
	if traceErr != nil {
		log.Fatalf("\xe2\x9d\x8c Telemetry init: %v", traceErr)
	}
	defer func() {
		shutCtx, shutCancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer shutCancel()
		if err := traceShutdown(shutCtx); err != nil {
			log.Printf("\xe2\x9a\xa0\xef\xb8\x8f  Trace provider shutdown: %v", err)
		}
	}()

	// Database — §9.17.3: pgxpool with full pool settings via bootstrap.
	pgPools, err := bootstrap.NewPGPools(ctx, cfg)
	if err != nil {
		log.Fatalf("\xe2\x9d\x8c PostgreSQL pool error: %v", err)
	}
	defer pgPools.Close()
	pool := pgPools.Primary // convenience alias; handlers receive *pgxpool.Pool directly.

	pingCtx, pingCancel := context.WithTimeout(ctx, cfg.DBPingTimeout())
	if err := pool.Ping(pingCtx); err != nil {
		pingCancel()
		log.Printf("\xe2\x9a\xa0\xef\xb8\x8f  PostgreSQL not ready yet, retrying...")
		time.Sleep(cfg.DBRetryDelay())
		pingCtx2, pingCancel2 := context.WithTimeout(ctx, cfg.DBPingTimeout())
		if err := pool.Ping(pingCtx2); err != nil {
			pingCancel2()
			log.Fatalf("\xe2\x9d\x8c Could not connect to PostgreSQL: %v", err)
		}
		pingCancel2()
	} else {
		pingCancel()
	}
	fmt.Println("\xe2\x9c\x85 PostgreSQL connection successful")

	// Redis — §9.17.3: two distinct clients (cacheClient, busClient) via bootstrap.
	redisClients := bootstrap.NewRedisClients(cfg)
	defer func() {
		if err := redisClients.Close(); err != nil {
			log.Printf("\xe2\x9a\xa0\xef\xb8\x8f  Redis close error: %v", err)
		}
	}()
	// rdb is the cacheClient alias used by existing handlers.
	// busClient is initialised and ready for §9.17.7 (XREAD audit pipelines).
	rdb := redisClients.CacheClient
	if err := redisClients.Ping(ctx); err != nil {
		log.Printf("\xe2\x9a\xa0\xef\xb8\x8f  Redis not ready yet, retrying...")
		time.Sleep(cfg.RedisRetryDelay())
		if err := redisClients.Ping(ctx); err != nil {
			log.Fatalf("\xe2\x9d\x8c Could not connect to Redis: %v", err)
		}
	}
	fmt.Println("\xe2\x9c\x85 Redis connection successful")

	// Phase 9 §9.13 — register api.gateway.v1 shim heartbeat so `swarmctl ps`
	// shows this process in its output. The static manifest in swarmctl reads
	// this Redis string key (SET, RFC3339) for the LAST_HEARTBEAT column.
	// TTL=0 (no expiry): the timestamp stays until overwritten on restart; it
	// becomes stale-marked after SwarmHeartbeatSec*3 seconds without refresh.
	if herr := rdb.Set(ctx, "agent:api.gateway.v1:heartbeat",
		time.Now().UTC().Format(time.RFC3339), 0).Err(); herr != nil {
		log.Printf("\xe2\x9a\xa0\xef\xb8\x8f  agent heartbeat write: %v", herr)
	}

	// Phase 9.6: boot-time Lua deploy-skew gate — refuses to start on SHA
	// drift or EVALSHA mismatch between the embedded body and Redis.
	bootLuaGates(ctx, rdb)

	// Phase 9.6: boot-time XFF trusted-proxy parse — refuses to start on
	// malformed CIDR in cfg.SecRateTrustedProxies.
	trustedProxies, err := sec.ParseTrustedProxies(cfg.SecRateTrustedProxies)
	if err != nil {
		log.Fatalf("\xe2\x9d\x8c Trusted-proxies parse: %v", err)
	}

	// Phase 9 §9.7 — burst budget: load endpoint cost map once at boot so
	// both the rate limiter and the totality gate share the same compiled map.
	endpointCosts, err := sec.LoadEndpointCosts(sec.EmbeddedEndpointCostsYAML)
	if err != nil {
		log.Fatalf("❌ Endpoint-cost load: %v", err)
	}
	// Construct the in-process GCRA secondary bucket using the Phase 9 §9.7
	// burst-budget config knobs (cfg.APIBurstCapacity / APIBurstRefillPerS).
	// MaxKeys=50000 accommodates a large number of distinct IP subjects before
	// LRU eviction is triggered.
	secondaryBucket := sec.NewSecondaryBucket(cfg.APIBurstCapacity, cfg.APIBurstRefillPerS, 50000)

	// Phase 7 §7.1: QA input gate (sec.QAInputGate for /v1/qa body).
	rules, err := sec.LoadInjectionPatterns(sec.EmbeddedInjectionPatternsYAML)
	if err != nil {
		log.Fatalf("\xe2\x9d\x8c Injection-pattern load: %v", err)
	}
	qaGate := sec.NewQAInputGate(rules, cfg.SecInputMaxLen)

	// Phase 16 forward contract: CalibrationStore Protocol seam.
	// Phase 9 uses the in-memory backend; Phase 16 swaps in the feed-plane
	// backend by replacing this constructor arg — 0 handler lines change.
	calibStore := calibration.NewInMemoryCalibrationStore()

	// Router
	if os.Getenv("GIN_MODE") == "" {
		gin.SetMode(gin.ReleaseMode)
	}
	r := gin.New()
	// Phase 9 §9.17.4 — custom panic recovery: catches panics, emits
	// sec.alert.v1{kind=api_panic, severity=critical} with SHA-256 of stack trace,
	// writes HTTP 500, and keeps the process alive. alertFn=nil is safe — the
	// middleware still recovers and returns 500; alert publishing will be wired
	// once the sec.alert.v1 bus publisher is injected (Phase 9 §9.17 follow-up).
	r.Use(middleware.PanicRecovery(nil))
	// Phase 9.5: W3C trace propagation — MUST be first so every downstream
	// handler and bus publisher sees a populated ContextKeyTraceID. Mints a
	// fresh traceparent if absent; reuses incoming trace_id if present.
	// X-Request-ID response header is the client-side alias (32-hex trace_id).
	r.Use(middleware.TraceParent())
	// Phase 9 §9.8 — OTLP span middleware. Wraps each request in an OTEL
	// server span seeded from the trace_id minted by TraceParent above.
	// When TelemetryOTLPEndpoint is empty, the global TracerProvider is no-op
	// and this middleware costs nothing.
	r.Use(middleware.OTelSpan())
	r.Use(requestLogger())
	// Phase 9.6: XFF derivation — derives real client IP per request and
	// stores sec.rate_subject in Gin context for the rate limiter.
	r.Use(middleware.XFF(trustedProxies, cfg.SecRateIPv4Prefix, cfg.SecRateIPv6Prefix))
	// Phase 9 §9.1 — global body-size cap (bcrypt-bomb / RAM-exhaustion defense).
	// Applied before every handler dispatch; route-specific sub-caps below
	// override for /v1/qa and /v1/auth/login.
	r.Use(middleware.BodySizeCap(int64(cfg.APIRequestMaxBytes)))
	// Phase 9 §9.9 — concurrency semaphore.
	// ConcurrencyLimit enforces cfg.APIMaxConcurrentRequests in-flight requests
	// per pod via a buffered-channel semaphore. Overflow → 503 immediately.
	// Applied after body-size cap so malformed-size requests are shed first.
	r.Use(middleware.ConcurrencyLimit(cfg.APIMaxConcurrentRequests))

	// Routes
	api := r.Group("/api/v1")
	{
		api.GET("/health", healthHandler(pool, rdb))
		api.GET("/matches", matchesHandler(pool, rdb, cfg.MatchesCacheTTL()))
		api.GET("/matches/:id", matchDetailHandler(pool, rdb))
		api.GET("/teams", teamsHandler(pool, rdb, cfg.TeamsCacheTTL()))
		api.GET("/teams/:id", teamDetailHandler(pool))
		api.POST("/scrape/trigger", scrapeTriggerHandler(pool))
		api.GET("/features/:match_id", featuresHandler(pool, rdb))
	}

	// /v1 group — Phase 9/10 routes (QA, identity, etc.)
	// CONTRACT (/v1 public contract -- Phase 9 §9.11):
	//   /v1 is the stable public API. Breaking changes (field removal, semantic
	//   changes, parameter renames) MUST cut a /v2 group -- never break /v1 in
	//   place. Additive changes (new optional fields, new endpoints) are allowed
	//   in /v1 without a version bump. Deprecated /v1 routes must carry
	//   x-deprecated-on + x-sunset-on in openapi.yaml and are automatically
	//   served with Sunset / Link headers (or 410 past sunset) by the
	//   DeprecationHeaders middleware wired below.
	v1 := r.Group("/v1")
	// Phase 9 §9.7 — burst budget rate limiter applied to all /v1 routes.
	// Primary checker is Noop for now (Redis GCRA wired in a later bullet);
	// the in-process SecondaryBucket is the active guard here.
	v1.Use(middleware.RateLimiterSimple(
		secondaryBucket,
		middleware.NoopRateChecker(),
		endpointCosts,
		cfg.APIBurstCapacity,
		cfg.APIBurstRefillPerS,
		cfg.SecRateRedisTimeoutMs,
	))
	{
		// Phase 9 §9.1 — K8s probes.
		// healthz = liveness; never depends on PG/Redis/bus (process-up only).
		// readyz  = readiness; checks PG + Redis.
		// Phase 14 (K8s) forward contract: readyz tolerates consensus.v1 not
		// being co-located on this pod. consensus.v1 runs at replicas:1 (§5.3
		// single-publication guarantee) and is NOT a co-location requirement
		// for the API pod. This probe checks only the API's own dependencies.
		v1.GET("/healthz", livezHandler())
		v1.GET("/readyz", readyzHandler(pool, rdb))
		// Phase 9 §9.1 — /v1/qa sub-cap (cfg.QAInputMaxBytes; tightens the global cap).
		// Phase 9 §9.9 — BackpressureCheck reads api:backpressure:on (set by §8.x scaler);
		// returns 425 for POST when the predict.request.v1 stream is overloaded.
		v1.POST("/qa",
			middleware.BodySizeCap(int64(cfg.QAInputMaxBytes)),
			middleware.BackpressureCheck(&middleware.RedisBackpressure{C: rdb}),
			qaHandler(qaGate, cfg),
		)
		// Phase 9.6: password-field bypass — password routed through
		// sec.PasswordPasses (length-cap only; no NFC; no patterns).
		// Full auth logic (bcrypt, JWT) wired in Phase 9.2.
		// Phase 9 §9.1 — /v1/auth/login sub-cap (cfg.AuthLoginMaxBytes; blocks bcrypt-bomb).
		v1.POST("/auth/login", middleware.BodySizeCap(int64(cfg.AuthLoginMaxBytes)), authLoginHandler(qaGate))
		v1.POST("/auth/register", authRegisterHandler(qaGate, cfg.APISelfRegistrationEnabled, cfg.APIRegisterCapPerSubnetPerH, rdb))
		
		// Phase 13.1 — League catalog endpoint (admin-token-gated).
		// Returns the canonical catalog + ETag=catalog_sha256; clients cache against etag.
		v1.GET("/catalog", catalogHandler())
		
		// Phase 9 §9.1 Predictions — CalibrationStore Protocol seam (Phase 16
		// forward contract): handler reads only through the interface; backend
		// is swapped in cmd/api/main.go, never in the handler.
		// Phase 9 §9.3 SWR cache: PredictionSWR wires the stale-while-revalidate
		// cache reads; InflightMax caps pod-level concurrent SWR goroutines.
		predSWR := &middleware.PredictionSWR{
			Store:       &middleware.RedisPredictionSWR{C: rdb},
			StaleAfterS: cfg.APICacheStaleAfterS,
			MaxAgeS:     cfg.APICacheMaxAgeS,
			InflightMax: cfg.APISWRInflightMax,
		}
		v1.GET("/matches/:id/predictions", handlers.PredictionsHandler(calibStore, predSWR))

		// §9.14 stub routes — openapi.yaml declares these; full implementation
		// is deferred to the phases noted inline. Stubs return 501 until wired.
		v1.GET("/matches/:id", func(c *gin.Context) {
			aperrors.Respond(c, aperrors.CodeServiceUnavailable, "not implemented yet")
		})
		v1.GET("/leagues", func(c *gin.Context) {
			aperrors.Respond(c, aperrors.CodeServiceUnavailable, "not implemented yet")
		})
		v1.GET("/leagues/:id/fixtures", func(c *gin.Context) {
			aperrors.Respond(c, aperrors.CodeServiceUnavailable, "not implemented yet")
		})
		v1.GET("/me", func(c *gin.Context) {
			aperrors.Respond(c, aperrors.CodeServiceUnavailable, "not implemented yet")
		})
		v1.POST("/auth/refresh", func(c *gin.Context) {
			aperrors.Respond(c, aperrors.CodeServiceUnavailable, "not implemented yet")
		})
	}

	// Phase 9.6: boot-time endpoint-cost totality gate — refuses to start
	// if any registered route lacks an explicit cost entry in
	// endpoint_costs.yaml (sec.CheckTotality, allowFallback=nil).
	bootCostTotalityGate(r, endpointCosts)

	// Phase 9 §9.8 — RED metrics boot gate and server startup.
	// 1. Create an isolated Prometheus registry (no Go runtime metrics so the
	//    operator controls exactly what is exposed on :9091).
	// 2. Run the cardinality estimate against cfg.TelemetryMaxSeries — refuses
	//    to start if worst-case series count would be exceeded.
	// 3. Wire the Observe middleware onto the router.
	// 4. Expose /metrics on the dedicated internal port (cfg.TelemetryMetricsPort).
	metricsReg := prometheus.NewRegistry()
	apiMetrics := metrics.New(metricsReg)
	routeCount := len(r.Routes())
	if err := metrics.ValidateCardinality(routeCount, cfg.TelemetryMaxSeries); err != nil {
		log.Fatalf("\xe2\x9d\x8c Metrics cardinality gate: %v", err)
	}
	// Add the Observe middleware globally. It runs after routing so
	// c.FullPath() always returns the matched OpenAPI pattern.
	r.Use(metrics.Observe(apiMetrics))

	metricsMux := http.NewServeMux()
	metricsMux.Handle("/metrics", promhttp.HandlerFor(metricsReg, promhttp.HandlerOpts{}))

	// §9.17.10 — pprof on the metrics port (:9091/debug/pprof/*).
	// Enabled when cfg.APIPprofEnabledDev OR cfg.APIPprofEnabledProd is true,
	// OR when the Redis key api:pprof:<hostname> exists (short-lived TTL 1h, set
	// by `make api.pprof-enable POD=...`). NEVER registered on the public listener.
	{
		hostname, _ := os.Hostname()
		pprofRedisKey := "api:pprof:" + hostname
		pprofEnabled := cfg.APIPprofEnabledDev || cfg.APIPprofEnabledProd
		if !pprofEnabled {
			// Check the short-lived Redis operator-enable key.
			if val := rdb.Exists(ctx, pprofRedisKey).Val(); val > 0 {
				pprofEnabled = true
			}
		}
		if pprofEnabled {
			// net/http/pprof registers its handlers on http.DefaultServeMux at
			// import time. Copy them onto our isolated metricsMux so the public
			// listener is never affected.
			for _, path := range []string{
				"/debug/pprof/",
				"/debug/pprof/cmdline",
				"/debug/pprof/profile",
				"/debug/pprof/symbol",
				"/debug/pprof/trace",
			} {
				metricsMux.Handle(path, http.DefaultServeMux)
			}
			log.Printf("pprof.enabled=true port=%s (metrics-port only; redis_key=%s)",
				cfg.TelemetryMetricsPort, pprofRedisKey)
		} else {
			log.Printf("pprof.enabled=false (set NEGELIR_API_PPROF_ENABLED_DEV=true or run make api.pprof-enable POD=%s)", hostname)
		}
	}

	// §9.17.10 — continuous CPU profiling sampler (10 s profile every 10 min).
	profiling.StartSampler(ctx, cfg.APIPprofDir)
	log.Printf("profiling.sampler=started dir=%s", cfg.APIPprofDir)

	metricsSrv := &http.Server{
		Addr:         ":" + cfg.TelemetryMetricsPort,
		Handler:      metricsMux,
		ReadTimeout:  5 * time.Second,
		WriteTimeout: 10 * time.Second,
	}
	go func() {
		fmt.Printf("\xf0\x9f\x93\x8a Metrics listening on :%s/metrics (internal only)\n", cfg.TelemetryMetricsPort)
		if err := metricsSrv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Printf("\xe2\x9a\xa0\xef\xb8\x8f  Metrics server error: %v", err)
		}
	}()

	srv := &http.Server{
		Addr: ":" + cfg.Port,
		// Pre-Phase-6 audit round-3 G2: cap per-request handler
		// compute time independently of the connection-level
		// Read/Write timeouts. Phase 6 fan-out (proofreader / drift)
		// can produce slow concurrent queries; without this cap a
		// runaway handler holds a `pgx` connection until the
		// client TCP timeout fires.
		// §9.17.10 — wrap with allocation-tracking middleware (sampled at
		// cfg.APIAllocSampleRate; negligible overhead at the default 0.001).
		Handler: metrics.ObserveAlloc(
			apiMetrics,
			cfg.APIAllocSampleRate,
			nil, // alertFn: nil until sec.alert.v1 bus publisher is injected
		)(http.TimeoutHandler(r, cfg.HTTPHandlerTimeout(), `{"error":"handler timeout"}`)),
		// Phase 9 §9.17.1 — timeout knobs (Slowloris / idle-fd defense).
		// These supersede the legacy HTTP_READ/WRITE_TIMEOUT_SEC values for
		// the public listener; both sets of knobs are kept for backward compat
		// but the §9.17.1 ms-granularity knobs take precedence here.
		ReadHeaderTimeout: cfg.ReadHeaderTimeout(),
		ReadTimeout:       cfg.ReadTimeout(),
		WriteTimeout:      cfg.WriteTimeout(),
		IdleTimeout:       cfg.IdleTimeout(),
		// MaxHeaderBytes = 32 KiB (§9.9 / §9.17.1 — caps header memory exhaustion).
		MaxHeaderBytes: 32 << 10,
	}

	// Phase 9 §9.17.1 — H2C in-mesh listener.
	// H2C (HTTP/2 cleartext) is ONLY exposed on the in-cluster sidecar port
	// (cfg.APIInMeshPort, default 8082), never on the public API port.
	// This port sits behind mTLS in-cluster and is intended for gRPC-over-HTTP/2
	// future-compat (no plain cleartext to the internet).
	if cfg.APIInMeshPort != "" && cfg.APIInMeshPort != "0" {
		inMeshSrv := &http.Server{
			Addr:              ":" + cfg.APIInMeshPort,
			Handler:           h2c.NewHandler(r, nil),
			ReadHeaderTimeout: cfg.ReadHeaderTimeout(),
			ReadTimeout:       cfg.ReadTimeout(),
			WriteTimeout:      cfg.WriteTimeout(),
			IdleTimeout:       cfg.IdleTimeout(),
			MaxHeaderBytes:    32 << 10,
		}
		go func() {
			fmt.Printf("\xf0\x9f\x94\x97 In-mesh H2C listener on :%s (in-cluster only)\n", cfg.APIInMeshPort)
			if err := inMeshSrv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
				log.Printf("\xe2\x9a\xa0\xef\xb8\x8f  In-mesh H2C server error: %v", err)
			}
		}()
		defer func() {
			shutCtx, shutCancel := context.WithTimeout(context.Background(), cfg.ShutdownGrace())
			defer shutCancel()
			if err := inMeshSrv.Shutdown(shutCtx); err != nil {
				log.Printf("\xe2\x9a\xa0\xef\xb8\x8f  In-mesh H2C shutdown: %v", err)
			}
		}()
	}

	// Graceful shutdown
	// Phase 9 §9.17.8 — SO_REUSEPORT listener + TCP_USER_TIMEOUT.
	// NewReusePortListener enables SO_REUSEPORT on Linux so multiple acceptor
	// goroutines can share the same port (one per GOMAXPROCS).  On non-Linux
	// platforms it falls back to a plain net.Listen.
	// WrapListener applies TCP_USER_TIMEOUT to every accepted connection so
	// the kernel abandons stale connections after cfg.APITCPUserTimeoutMs ms.
	pubListener, listenErr := apitcp.NewReusePortListener("tcp", ":"+cfg.Port)
	if listenErr != nil {
		log.Fatalf("\xe2\x9d\x8c §9.17.8 SO_REUSEPORT listen :%s: %v", cfg.Port, listenErr)
	}
	pubListener = apitcp.WrapListener(pubListener, cfg.APITCPUserTimeoutMs)
	log.Printf("listener.reuseport=enabled addr=:%s tcp_user_timeout_ms=%d",
		cfg.Port, cfg.APITCPUserTimeoutMs)

	go func() {
		fmt.Printf("\xf0\x9f\x93\xa1 Server listening on :%s\n", cfg.Port)
		if err := srv.Serve(pubListener); err != nil && err != http.ErrServerClosed {
			log.Fatalf("\xe2\x9d\x8c Server error: %v", err)
		}
	}()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	fmt.Println("\n\xf0\x9f\x9b\x91 Server shutting down...")
	// §9.17.1 — use APIShutdownGraceS (default 30s) for the SIGTERM drain window.
	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), cfg.ShutdownGrace())
	defer shutdownCancel()
	if err := srv.Shutdown(shutdownCtx); err != nil {
		log.Fatalf("\xe2\x9d\x8c Server shutdown error: %v", err)
	}
	// Also shut down the metrics server gracefully.
	if err := metricsSrv.Shutdown(shutdownCtx); err != nil {
		log.Printf("\xe2\x9a\xa0\xef\xb8\x8f  Metrics server shutdown error: %v", err)
	}
	// Redis and PG pools are closed via defer (redisClients.Close / pgPools.Close).
	fmt.Println("\xe2\x9c\x85 Server shut down successfully")
}

// --- Middleware ---

func requestLogger() gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		c.Next()
		latency := time.Since(start)
		log.Printf("📝 %s %s %d %v", c.Request.Method, c.Request.URL.Path, c.Writer.Status(), latency)
	}
}

// --- Handlers ---

func healthHandler(pool *pgxpool.Pool, rdb *redis.Client) gin.HandlerFunc {
	return func(c *gin.Context) {
		ctx := c.Request.Context()
		dbOk := pool.Ping(ctx) == nil
		redisOk := rdb.Ping(ctx).Err() == nil

		status := "healthy"
		code := http.StatusOK
		if !dbOk || !redisOk {
			status = "degraded"
			code = http.StatusServiceUnavailable
		}

		c.JSON(code, gin.H{
			"status":   status,
			"database": dbOk,
			"redis":    redisOk,
			"version":  "0.1.0",
		})
	}
}

// livezHandler — GET /v1/healthz (K8s liveness probe).
// Returns 200 unconditionally: the process is alive.
// MUST NOT depend on PG, Redis, or the bus (per §9.1 route table).
func livezHandler() gin.HandlerFunc {
	return func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"alive": true})
	}
}

// readyzHandler — GET /v1/readyz (K8s readiness probe).
// Returns 200 when PG and Redis are reachable; 503 otherwise.
//
// Phase 14 (K8s) forward contract: this probe MUST NOT check whether
// consensus.v1 is co-located. consensus.v1 runs at replicas:1 (§5.3
// single-publication guarantee) and is never a co-location requirement
// for an API pod. The API pod is ready when its own dependencies
// (PG + Redis) are healthy — consensus.v1 absence is tolerated.
func readyzHandler(pool *pgxpool.Pool, rdb *redis.Client) gin.HandlerFunc {
	return func(c *gin.Context) {
		ctx := c.Request.Context()
		dbOk := pool.Ping(ctx) == nil
		redisOk := rdb.Ping(ctx).Err() == nil

		if !dbOk || !redisOk {
			c.JSON(http.StatusServiceUnavailable, gin.H{
				"ready":    false,
				"database": dbOk,
				"redis":    redisOk,
			})
			return
		}
		c.JSON(http.StatusOK, gin.H{
			"ready":    true,
			"database": true,
			"redis":    true,
		})
	}
}

func matchesHandler(pool *pgxpool.Pool, rdb *redis.Client, cacheTTL time.Duration) gin.HandlerFunc {
	return func(c *gin.Context) {
		ctx := c.Request.Context()

		// Parse and sanitize filter params. Empty values disable that
		// filter; the cache key includes the *raw* filter value so
		// distinct (league_id, season) tuples never collide.
		leagueID := strings.TrimSpace(c.Query("league_id"))
		season := strings.TrimSpace(c.Query("season"))
		limit := 50
		if raw := strings.TrimSpace(c.Query("limit")); raw != "" {
			if n, err := strconv.Atoi(raw); err == nil && n > 0 && n <= 500 {
				limit = n
			}
		}

		cacheKey := fmt.Sprintf("matches:list:%s:%s:%d", leagueID, season, limit)

		// Try cache first
		cached, err := rdb.Get(ctx, cacheKey).Result()
		if err == nil && cached != "" {
			c.Data(http.StatusOK, "application/json", []byte(cached))
			return
		}

		// Build a parameterised query so league/season are SQL-safe.
		query := `
			SELECT id, home_team, away_team, match_date, league_id, season,
				   home_score, away_score, match_week
			FROM raw_matches
			WHERE ($1 = '' OR league_id = $1)
			  AND ($2 = '' OR season = $2)
			ORDER BY match_date DESC
			LIMIT $3
		`
		rows, err := pool.Query(ctx, query, leagueID, season, limit)
		if err != nil {
			aperrors.Respond(c, aperrors.CodeInternal, "could not fetch data")
			return
		}
		defer rows.Close()

		var matches []gin.H
		for rows.Next() {
			// Pre-Phase-6 audit G1: bail if the client has gone away.
			// Without this we'd keep streaming rows from Postgres into
			// a buffer that nobody is reading, holding the pgx
			// connection until the full scan completes.
			select {
			case <-ctx.Done():
				return
			default:
			}
			var id int
			var homeTeam, awayTeam, leagueID, season string
			var matchDate time.Time
			var homeScore, awayScore *int
			var matchWeek int

			if err := rows.Scan(&id, &homeTeam, &awayTeam, &matchDate,
				&leagueID, &season, &homeScore, &awayScore, &matchWeek); err != nil {
				continue
			}
			matches = append(matches, gin.H{
				"id":         id,
				"home_team":  homeTeam,
				"away_team":  awayTeam,
				"match_date": matchDate.Format("2006-01-02"),
				"league":     leagueID,
				"season":     season,
				"home_score": homeScore,
				"away_score": awayScore,
				"match_week": matchWeek,
			})
		}

		if err := rows.Err(); err != nil {
			aperrors.Respond(c, aperrors.CodeInternal, "row iteration error")
			return
		}

		if matches == nil {
			matches = []gin.H{}
		}

		result := gin.H{
			"matches": matches,
			"count":   len(matches),
		}

		// Write to cache using configured TTL
		if data, err := json.Marshal(result); err == nil {
			rdb.Set(ctx, cacheKey, data, cacheTTL)
		}

		c.JSON(http.StatusOK, result)
	}
}

func matchDetailHandler(pool *pgxpool.Pool, rdb *redis.Client) gin.HandlerFunc {
	return func(c *gin.Context) {
		id := c.Param("id")
		ctx := c.Request.Context()

		var homeTeam, awayTeam, leagueID, season string
		var matchDate time.Time
		var homeScore, awayScore *int
		var matchWeek int
		var statsJSON *string

		err := pool.QueryRow(ctx, `
			SELECT home_team, away_team, match_date, league_id, season,
				   home_score, away_score, match_week, stats_json::text
			FROM raw_matches WHERE id = $1
		`, id).Scan(&homeTeam, &awayTeam, &matchDate, &leagueID, &season,
			&homeScore, &awayScore, &matchWeek, &statsJSON)

		if err != nil {
			aperrors.Respond(c, aperrors.CodeNotFound, "match not found")
			return
		}

		c.JSON(http.StatusOK, gin.H{
			"id":         id,
			"home_team":  homeTeam,
			"away_team":  awayTeam,
			"match_date": matchDate.Format("2006-01-02"),
			"league":     leagueID,
			"season":     season,
			"home_score": homeScore,
			"away_score": awayScore,
			"match_week": matchWeek,
		})
	}
}

func teamsHandler(pool *pgxpool.Pool, rdb *redis.Client, cacheTTL time.Duration) gin.HandlerFunc {
	return func(c *gin.Context) {
		ctx := c.Request.Context()

		cached, err := rdb.Get(ctx, "teams:list").Result()
		if err == nil && cached != "" {
			c.Data(http.StatusOK, "application/json", []byte(cached))
			return
		}

		rows, err := pool.Query(ctx, `
			SELECT uuid, display_name, league_id, internal_code
			FROM teams
			ORDER BY display_name
		`)
		if err != nil {
			aperrors.Respond(c, aperrors.CodeInternal, "could not fetch data")
			return
		}
		defer rows.Close()

		var teams []gin.H
		for rows.Next() {
			// Pre-Phase-6 audit G1.
			select {
			case <-ctx.Done():
				return
			default:
			}
			var uuid, displayName, leagueID, internalCode string
			if err := rows.Scan(&uuid, &displayName, &leagueID, &internalCode); err != nil {
				continue
			}
			teams = append(teams, gin.H{
				"id":            uuid,
				"name":          displayName,
				"internal_code": internalCode,
				"league":        leagueID,
			})
		}

		if err := rows.Err(); err != nil {
			aperrors.Respond(c, aperrors.CodeInternal, "row iteration error")
			return
		}

		if teams == nil {
			teams = []gin.H{}
		}

		result := gin.H{
			"teams": teams,
			"count": len(teams),
		}

		// Write to cache using configured TTL
		if data, err := json.Marshal(result); err == nil {
			rdb.Set(ctx, "teams:list", data, cacheTTL)
		}

		c.JSON(http.StatusOK, result)
	}
}

func teamDetailHandler(pool *pgxpool.Pool) gin.HandlerFunc {
	return func(c *gin.Context) {
		id := c.Param("id")
		ctx := c.Request.Context()

		var displayName, leagueID, internalCode string
		err := pool.QueryRow(ctx, `
			SELECT display_name, league_id, internal_code FROM teams WHERE uuid = $1
		`, id).Scan(&displayName, &leagueID, &internalCode)
		if err != nil {
			aperrors.Respond(c, aperrors.CodeNotFound, "team not found")
			return
		}

		c.JSON(http.StatusOK, gin.H{
			"id":            id,
			"name":          displayName,
			"internal_code": internalCode,
			"league":        leagueID,
		})
	}
}

func scrapeTriggerHandler(pool *pgxpool.Pool) gin.HandlerFunc {
	return func(c *gin.Context) {
		ctx := c.Request.Context()

		// Insert a scrape task
		taskID := fmt.Sprintf("manual_%d", time.Now().UnixNano())
		_, err := pool.Exec(ctx, `
			INSERT INTO scrape_tasks (task_id, source_id, data_type, match_date, status)
			VALUES ($1, 'manual_trigger', 'full_scrape', CURRENT_DATE, 'pending')
		`, taskID)

		if err != nil {
			aperrors.Respond(c, aperrors.CodeInternal, "could not create scrape task")
			return
		}

		log.Printf("🔄 Scrape task created: %s", taskID)
		c.JSON(http.StatusAccepted, gin.H{
			"task_id": taskID,
			"status":  "pending",
			"message": "Scrape task queued",
		})
	}
}

func featuresHandler(pool *pgxpool.Pool, rdb *redis.Client) gin.HandlerFunc {
	return func(c *gin.Context) {
		matchID := c.Param("match_id")
		ctx := c.Request.Context()

		rows, err := pool.Query(ctx, `
			SELECT team_uuid, season, match_week, elo_rating, form_index, xg_approximation,
				   avg_goals_scored_5, avg_goals_conceded_5, points_per_game_5
			FROM team_features
			WHERE match_id = $1
			ORDER BY team_uuid
		`, matchID)
		if err != nil {
			aperrors.Respond(c, aperrors.CodeNotFound, "feature data not found")
			return
		}
		defer rows.Close()

		var features []gin.H
		for rows.Next() {
			// Pre-Phase-6 audit G1.
			select {
			case <-ctx.Done():
				return
			default:
			}
			var teamUUID, season string
			var matchWeek int
			var elo, form, xg, scored5, conceded5, ppg5 *float64
			if err := rows.Scan(&teamUUID, &season, &matchWeek, &elo, &form, &xg,
				&scored5, &conceded5, &ppg5); err != nil {
				continue
			}
			features = append(features, gin.H{
				"team_uuid":  teamUUID,
				"season":     season,
				"match_week": matchWeek,
				"elo":        elo,
				"form":       form,
				"xg":         xg,
				"scored_5":   scored5,
				"conceded_5": conceded5,
				"ppg_5":      ppg5,
			})
		}
		if err := rows.Err(); err != nil {
			aperrors.Respond(c, aperrors.CodeInternal, "row iteration error")
			return
		}

		if features == nil {
			features = []gin.H{}
		}
		c.JSON(http.StatusOK, gin.H{"features": features, "match_id": matchID})
	}
}

// --- Helpers ---
//
// All env-binding/defaulting logic now lives in
// `server/internal/config` (Phase 1.2). Handlers and middleware-only
// helpers stay here.

// bootLuaGates runs sec.ScriptLoader.Verify for the two embedded Lua scripts
// (sec_rate_check.lua, sec_denylist_mutate.lua). It must be called after Redis
// is confirmed up; it calls log.Fatalf on header-SHA256 drift or EVALSHA
// mismatch (Phase 9.6 §7.7 deferred wiring).
func bootLuaGates(ctx context.Context, rdb *redis.Client) {
	type entry struct {
		name string
		body string
	}
	scripts := []entry{
		{"sec_rate_check.lua", sec.EmbeddedRateCheckLua},
		{"sec_denylist_mutate.lua", sec.EmbeddedDenylistMutateLua},
	}
	for _, s := range scripts {
		loader := sec.NewScriptLoader(s.name, s.body)
		body := s.body // capture by value for loadFn closure
		loadFn := func(_ string) (string, error) {
			return rdb.ScriptLoad(ctx, body).Result()
		}
		if err := loader.Verify(loadFn); err != nil {
			log.Fatalf("\xe2\x9d\x8c Lua deploy-skew gate [%s]: %v", s.name, err)
		}
		fmt.Printf("\xe2\x9c\x85 Lua deploy-skew gate OK: %s\n", s.name)
	}
}

// bootCostTotalityGate verifies that every registered route in r has an
// explicit entry in the pre-loaded EndpointCostMap.
// It calls log.Fatalf if any route lacks an explicit cost entry, making
// it structurally impossible to forget to update endpoint_costs.yaml
// when adding a new route (Phase 9.6 §7.6 totality gate).
//
// Must be called after all routes are registered and before the HTTP
// server starts listening.
func bootCostTotalityGate(r *gin.Engine, m *sec.EndpointCostMap) {
	// Collect unique path patterns from the router (same path can appear
	// with multiple HTTP methods — cost is per-path, not per-method).
	seen := make(map[string]struct{})
	var patterns []string
	for _, info := range r.Routes() {
		if _, ok := seen[info.Path]; !ok {
			seen[info.Path] = struct{}{}
			patterns = append(patterns, info.Path)
		}
	}
	missing := m.CheckTotality(patterns, nil)
	if len(missing) > 0 {
		log.Fatalf("\xe2\x9d\x8c Endpoint-cost totality gate: routes with no explicit cost entry — add them to endpoint_costs.yaml: %v", missing)
	}
	fmt.Println("\xe2\x9c\x85 Endpoint-cost totality gate OK")
}

// qaHandler applies sec.QAInputGate to the request body before the Phase 10
// NLP layer processes it. Quarantined payloads are rejected with 422; passing
// payloads receive 202 Accepted with a qa_correlation_id (per §8.16.12).
//
// v1 body contract (closed for v1 per §9.15): { "q": str, "locale": str }.
// Phase 10 humanizer will add "humanize": bool as an additive minor bump.
// The qa_correlation_id returned here WILL be stamped on every
// predict.request.v1 spawned by the Phase 10 NLP fan-out.
func qaHandler(gate *sec.QAInputGate, cfg *config.Config) gin.HandlerFunc {
	return func(c *gin.Context) {
		var req struct {
			Q      string `json:"q"`
			Locale string `json:"locale"`
		}
		if err := c.ShouldBindJSON(&req); err != nil || req.Q == "" {
			aperrors.Respond(c, aperrors.CodeInvalidRequest, "q is required")
			return
		}

		answerFormat, err := resolveAnswerFormat(c)
		if err != nil {
			aperrors.Respond(c, aperrors.CodeInvalidRequest, err.Error())
			return
		}
		c.Set("answer_format", answerFormat)

		qaAnswerSchemaVersion, err := resolveQAAnswerSchemaVersion(c)
		if err != nil {
			aperrors.Respond(c, aperrors.CodeInvalidRequest, err.Error())
			return
		}
		if err := maybeFinalizeQAAnswerSchemaVersion(c, qaAnswerSchemaVersion, cfg); err != nil {
			aperrors.Respond(c, aperrors.CodeUpgradeRequired, err.Error())
			c.Abort()
			return
		}
		c.Set("qa_answer_schema_version", qaAnswerSchemaVersion)

		requestMetadata, err := resolveRequestMetadata(c)
		if err != nil {
			aperrors.Respond(c, aperrors.CodeInvalidRequest, err.Error())
			return
		}
		if requestMetadata != nil {
			c.Set("request_metadata", requestMetadata)
		}

		decision := gate.Inspect(req.Q)
		if decision.Verdict == sec.VerdictQuarantine {
			aperrors.Respond(c, aperrors.CodeQAQuarantined, "input rejected by security gate")
			return
		}
		// Phase 10 NLP fan-out wired here; qa_correlation_id will be
		// stamped on every predict.request.v1 envelope (§8.16.12).
		corrID := newQACorrelationID()
		c.JSON(http.StatusAccepted, gin.H{
			"status":            "accepted",
			"qa_correlation_id": corrID,
		})
	}
}

func resolveAnswerFormat(c *gin.Context) (string, error) {
	const (
		plain        = "plain"
		markdown     = "markdown_safe"
		screenReader = "screen_reader"
		whatsapp     = "whatsapp_4096"
		sms          = "sms_160"
		ttsNeutral   = "tts_neutral"
	)

	if q := strings.TrimSpace(c.Query("answer_format")); q != "" {
		switch q {
		case plain, markdown, screenReader, whatsapp, sms, ttsNeutral:
			return q, nil
		default:
			return "", fmt.Errorf("unsupported answer_format: %q", q)
		}
	}

	acceptHeader := c.GetHeader("Accept")
	for _, part := range strings.Split(acceptHeader, ",") {
		mediaType, _, err := mime.ParseMediaType(strings.TrimSpace(part))
		if err != nil {
			continue
		}
		switch strings.ToLower(mediaType) {
		case "text/x-screen-reader":
			return screenReader, nil
		case "text/markdown":
			return markdown, nil
		case "text/plain":
			return plain, nil
		}
	}
	return plain, nil
}

func resolveQAAnswerSchemaVersion(c *gin.Context) (int, error) {
	const serverSupported = 3
	acceptHeader := c.GetHeader("Accept")
	if acceptHeader == "" {
		return serverSupported, nil
	}

	for _, part := range strings.Split(acceptHeader, ",") {
		mediaType, params, err := mime.ParseMediaType(strings.TrimSpace(part))
		if err != nil {
			continue
		}
		if !strings.EqualFold(mediaType, "application/vnd.negelir.qa-answer+json") {
			continue
		}

		versionParam := strings.TrimSpace(params["version"])
		if versionParam == "" {
			return serverSupported, nil
		}

		bestVersion := 0
		for _, candidate := range strings.Split(versionParam, "|") {
			candidate = strings.TrimSpace(candidate)
			if candidate == "" {
				continue
			}
			v, err := strconv.Atoi(candidate)
			if err != nil {
				return 0, fmt.Errorf("invalid qa answer version: %q", candidate)
			}
			if v > bestVersion {
				bestVersion = v
			}
		}
		if bestVersion == 0 {
			return 0, fmt.Errorf("invalid qa answer version: %q", versionParam)
		}
		if bestVersion > serverSupported {
			return serverSupported, nil
		}
		return bestVersion, nil
	}

	return serverSupported, nil
}

func resolveRequestMetadata(c *gin.Context) (map[string]any, error) {
	metadata := map[string]any{}
	acceptHeader := c.GetHeader("Accept")
	for _, part := range strings.Split(acceptHeader, ",") {
		mediaType, params, err := mime.ParseMediaType(strings.TrimSpace(part))
		if err != nil {
			continue
		}
		if !strings.EqualFold(mediaType, "application/vnd.negelir.qa-answer+json") {
			continue
		}

		versionParam := strings.TrimSpace(params["version"])
		if versionParam == "" {
			continue
		}

		bestVersion := 0
		for _, candidate := range strings.Split(versionParam, "|") {
			candidate = strings.TrimSpace(candidate)
			if candidate == "" {
				continue
			}
			v, err := strconv.Atoi(candidate)
			if err != nil {
				return nil, fmt.Errorf("invalid qa answer version: %q", candidate)
			}
			if v > bestVersion {
				bestVersion = v
			}
		}
		if bestVersion == 0 {
			return nil, fmt.Errorf("invalid qa answer version: %q", versionParam)
		}
		metadata["client_format_max_version"] = bestVersion
		break
	}

	previewHeader := strings.TrimSpace(c.GetHeader("X-NLP-Preview"))
	if previewHeader != "" {
		if !isMTLSRequest(c.Request) {
			return nil, fmt.Errorf("X-NLP-Preview requires mTLS")
		}
		if strings.EqualFold(previewHeader, "true") || previewHeader == "1" {
			metadata["preview"] = true
			return metadata, nil
		}
		return nil, fmt.Errorf("unsupported X-NLP-Preview value: %q", previewHeader)
	}

	if len(metadata) == 0 {
		return nil, nil
	}
	return metadata, nil
}

func isMTLSRequest(req *http.Request) bool {
	return req.TLS != nil && len(req.TLS.VerifiedChains) > 0
}

func parseSunsetTime(cfg *config.Config) (time.Time, error) {
	if cfg.QAAnswerSunsetOnUTC != "" {
		return time.Parse(time.RFC3339, cfg.QAAnswerSunsetOnUTC)
	}
	return time.Now().UTC(), nil
}

func maybeFinalizeQAAnswerSchemaVersion(c *gin.Context, requestedVersion int, cfg *config.Config) error {
	if requestedVersion >= cfg.QAAnswerMinSupportedVersion {
		return nil
	}

	sunsetOn, err := parseSunsetTime(cfg)
	if err != nil {
		return fmt.Errorf("invalid sunset configuration: %v", err)
	}

	deadline := sunsetOn.Add(time.Duration(cfg.QAAnswerSunsetWindowDays) * 24 * time.Hour)
	c.Header("Deprecation", "true")
	c.Header("Sunset", deadline.Format("Mon, 02 Jan 2006 15:04:05 GMT"))
	if time.Now().UTC().After(deadline) {
		return fmt.Errorf("unsupported qa answer schema version %d; upgrade to %d", requestedVersion, cfg.QAAnswerMinSupportedVersion)
	}
	return nil
}

// newQACorrelationID returns a random UUIDv4 used as the qa_correlation_id
// stamped on predict.request.v1 envelopes spawned by the Phase 10 NLP fan-out
// (§8.16.12). UUIDv4 is used here (not v7) because qa correlation IDs are
// content-correlated, not time-sorted — the timestamp prefix is meaningless.
func newQACorrelationID() string {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		panic("cmd/api: crypto/rand.Read failed: " + err.Error())
	}
	b[6] = (b[6] & 0x0f) | 0x40 // version 4
	b[8] = (b[8] & 0x3f) | 0x80 // variant 10 (RFC 4122)
	return fmt.Sprintf("%08x-%04x-%04x-%04x-%012x",
		b[0:4], b[4:6], b[6:8], b[8:10], b[10:16])
}
