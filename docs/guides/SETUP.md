# Negelir — Setup Guide

## Prerequisites

| Tool | Minimum Version | Description |
|------|-----------------|-------------|
| Docker | 24.0+ | Container runtime |
| Docker Compose | 2.20+ | Multi-container orchestration |
| Make | 4.0+ | Build automation |
| Git | 2.40+ | Version control |

### Optional (local development)

| Tool | Version | Description |
|------|---------|-------------|
| Python | 3.11+ | AI module development |
| Go | 1.22+ | Server development |
| CUDA | 12.0+ | GPU acceleration (target: RTX 4080) |

> **Infrastructure note:** PostgreSQL, Redis, and the Go middleware server are **local
> development tools only**. They provide a convenient way to inspect raw scraped data
> and cached feature payloads during development. They are **not** required to run the
> AI engine, and they are **not** part of the production deployment. The AI service
> (`ai/`) is fully self-contained and connects directly to its configured scraping
> sources.

## Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/metaphy6/negelir.git
cd negelir

# 2. Create environment file
cp .env.example .env

# 3. Start all services
make up

# 4. Health check
make health

# 5. AI demo
make ai-demo
```

## All Commands

```bash
make help          # List all commands

# === Core ===
make up            # Start with Docker Compose
make down          # Stop all services
make restart       # Restart all services
make logs          # Follow all logs
make health        # Health check

# === AI ===
make ai            # AI service only
make ai-demo       # AI demo mode (11 Turkish questions)
make ai-pipeline   # Run full pipeline
make ai-train      # Model training
make ai-tqu-test   # TQU test mode

# === P2P ===
make p2p            # P2P service
make p2p-simulate   # P2P simulation (5 nodes, 10 matches)

# === Server ===
make server         # Go middleware server
make server-scrape  # Trigger scrape task

# === Database ===
make db-shell       # Open PostgreSQL shell
make db-migrate     # Run migrations
make db-reset       # Reset database

# === Cleanup ===
make clean          # Clean Docker data
make nuke           # Delete everything (CAUTION!)
```

## GPU Configuration

### NVIDIA GPU (recommended: RTX 4080)

1. Install NVIDIA Container Toolkit
2. Set `AI_DEVICE=cuda` in `.env`
3. Enable the GPU deploy block in `docker-compose.yml`

```yaml
# In docker-compose.yml under the ai service:
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: 1
          capabilities: [gpu]
```

### CPU Mode (default)

No additional configuration required. The system runs in CPU mode automatically.
Set `AI_DEVICE=cpu` or leave empty.

## Environment Variables

Use `.env.example` as the canonical source of every configurable key.

| Group | Canonical Prefix/Keys | Description |
|------|------------------------|-------------|
| AI runtime | `NEGELIR_*` | Scheduler, scraper, model, telemetry defaults for `ai/common/config.py` |
| P2P network | `P2P_*` | Discovery, transport, gossip consensus, retention, simulation |
| Server runtime | `DB_*`, `HTTP_*`, `CACHE_*`, `SERVER_PORT` | Go server DB pool, HTTP timeouts, cache TTLs, listen port |
| Infra connectivity | `POSTGRES_*`, `REDIS_*`, `DATABASE_URL`, `REDIS_URL` | Database/Redis connection settings |
| Device and logs | `AI_DEVICE`, `AI_LOG_LEVEL` | Inference hardware target and logging verbosity |

Legacy fallback aliases were removed. Set canonical keys directly to avoid ambiguity.

## Troubleshooting

### Docker memory error
```bash
# Increase Docker memory limit (at least 4GB)
# Docker Desktop → Settings → Resources → Memory
```

### PostgreSQL connection error
```bash
# Check container logs
docker compose logs postgres

# Try manual connection
make db-shell
```

### GPU not detected
```bash
# Check NVIDIA driver
nvidia-smi

# Check inside container
docker compose exec ai python -c "import xgboost; print(xgboost.build_info())"
```
