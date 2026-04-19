/*
Negelir Go Middleware Server
Fetches data from external sources, stores to PostgreSQL, caches in Redis.
Serves REST API for the AI module.
*/
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"

	"github.com/metaphy6/negelir/server/internal/config"
)

func main() {
	fmt.Println("\xf0\x9f\x9a\x80 Negelir Middleware Server starting...")
	cfg, err := config.Load()
	if err != nil {
		log.Fatalf("\xe2\x9d\x8c Config error: %v", err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Database
	dbConfig, err := pgxpool.ParseConfig(cfg.EffectiveDatabaseURL())
	if err != nil {
		log.Fatalf("\xe2\x9d\x8c PostgreSQL URL error: %v", err)
	}
	dbConfig.MaxConns = int32(cfg.DBMaxConns)
	dbConfig.ConnConfig.ConnectTimeout = cfg.DBConnectTimeout()

	pool, err := pgxpool.NewWithConfig(ctx, dbConfig)
	if err != nil {
		log.Fatalf("\xe2\x9d\x8c PostgreSQL connection error: %v", err)
	}
	defer pool.Close()

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

	// Redis
	rdb := redis.NewClient(&redis.Options{Addr: cfg.EffectiveRedisURL()})
	if err := rdb.Ping(ctx).Err(); err != nil {
		log.Printf("\xe2\x9a\xa0\xef\xb8\x8f  Redis not ready yet, retrying...")
		time.Sleep(cfg.RedisRetryDelay())
		if err := rdb.Ping(ctx).Err(); err != nil {
			log.Fatalf("\xe2\x9d\x8c Could not connect to Redis: %v", err)
		}
	}
	fmt.Println("\xe2\x9c\x85 Redis connection successful")

	// Router
	if os.Getenv("GIN_MODE") == "" {
		gin.SetMode(gin.ReleaseMode)
	}
	r := gin.New()
	r.Use(gin.Recovery())
	r.Use(requestLogger())

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

	srv := &http.Server{
		Addr:         ":" + cfg.Port,
		Handler:      r,
		ReadTimeout:  cfg.HTTPReadTimeout(),
		WriteTimeout: cfg.HTTPWriteTimeout(),
	}

	// Graceful shutdown
	go func() {
		fmt.Printf("\xf0\x9f\x93\xa1 Server listening on :%s\n", cfg.Port)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("\xe2\x9d\x8c Server error: %v", err)
		}
	}()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	fmt.Println("\n\xf0\x9f\x9b\x91 Server shutting down...")
	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), cfg.HTTPShutdownTimeout())
	defer shutdownCancel()
	if err := srv.Shutdown(shutdownCtx); err != nil {
		log.Fatalf("\xe2\x9d\x8c Server shutdown error: %v", err)
	}
	if err := rdb.Close(); err != nil {
		log.Printf("\xe2\x9a\xa0\xef\xb8\x8f  Redis close error: %v", err)
	}
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

func matchesHandler(pool *pgxpool.Pool, rdb *redis.Client, cacheTTL time.Duration) gin.HandlerFunc {
	return func(c *gin.Context) {
		ctx := c.Request.Context()

		// Try cache first
		cached, err := rdb.Get(ctx, "matches:list").Result()
		if err == nil && cached != "" {
			c.Data(http.StatusOK, "application/json", []byte(cached))
			return
		}

		rows, err := pool.Query(ctx, `
			SELECT id, home_team, away_team, match_date, league_id, season,
				   home_score, away_score, match_week
			FROM raw_matches
			ORDER BY match_date DESC
			LIMIT 50
		`)
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "could not fetch data"})
			return
		}
		defer rows.Close()

		var matches []gin.H
		for rows.Next() {
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
			c.JSON(http.StatusInternalServerError, gin.H{"error": "row iteration error"})
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
			rdb.Set(ctx, "matches:list", data, cacheTTL)
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
			c.JSON(http.StatusNotFound, gin.H{"error": "match not found"})
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
			c.JSON(http.StatusInternalServerError, gin.H{"error": "could not fetch data"})
			return
		}
		defer rows.Close()

		var teams []gin.H
		for rows.Next() {
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
			c.JSON(http.StatusInternalServerError, gin.H{"error": "row iteration error"})
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
			c.JSON(http.StatusNotFound, gin.H{"error": "team not found"})
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
			c.JSON(http.StatusInternalServerError, gin.H{"error": "could not create scrape task"})
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
			c.JSON(http.StatusNotFound, gin.H{"error": "feature data not found"})
			return
		}
		defer rows.Close()

		var features []gin.H
		for rows.Next() {
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
			c.JSON(http.StatusInternalServerError, gin.H{"error": "row iteration error"})
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
