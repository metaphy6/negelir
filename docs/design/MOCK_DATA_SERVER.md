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
├── gen_ca.py                 # cross-platform (no bash)
├── gen_cert.py
├── install_hosts.py          # idempotent /etc/hosts editor
├── uninstall_hosts.py
├── capture.py                # one-time real-source capture (Phase 2.4)
└── verify.py                 # offline integrity check (Phase 2.5)
```

## 🔑 TLS

- `make mock-ca-init` runs `xops/mock/gen_ca.py` (only if `ca.crt` is missing).
- `make mock-certs` regenerates leaves when the domain list in `infra/mock/domains.txt` changes (driver: `xops/mock/gen_cert.py`).
- The CA is **mounted** into:
  - `nginx-mock` (terminates TLS).
  - Every Python image: appended to `/etc/ssl/certs/ca-certificates.crt` via `update-ca-certificates` in the entrypoint.
  - Every Go image: same. (Go reads system roots.)
- **Nothing is installed on the host.** Browsers / curl from the host will not trust the CA — by design. Use containers.

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
NEGELIR_SCRAPE_PROFILE=real     # opt-in for "make mock-capture"
```

`LeagueConfig.scrape_endpoints` then composes the right base URL:

```python
base = "https://mackolik.local" if profile == "mock" else "https://www.mackolik.com"
```

## 📦 Seed corpus

- One-time capture: `make mock-capture` runs `xops/mock/capture.py` against the **real** sources (rate-limited, robots-respecting, user-agent declared).
- Each capture writes: the response body verbatim, status code, headers, and an entry in `manifest.json` with sha256.
- Captures are committed (small) or LFS'd (large).
- `make mock-verify` re-hashes everything and refuses to bring up nginx-mock if a seed is corrupt.

## 🧪 Integrity tests

`ai/tests/test_mock_parity.py`:

- For every URL in `manifest.json`, fetch it from `nginx-mock` inside the test container and assert byte-identical body + matching status.
- For each scraper / source, run a **shape test**: parse the seed and assert the resulting normalized record matches the schema.

## 🧰 Makefile UX (final)

```
make mock-ca-init        # one-time: generate root CA
make mock-certs          # generate leaves from domains.txt
make mock-up             # bring up nginx-mock + seed-backed mocksrv
make mock-down           # tear down
make mock-capture        # ⚠️ hits the real internet
make mock-verify         # offline integrity check
make hosts-install       # adds .local entries to /etc/hosts (sudo)
make hosts-uninstall     # removes them
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
