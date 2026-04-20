# Swarm Network — How the Phase 2 Mock Stack Plugs Into the Future Swarm

> **Status:** Design (Phase 2 → Phase 3+ bridge)
> **Audience:** anyone wiring a new compose service (agent, scraper,
> evaluator, etc.) into the dev stack.

---

## 1. TL;DR

The mock-data dev stack already exposes a **container-to-container
network** that any future swarm agent can join with a one-line
`networks:` block. Inside that network:

| Endpoint | Resolves to | Purpose |
|---|---|---|
| `http://mocksrv:8090/` | `mocksrv` container | Direct content-by-(host,path) lookup |
| `http://mocksrv:8090/__mocksrv/health` | same | Liveness |
| `http://mocksrv:8090/__mocksrv/reload` | same | Hot-reload manifest |
| `https://mackolik.local/` | `nginx-mock` (TLS) | Browser-shaped HTTP, real routing semantics |
| `https://nesine.local/` | `nginx-mock` (TLS) | ″ |
| `https://tff.local/` | `nginx-mock` (TLS) | ″ |
| `https://openfootball.local/` | `nginx-mock` (TLS) | ″ |
| `postgres:5432` | `postgres` | Shared DB (use the dev creds in `.env`) |
| `redis:6379` | `redis` | Shared cache / pub-sub bus |

All of the above are reachable by **service DNS name** from any
container that joins the `mocknet` (and default) bridge.

---

## 2. The network topology

```
                                ┌──────────────────────────────┐
                                │       mocknet (bridge)       │
                                │                              │
   ┌────────┐  resolves to      │  ┌────────┐    ┌──────────┐  │
   │  agent │ ─── mackolik.local│─►│ nginx- │───►│ mocksrv  │  │
   │ (you!) │     (network alias)  │  mock  │    │  :8090   │  │
   └────┬───┘                   │  └────────┘    └──────────┘  │
        │                       │       ▲              ▲       │
        │ uses postgres:5432    │       │              │       │
        │      redis:6379       │       │ TLS w/ dev   │ HTTP  │
        ▼                       │       │ leaf certs   │ plain │
   ┌──────────┐ ┌──────────┐    │       └──────────────┘       │
   │ postgres │ │  redis   │    └──────────────────────────────┘
   └──────────┘ └──────────┘    (defined in docker-compose.mock.yml)
```

Network-aliases on `nginx-mock` (declared in
`docker-compose.mock.yml`):

```yaml
networks:
  mocknet:
    aliases:
      - mackolik.local
      - nesine.local
      - tff.local
      - openfootball.local
```

That alias trick is what lets a containerized scraper code path keep
its production URL unchanged (`https://www.mackolik.com/...`) while
still landing on the mock — see §3.

---

## 3. Wiring a new agent container

### 3.1 Minimal compose snippet

```yaml
# docker-compose.swarm.yml  (overlay)
services:
  my-agent:
    build: ./ai-agents/my-agent
    environment:
      # Tell the agent it's running against the mock corpus.
      NEGELIR_SCRAPE_PROFILE: mock
      # If the agent uses a non-system HTTP client, point it at the dev CA.
      SSL_CERT_FILE: /etc/ssl/negelir-ca.crt
      REQUESTS_CA_BUNDLE: /etc/ssl/negelir-ca.crt
      # Direct-to-mocksrv shortcut (skips TLS + nginx).
      MOCKSRV_URL: http://mocksrv:8090
      # Shared infra
      POSTGRES_HOST: postgres
      POSTGRES_PORT: 5432
      REDIS_HOST: redis
      REDIS_PORT: 6379
    volumes:
      - ./infra/mock/ca/root.crt:/etc/ssl/negelir-ca.crt:ro
    networks:
      - default
      - mocknet
    depends_on:
      mocksrv:
        condition: service_started

networks:
  mocknet:
    external: true   # joined; not redefined
    name: negelir_mocknet
```

Bring it up alongside the rest of the stack:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.mock.yml \
  -f docker-compose.swarm.yml \
  up -d --build
```

### 3.2 Two ways to talk to the mock

| Mode | URL pattern | When |
|---|---|---|
| **Direct** | `GET http://mocksrv:8090/` with `Host: mackolik.local` header | Lowest overhead, no TLS, ideal for high-volume agents |
| **Browser-shaped** | `GET https://mackolik.local/` (no special Host header — the alias resolves it) | Closest to production behavior; exercises nginx routing |

The second mode requires the dev root CA mounted as
`/etc/ssl/negelir-ca.crt` and your HTTP client honoring it
(`SSL_CERT_FILE` is the universal lever for OpenSSL-based stacks
including Python's `requests`, Go's `crypto/tls`, and `curl --cacert`).

### 3.3 Home-page fallback

mocksrv serves the captured home HTML for **any** unknown path on a
known host (default `-fallback=true`). Each fallback response carries:

```
HTTP/1.1 200 OK
X-Negelir-Mock-Fallback: 1
X-Negelir-Mock-Captured-At: <iso8601>
X-Negelir-Mock-Sha256: <hash>
```

