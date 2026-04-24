# 🚀 Setup Guide — Zero to Running Stack

> Companion to [`../planning/ROADMAP.md`](../planning/ROADMAP.md).
> Targets a Linux dev host with Docker + Docker Compose v2.
> Windows / WSL2 should work; macOS works for CPU-only paths.

## 0. Prerequisites

- Docker Engine 24+ with Compose v2 (`docker compose version`).
- `make` (any GNU make).
- ~10 GB free disk for images + seed corpus.
- (Optional) NVIDIA GPU + recent driver + `nvidia-container-toolkit` for GPU training.

## 1. Clone and bootstrap env

```bash
git clone <repo>
cd negelir
make env             # creates xops/env/.env from xops/env/.env.example
```

> Edit `.env` if you need to override anything. **Never commit `.env`.**

## 2. Bring up the mock-data stack (one-time per machine)

```bash
make mock.ca-init    # generate self-signed root CA + leaf certs
make hosts.install   # adds .local hostnames to /etc/hosts (sudo)
make mock.trust      # install dev CA into host trust store (sudo, opt-in)
make mock.up         # nginx-mock + mocksrv + seeded postgres
make mock.verify     # offline integrity check
make mock.smoke      # end-to-end: reset → capture (DEPTH=1) → up → curl every vhost
```

> 🌐 You now have a fully local "fake internet". The scrapers will hit it instead of the real sites.
> One-shot equivalent: `make mock.setup` runs ca-init → trust → hosts.install → up.

## 3. Bring up the application stack

```bash
make up              # postgres + redis + go api + ai container (default profile)
make health          # report container health
make test            # full test suite (Python + Go) — proxy for the future smoke target
```

> The future Phase 12 `make smoke` (HTTP happy-path) target lands with the
> Go API in Phase 9; until then `make test` is the canonical green-bar.
> Phase R5 (ROADMAP §3.5) introduces explicit compose profiles
> (`make up PROFILES=core,mock,datasource,swarm`); today `make up`
> brings up the default profile.

## 4. Common commands

```bash
make logs                   # tail everything
make watch.run              # one-shot source-watcher pass (Phase 2.8)
make watch.history SOURCE=mackolik.local
make watch.sources          # list registered sources + last-seen state
make ai.shell               # shell into the AI image
make test.ai                # Python tests only
make test.integration       # cross-component integration tests
make backtest WEEKS=3       # offline historical backtest
make track.list             # current phase status
make version.show           # project + per-component versions
```

> Phase 3 (swarm bus + supervisor) introduces a `swarmctl` CLI for
> live agent inspection (`swarmctl ps`, `swarmctl tail`). It does not
> exist yet — see ROADMAP §3 for the spec.

## 5. GPU / NPU

```bash
NEGELIR_DEVICE=cuda make up    # force CUDA
NEGELIR_DEVICE=npu  make up    # force OpenVINO NPU
NEGELIR_DEVICE=cpu  make up    # force CPU
NEGELIR_DEVICE=auto make up    # default; picks the best available
```

## 6. Tear down

```bash
make down                # stop containers, keep volumes
make mock.down           # stop the mock-data stack
make mock.untrust        # remove dev CA from host trust store (sudo)
make hosts.uninstall     # remove .local hostnames
make clean               # remove containers + local images
make clean.all           # also drop volumes (⚠️ wipes data)
```

## 7. Refresh seed corpus (rare, deliberate)

```bash
make mock.capture        # ⚠️ hits the real internet, rate-limited
make mock.capture FORCE=1 DEPTH=1   # full refetch + follow same-host links
git diff infra/mock/seeds/manifest.json  # review what changed
```

> Captures land as a separate commit, ideally reviewed for shape changes before merging.
> AGENTS.md §2 rule 9 allows AI assistants to invoke `make mock.capture`;
> only `git` itself stays human-only.

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `x509: certificate signed by unknown authority` inside an agent | CA not mounted into image | rebuild the affected image (`docker compose build <svc>`); the entrypoint re-trusts on start |
| `x509: …` from the host browser / curl | dev CA not trusted by the host | `make mock.trust` (or skip and use containers) |
| `mackolik.local: name or service not known` | hosts file not edited | `make hosts.install` (status: `make hosts.status`) |
| Predictor OOM on training | XGBoost on GPU + tiny VRAM | set `NEGELIR_DEVICE=cpu` for training only |
| `make test` fails on auth | no seeded user | `make db.reset && make db.seed` |
| Mock seed integrity check fails | stale or corrupt capture | `make mock.reset && make mock.capture` |
| Agent missing after `make up` | image not built / crashed | `make logs` then `docker compose up -d --build <svc>` |
