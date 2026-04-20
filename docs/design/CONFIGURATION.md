# 🔧 Centralized Configuration

> Companion to Phase 1 of [`../planning/ROADMAP.md`](../planning/ROADMAP.md).
> **Doctrine:** *one place per language, env-driven, validated, sync-tested.*

## 📐 Layout

```
xops/env/.env.example             # canonical env-var documentation
ai/common/
├── config.py                     # Python @dataclass Config, the only Python config
└── defaults.yaml                 # generated from config.py for human readers
server/internal/config/
├── config.go                     # Go Config struct, the only Go config
└── sync_test.go                  # parity test against xops/env/.env.example
ai/tests/test_config_sync.py      # parity test for the Python side
xops/lint/no_magic.py             # lint that forbids magic numbers
```

## 🎛️ Naming conventions

| Prefix | Owner | Example |
|---|---|---|
| `NEGELIR_` | shared (Python + Go) | `NEGELIR_DEFAULT_LEAGUE_ID` |
| `SCRAPE_` | scrapers | `SCRAPE_RATE_LIMIT_SECONDS` |
| `AI_` | AI image / runtime hints | `AI_DEVICE`, `AI_IMAGE_FLAVOR` |
| `SERVER_` | Go API / mock server | `SERVER_PORT`, `SERVER_MODE` |
| `POSTGRES_` / `REDIS_` | infra connection | standard |
| `SEC_` | security agents | `SEC_INPUT_MAX_LEN`, `SEC_BURST_THRESHOLD` |
| `SWARM_` | bus / agents platform | `SWARM_HEARTBEAT_SEC`, `SWARM_BUS_KIND` |

A single key may not be owned by both Python and Go unless `xops/env/.env.example`
marks it `# shared`. The meta-test enforces this.

## ✅ Validation rules

- Every key in `xops/env/.env.example` is read by at least one config layer.
- Every config field has a sane default; validation rejects out-of-range values on startup.
- Strict mode (`NEGELIR_STRICT=1`) refuses unknown keys with our prefixes — catches typos and stale configs.
- Tuple-range fields (e.g. `feature_ranges`) check `lo < hi`.
- Day-of-week fields check valid weekday names.
- URL fields check scheme.

## 🚫 Forbidden patterns

(enforced by `xops/lint/no_magic.py` in CI)

- Numeric literal in non-test code unless inside a `Config` field default.
- `localhost:<port>` outside test fixtures.
- `time.sleep(<int>)` in production code.
- `requests.get("https://...")` with a hardcoded URL.
- Float thresholds (`> 0.5`, `< 0.7`, …) — must be named.

## 🔄 Bidirectional sync

The `test_config_sync.py` and `sync_test.go` tests assert:

1. Every key documented in `xops/env/.env.example` is consumed by at least one config layer.
2. Every key consumed by a config layer is documented in `xops/env/.env.example`.
3. Defaults in `xops/env/.env.example` match defaults in code.
4. Pickle round-trip succeeds for the Python `Config` (config-as-data).
5. No Phase-2 synthetic-data env keys leak back in.

## 🌍 Same config, three deployments

Local compose, prod compose, and K8s all set the same env vars. The `Config`
layer doesn't care where they came from — `os.getenv` for Python, `env:` tags
for Go. K8s Secrets / ConfigMaps just project the same names.
