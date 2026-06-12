# Phase 16.32 — Compression strategy & per-plane dictionaries (NEW; ledger #36)

> Extracted from `docs/planning/ROADMAP.md` §16.32
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 16.32 Compression strategy & per-plane dictionaries (NEW; ledger #36)

- [x] **Per-plane codec/level/dict config** (already wired in §16.2). Defaults: `score=zstd:9`, `lineup=zstd:9`, `schedule=zstd:6` (small payloads), `editorial=zstd:12` (high-text), `market=zstd:9 + per-plane trained dict`, `reference=zstd:6`.
- [x] **Dictionary training tool** `make feeds.dict.train PLANE=market WINDOW=7d` writes `xops/feeds/dicts/<plane>.zdict` (and a `.sha256`); training happens on a sample of recent NDJSON; output is reproducible (same input ⇒ same dict bytes within `zstd` library version).
- [x] **Dictionary rotation** `make feeds.dict.rotate PLANE=market` increments the dict generation; manifest carries `compression: {codec, level, dict_sha256?, dict_generation?}`; old generations remain readable until the corresponding files age out.
- [x] **Codec change is non-breaking on read.** A reader from generation N+1 must read generation-N files; lint enforces.
- [x] **Compression-ratio targets** per the load-test corpus (binding for Phase 16 sign-off): `market` ≥ 4× ratio with dict, `editorial` ≥ 6× ratio without dict, `score` ≥ 3× ratio.
- [x] Proof tests: `test_per_plane_codec_round_trip.py`, `test_dict_compression_meets_ratio_target.py`, `test_codec_change_does_not_break_old_files.py`, `test_dict_training_reproducible.py`, `test_dict_rotation_atomic.py`.
