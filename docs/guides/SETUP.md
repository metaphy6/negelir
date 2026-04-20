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
make mock-ca-init    # generate self-signed root CA
make mock-certs      # generate per-domain leaf certs
make hosts-install   # adds .local hostnames to /etc/hosts (sudo)
make mock-up         # nginx-mock + mocksrv + seeded postgres
make mock-verify     # offline integrity check
```

> 🌐 You now have a fully local "fake internet". The scrapers will hit it instead of the real sites.

## 3. Bring up the swarm

```bash
make up-dev          # postgres + redis + go api + swarm agents (compose dev profile)
make smoke           # end-to-end happy path
```

If `make smoke` is green you're running.

## 4. Common commands

```bash
make logs                   # tail everything
make swarmctl-ps            # list agents + heartbeats
make swarmctl-tail TOPIC=predict.final
make ai.shell               # shell into the AI image
make test                   # full test suite
make backtest WEEKS=3       # offline historical backtest
```

## 5. GPU / NPU

```bash
NEGELIR_DEVICE=cuda make up-dev    # force CUDA
NEGELIR_DEVICE=npu  make up-dev    # force OpenVINO NPU
NEGELIR_DEVICE=cpu  make up-dev    # force CPU
NEGELIR_DEVICE=auto make up-dev    # default; picks the best available
```

## 6. Tear down

```bash
make down                # stop containers, keep volumes
make hosts-uninstall     # remove .local hostnames
make clean               # remove containers + local images
make clean.all           # also drop volumes (⚠️ wipes data)
```

## 7. Refresh seed corpus (rare, deliberate)

```bash
make mock-capture        # ⚠️ hits the real internet, rate-limited
git diff infra/mock/seeds/manifest.json  # review what changed
```

> Captures land as a separate commit, ideally reviewed for shape changes before merging.

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `x509: certificate signed by unknown authority` inside an agent | CA not mounted into image | `make mock-ca-trust` rebuilds & re-trusts |
| `mackolik.local: name or service not known` | hosts file not edited | `make hosts-install` |
| Predictor OOM on training | XGBoost on GPU + tiny VRAM | set `NEGELIR_DEVICE=cpu` for training only |
| `make smoke` fails on auth | no seeded user | `make seed-dev-user` |
| Agent missing from `swarmctl ps` | image not built / crashed | `make logs` then `docker compose up -d --build <svc>` |
