# `xops/env/` — Environment Configuration

This folder is the **single source of truth** for every environment
variable consumed by the Negelir dev stack.

## Files

| File | Purpose | Tracked? |
|---|---|---|
| `.env.example` | Canonical template; every key is documented and groups are commented. | ✅ committed |
| `.env`         | Real values (passwords, overrides). | ✅ committed (dev) |
| `README.md`    | This file. | ✅ committed |

## Lifecycle

```bash
make env       # copies .env.example → xops/env/.env if missing
```

After bootstrap, edit `xops/env/.env` — `POSTGRES_PASSWORD` is the only
required override (the `make up` Postgres guard refuses to boot without
it).

## How Compose finds it

Every `docker compose` invocation in this repo goes through the
`compose_run`/`compose_exec` helpers in
[`xops/makefile/_common.py`](../makefile/_common.py), which auto-prefix
the command with `--env-file xops/env/.env`. That feeds Compose's own
variable substitution (ports, healthchecks, the password guard).

Each service in [`docker-compose.yml`](../../docker-compose.yml) also
pulls the same file via `env_file:`, so container-side processes see
exactly the values the host saw — no duplication, no drift.

If you call `docker compose` directly (bypassing `make`), pass it
yourself:

```bash
docker compose --env-file xops/env/.env up
```

Override the location with `NEGELIR_ENV_FILE=/abs/path/other.env make up`.

## Sync tests

- Python: `ai/tests/test_config_sync.py`
- Go:     `server/internal/config/sync_test.go`

Both walk to `xops/env/.env.example` and assert that every documented
key is consumed by at least one config layer (and vice versa). Adding
a new tunable means: add it to `.env.example`, then read it through
`ai/common/config.py` or `server/internal/config`.
