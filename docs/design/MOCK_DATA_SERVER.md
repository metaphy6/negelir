# 🌐 Mock-Data Dev Stack ("Fake Internet")

> Companion to Phase 2 of [`../planning/ROADMAP.md`](../planning/ROADMAP.md).

## 🎯 Goal

Local dev and CI **never** hit the real internet. Every scraper request
resolves to a local nginx that serves byte-identical captures of the real
sources, over real (self-signed) TLS.

## 🧱 Components

```
infra/mock/
├── ca/                       # root CA (gen once, gitignored)
│   ├── ca.key
│   └── ca.crt
├── certs/                    # leaf certs per fake domain
│   ├── mackolik.local.{crt,key}
│   ├── nesine.local.{crt,key}
│   ├── tff.local.{crt,key}
│   └── openfootball.local.{crt,key}
├── nginx/
│   ├── nginx.conf            # one server block per vhost
│   └── snippets/             # tls config, common headers
└── seeds/
    ├── manifest.json         # url, sha256, captured_at, content_type
    ├── mackolik.com/...      # frozen html / json / images
    ├── nesine.com/...
    └── tff.org/...

xops/mock/                    # automation lives under xops/ per AGENTS.md §5
├── ca.py                     # cross-platform CA + leaf cert generator
├── hosts_file.py             # idempotent /etc/hosts editor
├── capture_engine.py         # one-time real-source capture (Phase 2.4)
├── manifest.py               # manifest read/write helpers
├── verify.py                 # offline integrity check (Phase 2.5)
├── nginx.py                  # vhost renderer (deterministic)
├── sources.py                # source registry (URL allow-list, robots policy)
└── tests/                    # pytest suite for the above
```

## 🔑 TLS

- `make mock.ca-init` runs `xops/mock/ca.py` (only if `ca.crt` is missing); the same module also issues leaf certificates for every domain in the source registry.
- `make mock.nginx` re-renders the vhost configs (driver: `xops/mock/nginx.py`) when the leaf cert set or the source registry changes.
- The CA is **mounted** into:
  - `nginx-mock` (terminates TLS).
  - Every Python image: appended to `/etc/ssl/certs/ca-certificates.crt` via `update-ca-certificates` in the entrypoint.
  - Every Go image: same. (Go reads system roots.)
- **Host trust is opt-in.** `make mock.trust` (and its inverse `make mock.untrust`) install the dev CA into the host trust store via `sudo` — the only sanctioned `sudo` callers per AGENTS.md §2 rule 10. Without it, browsers / `curl` from the host won't trust the CA — by design.

## 🪪 Hostnames

We use `.local` TLDs to avoid colliding with real DNS:

```
mackolik.local
nesine.local
tff.local
openfootball.local
```

Scraper config switches via env:

```bash
NEGELIR_SCRAPE_PROFILE=mock     # default in dev
NEGELIR_SCRAPE_PROFILE=real     # opt-in for `make mock.capture`
```

`LeagueConfig.scrape_endpoints` then composes the right base URL:

```python
base = "https://mackolik.local" if profile == "mock" else "https://www.mackolik.com"
```

## 📦 Seed corpus

- One-time capture: `make mock.capture` runs `xops/mock/capture_engine.py` against the **real** sources. The driver is rate-limited, respects `robots.txt`, declares its user-agent, and only fetches URLs that the source registry (`xops/mock/sources.py`) allows. Supports `DEPTH=N` to follow same-host links one level deep, and `FORCE=1` to refetch already-seeded targets.
- Each capture writes: the response body verbatim, status code, headers, and an entry in `infra/mock/seeds/manifest.json` with sha256 + captured_at.
- Captures are committed (small) or LFS'd (large).
- `make mock.verify` re-hashes everything and refuses to bring up nginx-mock if a seed is corrupt.
- `make mock.reset` wipes `infra/mock/seeds/` + manifest (the next capture starts clean).

## 🧪 Integrity tests

Tests live under `xops/mock/tests/`:

- `test_manifest.py` + `test_manifest_contract.py` — manifest schema and round-trip integrity.
- `test_live_parity.py` — for every URL in `manifest.json`, fetch it from `nginx-mock` (in CI: from the in-process mock server) and assert byte-identical body + matching status.
- `test_capture_engine.py` — capture engine behaviour under rate-limit, robots, and depth-1 crawl.
- `test_ca.py`, `test_hosts_file.py`, `test_nginx.py`, `test_sources.py` — per-module unit coverage.

The per-source extractor shape tests live with the extractors
(`datasource/scraper/tests/` post-Pivot v3; `ai/scraper/` today) and
run against the seed corpus via the `mock` profile.

## 🧰 Makefile UX (final)

```
make mock.ca-init        # one-time: generate root CA + leaf certs
make mock.nginx          # re-render nginx vhost configs
make mock.up             # bring up nginx-mock + seed-backed mocksrv
make mock.down           # tear down
make mock.smoke          # reset → capture → up → curl every vhost (E2E)
make mock.reset          # wipe seeds + manifest
make mock.capture        # ⚠️ hits the real internet, rate-limited
make mock.verify         # offline integrity check
make mock.browser        # opt-in: run a real browser against the stack
make mock.sources        # list registered sources + robots policy
make mock.trust          # install dev CA into host trust store (sudo)
make mock.untrust        # remove it (sudo)
make mock.setup          # one-shot: ca-init → trust → hosts.install → up
make hosts.install       # adds .local entries to /etc/hosts (sudo)
make hosts.uninstall     # removes them
make hosts.status        # reports installed=True/False
make hosts.show          # dump current managed entries
make hosts.preview       # show what would be installed
```

All targets are **idempotent** and print a clear, single-line status.

## 🟦 Server binary, two modes

The Go server is repurposed:

```
server/cmd/api/       # Phase 9 — public REST surface
server/cmd/mocksrv/   # Phase 2 — mock-data backend behind nginx
server/internal/...   # shared config, db, redis, observability
```

Selecting at runtime:

```bash
SERVER_MODE=api      ./server      # production-style
SERVER_MODE=mocksrv  ./server      # dev mock backend
```

`docker-compose.yml` runs them as two named services pointing at the same image.

> **Pivot v3 rename (in flight, ROADMAP §3.5).** During Phase R5 the
> `mocksrv` binary is renamed to `mock` (`server/cmd/mock/`) and the
> mode toggle becomes `SERVER_MODE=mock`. The legacy `mocksrv` name
> is retained as a one-release alias before being dropped. Until
> Phase R5 lands, every reference above is current.
