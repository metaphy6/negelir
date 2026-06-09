# Phase 13.25 — Source supply-chain trust

> Extracted from `docs/planning/ROADMAP.md` §13.25
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.25 Source supply-chain trust

> Retires assumption §13.0 #26.

- [x] **Per-source TLS pin + CA bundle pin.** `xops/mock/sources.py` row carries `tls_spki_sha256` (subject-public-key-info pin) + `tls_root_ca_sha256`; scrapers in non-mock profile refuse handshake on mismatch (proof test `test_source_tls_pin_mismatch_refused.py`).
- [x] **Content-type allow-list.** Per-source `accept_content_types` enum; an HTML-only source returning `application/javascript` is refused as drift (Phase 17 patcher artifact).
- [x] **ToS snapshot hash.** Per-source `tos_sha256` snapshot of the upstream Terms-of-Service; CI fails when the source's published ToS hash drifts (manual ack via tracker row required to update).
- [x] **Pin-rotation drill.** `make sources.pin.rotate SOURCE=<s>` exercises the new-pin / old-pin overlap window (`cfg.source_pin_rotation_overlap_h`, default 72); proof test asserts no scraper request fails during the overlap.
- [x] **Robots.txt fetch + parse cache.** `xops/mock/robots.py` re-fetches `robots.txt` at `cfg.robots_recheck_h` (default 24); a newly disallowed path quarantines the relevant scraper via Phase 7 sec.input.