This means an agent that follows links found in `/` won't 404 even if
the deep page hasn't been captured yet. Combine with `make
mock.capture DEPTH=1` to actually seed the deep pages on first run.

---

## 4. Idempotency & seed lifecycle

The capture pipeline is **idempotent by default** (per §1 of the
user's Phase-2 follow-up). The only ways to refetch from the real
internet are:

| Trigger | Effect |
|---|---|
| `make mock.capture` | No-op for already-seeded targets (skipped). |
| `make mock.capture FORCE=1` | Refetch every target. |
| `make mock.capture DEPTH=1` | Capture + follow same-host links one level deep. |
| `make mock.reset` | Wipe `infra/mock/seeds/` + manifest. Next capture will refetch. |
| `make mock.smoke` | reset → capture (DEPTH=1) → up → curl every vhost (incl. fallback path). |

Agents in the swarm should **never** call `mock.capture` themselves —
that's a developer/CI operation. They should always read from the
seed corpus via mocksrv or nginx-mock.

---

## 5. Speed defaults (DEV ONLY)

The **base** `docker-compose.yml` is already tuned for the fastest
inner-loop dev experience — there is no separate "fast" overlay.
What that means in practice:

- Postgres → `fsync=off`, `synchronous_commit=off`, tmpfs `/var/lib/postgresql/data` (1 GB).
- Redis    → `--save "" --appendonly no`, tmpfs `/data` (512 MB), LRU eviction.
- Server   → tighter pool sizes, sub-second timeouts, 30 s cache TTLs.
- AI       → `SCRAPE_RATE_LIMIT_SECONDS=0` (safe only because the
  scrape profile is `mock`).

```bash
make up   # tmpfs Postgres + Redis, all defaults dialled for speed
```

**Trade-off:** any container restart wipes Postgres + Redis state.
That's the price for the speed and is fine in dev because migrations
live under `migrations/` and re-run automatically via the
`docker-entrypoint-initdb.d` mount on every fresh container.

**Production override (future):** when the time comes to ship
Negelir to a real environment, point `pg_data` and `redis_data` at
named volumes via a `docker-compose.prod.yml` overlay and remove the
`tmpfs:` blocks. The other knobs (`fsync`, `appendonly`) live in
`command:`, so flipping those for prod is a one-file change.

---

## 6. Pub/sub bus & shared state

The Phase 3 swarm will use Redis as the bus (see roadmap). Two
patterns are already supported by the current `docker-compose.yml`:

```python
# Python: publish a tick every time a fixture is observed
import redis
r = redis.Redis(host="redis", port=6379)
r.publish("negelir.fixture.observed", payload_bytes)
```

```go
// Go: subscribe in the server
sub := rdb.Subscribe(ctx, "negelir.fixture.observed")
for msg := range sub.Channel() { ... }
```

There is no mandate to use Redis pub/sub — it's the path of least
resistance. NATS / Postgres LISTEN/NOTIFY / etc. would each require
adding a new service; do that in a separate ROADMAP phase.

---

## 7. Security boundary

- The dev root CA (`infra/mock/ca/root.crt`) is **trusted only inside
  containers** via the `SSL_CERT_FILE` mount. The host's keychain is
  modified only when the user opts in via `make mock.browser` and
  runs the printed sudo commands.
- The mock CA must never be checked into a release artefact. It's
  generated locally per-clone and is git-ignored under
  `infra/mock/ca/`.
- mocksrv listens only on the docker bridge network. It has no
  authentication. Anyone who can reach the bridge can trigger
  `__mocksrv/reload` — that's acceptable for dev only.

---

## 8. Readiness checklist

Use this as a copy/paste pre-flight when bringing up a new swarm
agent against the mock stack:

- [ ] `make mock.ca-init` (root CA + leaf certs exist)
- [ ] `make mock.capture DEPTH=1` (seed corpus has home + links)
- [ ] `make mock.nginx` (vhost configs rendered)
- [ ] `make mock.up` (mocksrv + nginx-mock running)
- [ ] `curl -k https://mackolik.local/` returns the captured HTML
- [ ] `curl -k https://mackolik.local/__random__` returns 200 with
  `X-Negelir-Mock-Fallback: 1`
- [ ] Your agent's compose joins `mocknet` with `external: true`
- [ ] Your agent has `NEGELIR_SCRAPE_PROFILE=mock` and
  `SSL_CERT_FILE=/etc/ssl/negelir-ca.crt`
- [ ] Optional: tighter agent‑side defaults via `.env` overrides

If every box ticks: **the mock stack is ready to be consumed by the
swarm.**

---

## 9. References

- `docker-compose.mock.yml` — service + network definitions
- `xops/mock/capture_engine.py` — idempotent capture + depth-1 crawl
- `server/cmd/mocksrv/main.go` — manifest router + home-page fallback
- `xops/mock/sources.py` — declarative source registry (4 sites today)
- `docs/design/MOCK_DATA_SERVER.md` — full Phase 2 design
