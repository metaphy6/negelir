# Phase 16.30 — OpenTelemetry tracing across emit/read (NEW; ledger #31)

> Extracted from `docs/planning/ROADMAP.md` §16.30
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 16.30 OpenTelemetry tracing across emit/read (NEW; ledger #31)

- [x] **Envelope `trace_context`** (W3C Trace Context `{traceparent, tracestate}`) is preserved end-to-end; producer SDK injects when missing.
- [x] **Writer span.** One span per `enqueue()` linked to the upstream traceparent via `links: [parent_traceparent]`; span attributes include `plane, source, idempotency_key, payload_bytes`.
- [x] **Reader span.** One span per `stream()`/`snapshot()`/`joined_snapshot()`/`time_travel()` call with `plane, as_of, principal, rows_yielded, bytes_decoded, cache_hit`.
- [x] **OTLP exporter** hook (Phase 14 wire-up); spec landed here. `cfg.feeds_otel_enabled` (default `true` in dev/CI, env-tunable in prod), `cfg.feeds_otel_endpoint` (default empty → spans dropped silently when no endpoint).
- [x] **Sampling.** `cfg.feeds_otel_sample_rate` (default 0.05). Errors and circuit-breaker events always sample (`always_on` policy on `proof.flag`/`sec.alert` paths).
- [x] Proof tests: `test_traceparent_round_trip.py`, `test_writer_continues_upstream_span.py`, `test_reader_emits_span_per_call.py`, `test_otel_sampling_respected.py`, `test_error_paths_always_sampled.py`.
