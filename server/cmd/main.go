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
)

func main() {
	fmt.Println("🚀 Negelir Middleware Server starting...")

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Database
	dbURL := getEnv("DATABASE_URL", "postgres://negelir:negelir_dev_2026@postgres:5432/negelir?sslmode=disable")
	dbConfig, err := pgxpool.ParseConfig(dbURL)
	if err != nil {
		log.Fatalf("❌ PostgreSQL URL error: %v", err)
	}
	dbConfig.MaxConns = 10
	dbConfig.ConnConfig.ConnectTimeout = 5 * time.Second

	pool, err := pgxpool.NewWithConfig(ctx, dbConfig)
	if err != nil {
		log.Fatalf("❌ PostgreSQL connection error: %v", err)
	}
	defer pool.Close()

	pingCtx, pingCancel := context.WithTimeout(ctx, 5*time.Second)
	if err := pool.Ping(pingCtx); err != nil {
		pingCancel()
		log.Printf("⚠️  PostgreSQL not ready yet, retrying...")
		time.Sleep(3 * time.Second)
		pingCtx2, pingCancel2 := context.WithTimeout(ctx, 5*time.Second)
		if err := pool.Ping(pingCtx2); err != nil {
			pingCancel2()
			log.Fatalf("❌ Could not connect to PostgreSQL: %v", err)
		}
		pingCancel2()
	} else {
		pingCancel()
	}
	fmt.Println("✅ PostgreSQL connection successful")

	// Redis
	redisAddr := getEnv("REDIS_URL", "redis:6379")
	rdb := redis.NewClient(&redis.Options{Addr: redisAddr})
	if err := rdb.Ping(ctx).Err(); err != nil {
		log.Printf("⚠️  Redis not ready yet, retrying...")
		time.Sleep(2 * time.Second)
		if err := rdb.Ping(ctx).Err(); err != nil {
			log.Fatalf("❌ Could not connect to Redis: %v", err)
		}
	}
	fmt.Println("✅ Redis connection successful")

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
		api.GET("/matches", matchesHandler(pool, rdb))
		api.GET("/matches/:id", matchDetailHandler(pool, rdb))
		api.GET("/teams", teamsHandler(pool, rdb))
		api.GET("/teams/:id", teamDetailHandler(pool))
		api.POST("/scrape/trigger", scrapeTriggerHandler(pool))
		api.GET("/features/:match_id", featuresHandler(pool, rdb))
	}

	port := getEnv("SERVER_PORT", "8080")
	srv := &http.Server{
		Addr:         ":" + port,
		Handler:      r,
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 30 * time.Second,
	}

	// Graceful shutdown
	go func() {
		fmt.Printf("📡 Server listening on :%s\n", port)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("❌ Server error: %v", err)
		}
	}()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	fmt.Println("\n🛑 Server shutting down...")
	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer shutdownCancel()
	if err := srv.Shutdown(shutdownCtx); err != nil {
		log.Fatalf("❌ Server shutdown error: %v", err)
	}
	if err := rdb.Close(); err != nil {
		log.Printf("⚠️  Redis close error: %v", err)
	}
	fmt.Println("✅ Server shut down successfully")
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

func matchesHandler(pool *pgxpool.Pool, rdb *redis.Client) gin.HandlerFunc {
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
				"id":           id,
				"home_team":    homeTeam,
				"away_team":    awayTeam,
				"match_date":   matchDate.Format("2006-01-02"),
				"league":       leagueID,
				"season":       season,
				"home_score":   homeScore,
				"away_score":   awayScore,
				"match_week":   matchWeek,
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

		// Write to cache (5 min TTL)
		if data, err := json.Marshal(result); err == nil {
			rdb.Set(ctx, "matches:list", data, 5*time.Minute)
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
			"id":           id,
			"home_team":    homeTeam,
			"away_team":    awayTeam,
			"match_date":   matchDate.Format("2006-01-02"),
			"league":       leagueID,
			"season":       season,
			"home_score":   homeScore,
			"away_score":   awayScore,
			"match_week":   matchWeek,
		})
	}
}

func teamsHandler(pool *pgxpool.Pool, rdb *redis.Client) gin.HandlerFunc {
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

		// Write to cache (10 min TTL)
		if data, err := json.Marshal(result); err == nil {
			rdb.Set(ctx, "teams:list", data, 10*time.Minute)
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

func getEnv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
