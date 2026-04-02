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
| `DATABASE_URL` | `postgres://negelir:negelir_dev@postgres:5432/negelir` | PostgreSQL connection string |
| `REDIS_URL` | `redis:6379` | Redis address |
| `SERVER_PORT` | `8080` | Listen port |
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


