/*
Negelir Go Middleware Server
Fetches data from external sources, stores to PostgreSQL, caches in Redis.
Serves REST API for the AI module.
*/
package main

import (
	"context"
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
			SELECT id, home_team_id, away_team_id, match_date, league, season,
				   home_score, away_score, status
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
			var id, homeTeamID, awayTeamID, league, season, status string
			var matchDate time.Time
			var homeScore, awayScore *int

			if err := rows.Scan(&id, &homeTeamID, &awayTeamID, &matchDate,
				&league, &season, &homeScore, &awayScore, &status); err != nil {
				continue
			}
			matches = append(matches, gin.H{
				"id":            id,
				"home_team_id":  homeTeamID,
				"away_team_id":  awayTeamID,
				"match_date":    matchDate.Format("2006-01-02"),
				"league":        league,
				"season":        season,
				"home_score":    homeScore,
				"away_score":    awayScore,
				"status":        status,
			})
		}

		if matches == nil {
			matches = []gin.H{}
		}

		c.JSON(http.StatusOK, gin.H{
			"matches": matches,
			"count":   len(matches),
		})
	}
}

func matchDetailHandler(pool *pgxpool.Pool, rdb *redis.Client) gin.HandlerFunc {
	return func(c *gin.Context) {
		id := c.Param("id")
		ctx := c.Request.Context()

		var homeTeamID, awayTeamID, league, season, status string
		var matchDate time.Time
		var homeScore, awayScore *int
		var rawJSON *string

		err := pool.QueryRow(ctx, `
			SELECT home_team_id, away_team_id, match_date, league, season,
				   home_score, away_score, status, raw_json::text
			FROM raw_matches WHERE id = $1
		`, id).Scan(&homeTeamID, &awayTeamID, &matchDate, &league, &season,
			&homeScore, &awayScore, &status, &rawJSON)

		if err != nil {
			c.JSON(http.StatusNotFound, gin.H{"error": "match not found"})
			return
		}

		c.JSON(http.StatusOK, gin.H{
			"id":            id,
			"home_team_id":  homeTeamID,
			"away_team_id":  awayTeamID,
			"match_date":    matchDate.Format("2006-01-02"),
			"league":        league,
			"season":        season,
			"home_score":    homeScore,
			"away_score":    awayScore,
			"status":        status,
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
			SELECT id, name, short_name, league
			FROM teams
			ORDER BY name
		`)
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "could not fetch data"})
			return
		}
		defer rows.Close()

		var teams []gin.H
		for rows.Next() {
			var id, name, shortName, league string
			if err := rows.Scan(&id, &name, &shortName, &league); err != nil {
				continue
			}
			teams = append(teams, gin.H{
				"id":         id,
				"name":       name,
				"short_name": shortName,
				"league":     league,
			})
		}

		if teams == nil {
			teams = []gin.H{}
		}

		c.JSON(http.StatusOK, gin.H{
			"teams": teams,
			"count": len(teams),
		})
	}
}

func teamDetailHandler(pool *pgxpool.Pool) gin.HandlerFunc {
	return func(c *gin.Context) {
		id := c.Param("id")
		ctx := c.Request.Context()

		var name, shortName, league string
		err := pool.QueryRow(ctx, `
			SELECT name, short_name, league FROM teams WHERE id = $1
		`, id).Scan(&name, &shortName, &league)
		if err != nil {
			c.JSON(http.StatusNotFound, gin.H{"error": "team not found"})
			return
		}

		c.JSON(http.StatusOK, gin.H{
			"id":         id,
			"name":       name,
			"short_name": shortName,
			"league":     league,
		})
	}
}

func scrapeTriggerHandler(pool *pgxpool.Pool) gin.HandlerFunc {
	return func(c *gin.Context) {
		ctx := c.Request.Context()

		// Insert a scrape task
		var taskID string
		err := pool.QueryRow(ctx, `
			INSERT INTO scrape_tasks (source_name, source_url, status)
			VALUES ('manual_trigger', 'N/A', 'pending')
			RETURNING id
		`).Scan(&taskID)

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

		var featuresJSON *string
		err := pool.QueryRow(ctx, `
			SELECT feature_vector::text FROM team_features
			WHERE match_id = $1
			LIMIT 1
		`, matchID).Scan(&featuresJSON)

		if err != nil || featuresJSON == nil {
			c.JSON(http.StatusNotFound, gin.H{"error": "feature data not found"})
			return
		}

		c.Data(http.StatusOK, "application/json", []byte(*featuresJSON))
	}
}

// --- Helpers ---

func getEnv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
