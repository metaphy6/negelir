# Negelir Go Middleware Server

## Overview

Go middleware server that fetches data from sources, stores in PostgreSQL, and caches with Redis.

## Technologies

| Library | Version | Usage |
|---------|---------|-------|
| Gin | 1.9.1 | HTTP framework |
| pgx/v5 | 5.5.1 | PostgreSQL driver |
| go-redis/v9 | 9.4.0 | Redis client |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/health` | System health status |
| GET | `/api/v1/matches` | Last 50 matches |
| GET | `/api/v1/matches/:id` | Match details |
| GET | `/api/v1/teams` | All teams |
| GET | `/api/v1/teams/:id` | Team details |
| POST | `/api/v1/scrape/trigger` | Trigger data fetch task |
| GET | `/api/v1/features/:match_id` | Feature vector |

## Health Check

```json
GET /api/v1/health

{
  "status": "healthy",
  "database": true,
  "redis": true,
  "version": "0.1.0"
}
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | empty | Full PostgreSQL DSN (optional if `POSTGRES_*` is set) |
| `POSTGRES_HOST` | `postgres` | PostgreSQL host fallback |
| `POSTGRES_PORT` | `5432` | PostgreSQL port fallback |
| `POSTGRES_DB` | `negelir` | PostgreSQL database fallback |
| `POSTGRES_USER` | `negelir` | PostgreSQL user fallback |
| `POSTGRES_PASSWORD` | empty | PostgreSQL password fallback |
| `REDIS_URL` | empty | Full Redis address (optional if `REDIS_*` is set) |
| `REDIS_HOST` | `redis` | Redis host fallback |
| `REDIS_PORT` | `6379` | Redis port fallback |
| `SERVER_PORT` | `8080` | Listen port |
| `DB_MAX_CONNS` | `10` | PostgreSQL max pooled connections |
| `DB_CONNECT_TIMEOUT_SEC` | `5` | PostgreSQL connect timeout |
| `DB_PING_TIMEOUT_SEC` | `5` | PostgreSQL ping timeout |
| `HTTP_READ_TIMEOUT_SEC` | `10` | HTTP read timeout |
| `HTTP_WRITE_TIMEOUT_SEC` | `30` | HTTP write timeout |
| `CACHE_MATCHES_TTL_SEC` | `300` | `/matches` cache TTL |
| `CACHE_TEAMS_TTL_SEC` | `600` | `/teams` cache TTL |
| `GIN_MODE` | `release` | Gin mode |

## Building

```bash
# With Docker (recommended)
make server

# Local
cd server && go build -o bin/server ./cmd/main.go
```

## Architecture

```
server/
├── Dockerfile          # Multi-stage build
├── go.mod              # Dependencies
├── go.sum              # Dependency lock
├── cmd/
│   └── main.go         # Entry point + all handlers
└── docs/
    └── README.md       # This file
```

Supports graceful shutdown (SIGINT/SIGTERM).


