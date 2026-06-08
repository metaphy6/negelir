# Phase 11.44 — Compute-side `/healthz` & K8s probe contract (binding for Phase 9 + Phase 14)

> Extracted from `docs/planning/ROADMAP.md` §11.44
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.44 Compute-side `/healthz` & K8s probe contract (binding for Phase 9 + Phase 14)

> **Why this exists.** Phase 9's API does its own `/healthz`; the
> compute side needs a separate, structured readiness contract so
> K8s does not send live traffic to a pod that parses `nvidia-smi`
> but has not yet warmed an inference. Wrong-assumption #15 retired.

- [x] **Three-probe contract.** Every agent that owns a model exposes:
  - `/livez` — process is alive and the GIL is unstuck (≤ 10 ms response, never blocked on the model). Failure → K8s restart.
  - `/readyz` — every device the agent claimed in `device.json` has executed at least one successful **end-to-end** inference on a frozen warmup input from `ai/tests/fixtures/warmup/`, **and** every bundle declared in the manifest has been verified + loaded + cached + warmed. Failure → K8s removes from Service endpoints; existing connections drain.
  - `/startupz` — distinct from `/readyz` so K8s `startupProbe` can use a longer threshold for cold bundle pull / engine compile (`cfg.compute_startup_probe_max_s` default 600 s) without falsely failing `/livez`.
- [x] **Structured response.** All three return JSON with `{status, devices: [{uuid, claimed, ready, last_warmup_ts, last_warmup_latency_ms}], bundles: [{sha256, loaded, warmed}], reasons_not_ready: [{kind, detail}]}`. Status is the single ground truth; the body lets ops debug without `kubectl exec`.
- [x] **Probe is the truth source for traffic.** §11.18 driver upgrade, §11.27 idle wake, §11.31 fallback exhaustion, §11.42 cluster drain all flip `/readyz` to `false` *before* refusing requests so K8s drains the endpoint cleanly. Conversely, no agent self-promotes to `ready` while the §11.42 cluster arbiter has it in `region_drain`.
- [x] **No secrets / no inputs.** Probe responses include device UUIDs and bundle SHAs but **no inputs / outputs / tokens / tenant IDs** — the probe is unauthenticated by K8s convention and must remain leak-free. Lint refuses an extension that adds a sensitive field.
- [x] **Test hooks.** `make compute.probe.simulate KIND=<bundle_pull_in_progress|engine_compile|drain|cluster_drain|warmup_fail>` injects each not-ready reason and asserts the JSON shape; chaos-tested in Phase 12.
