# Phase 9.5 — Wire-authority additions, schemas, envelope discipline

> Extracted from `docs/planning/ROADMAP.md` §9.5
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 9.5 Wire-authority additions, schemas, envelope discipline

- [ ] **`api.request.v1` schema** (`ai/swarm/sdk/schemas/api.request.v1.json`): `{request_id, user_id?, anon_subject_key, route, method, status_anticipated:null, accepted_at, sec_gate_ms, auth_ms}`. `additionalProperties:false`. Per §8.16.9 dual-emit doctrine, when a Phase 7 quarantine fires for the same request, the matching `sec.alert.v1` carries the `event_correlation_id = request_id`.
- [ ] **`api.response.v1` schema** (`ai/swarm/sdk/schemas/api.response.v1.json`): `{request_id, status, latency_ms, bytes_out, cache, degraded, prediction_id?, calibration_version?, error_code?}`. **Bytes_out is computed on the actual response writer** (gzipped if applicable) so the audit row is truthful.
- [ ] **`predict.cancel.v1` schema** (new): `{request_id, cancelled_at, reason ∈ {client_disconnect, deadline_exceeded, operator_kill}}`. Producer set bounded to `api.gateway.v1`.
- [ ] **Envelope discipline.** API uses the existing Phase 3 envelope (`message_id`, `topic`, `schema_version`, `produced_at`, `producer`, `kind_schema_version`); `client_id` payload field carries the user_id when present, else `anon:<sha256(subject_key)>[:12]`. **Never** put raw IP in payload (§7.6 `SubjectKey` masked form only). Boundary test scans for IP-shaped strings in published payloads.
- [ ] **Trace propagation.** API mints W3C `traceparent` if absent; `X-Request-ID` is its alias for client-side echo. The trace_id rides the envelope per §8.15.6 and threads through `predict.request → vote → final → approved → api.response.v1`.
