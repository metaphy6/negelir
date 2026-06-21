"""Phase 10 §10.21.2 — Lexicon old-generation eviction contract tests.

Verifies that LexiconStore:
  * Tracks generations via monotonic counter
  * Retains at most max_old_generations retired snapshots
  * Evicts oldest generations when deque is full
  * Logs (old_gen, new_gen, in_flight_count) at swap time

Per AGENTS.md Rule 10: new surface → happy path + adversarial tests.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from nlp.lexicon_loader import LexiconStore

# ── Fixtures ──────────────────────────────────────────────────────────────

_VALID_META = (
    "_meta:\n"
    "  schema_version: 1\n"
    "  lexicon_version: 1.0.0\n"
    '  generated_at_utc: "2026-05-27T00:00:00Z"\n'
    "  generator: nlp.lexicon-build\n"
)

_TEAMS_YAML_V1 = (
    _VALID_META
    + "entries:\n"
    + "  - canonical_id: tr_super_lig_galatasaray\n"
    + "    names:\n"
    + "      - Galatasaray\n"
    + "    aliases:\n"
    + "      - gs\n"
)

_TEAMS_YAML_V2 = (
    _VALID_META
    + "entries:\n"
    + "  - canonical_id: tr_super_lig_galatasaray\n"
    + "    names:\n"
    + "      - Galatasaray\n"
    + "    aliases:\n"
    + "      - gs\n"
    + "  - canonical_id: tr_super_lig_fenerbahce\n"
    + "    names:\n"
    + "      - Fenerbahçe\n"
    + "    aliases:\n"
    + "      - fb\n"
)

_TEAMS_YAML_V3 = (
    _VALID_META
    + "entries:\n"
    + "  - canonical_id: tr_super_lig_galatasaray\n"
    + "    names:\n"
    + "      - Galatasaray\n"
    + "    aliases:\n"
    + "      - gs\n"
    + "  - canonical_id: tr_super_lig_fenerbahce\n"
    + "    names:\n"
    + "      - Fenerbahçe\n"
    + "    aliases:\n"
    + "      - fb\n"
    + "  - canonical_id: tr_super_lig_besiktas\n"
    + "    names:\n"
    + "      - Beşiktaş\n"
    + "    aliases:\n"
    + "      - bjk\n"
)

_TEAMS_YAML_V4 = (
    _VALID_META
    + "entries:\n"
    + "  - canonical_id: tr_super_lig_galatasaray\n"
    + "    names:\n"
    + "      - Galatasaray\n"
    + "    aliases:\n"
    + "      - gs\n"
    + "  - canonical_id: tr_super_lig_fenerbahce\n"
    + "    names:\n"
    + "      - Fenerbahçe\n"
    + "    aliases:\n"
    + "      - fb\n"
    + "  - canonical_id: tr_super_lig_besiktas\n"
    + "    names:\n"
    + "      - Beşiktaş\n"
    + "    aliases:\n"
    + "      - bjk\n"
    + "  - canonical_id: tr_super_lig_trabzonspor\n"
    + "    names:\n"
    + "      - Trabzonspor\n"
    + "    aliases:\n"
    + "      - ts\n"
)

_MARKETS_YAML = (
    _VALID_META
    + "entries:\n"
    + "  - canonical_id: ms\n"
    + "    names:\n"
    + "      - Maç Sonucu\n"
    + "    aliases:\n"
    + "      - 1x2\n"
)

_DIALECTS_YAML = (
    _VALID_META
    + "entries:\n"
    + "  - token: kl\n"
    + "    canonical_tokens:\n"
    + "      - kilit\n"
    + "      - maç\n"
)

_ENTITIES_NEG_YAML = (
    _VALID_META
    + "entries:\n"
    + "  - token: fener\n"
    + "    requires_co_tokens:\n"
    + "      - bahce\n"
)


def _write_minimal_lexicon_dir(
    tmp_path: Path,
    *,
    override: dict[str, str] | None = None,
) -> Path:
    """Write a minimal but valid set of lexicon files to *tmp_path*."""
    overrides = override or {}
    defaults: dict[str, str] = {
        "teams.tr.yaml": _TEAMS_YAML_V1,
        "players.tr.yaml": _TEAMS_YAML_V1,
        "leagues.tr.yaml": _TEAMS_YAML_V1,
        "competitions.tr.yaml": _TEAMS_YAML_V1,
        "markets.tr.yaml": _MARKETS_YAML,
        "dialects.tr.yaml": _DIALECTS_YAML,
        "entities_negative.tr.yaml": _ENTITIES_NEG_YAML,
    }
    for fname, content in defaults.items():
        (tmp_path / fname).write_text(overrides.get(fname, content), encoding="utf-8")
    return tmp_path


def _monotonic_factory(start: float = 0.0):
    """Return a controllable fake clock and an advance callable."""
    t = [start]

    def clock() -> float:
        return t[0]

    def advance(by: float) -> None:
        t[0] += by

    return clock, advance


# ── Tests ─────────────────────────────────────────────────────────────────


class TestLexiconOldGenerationEviction:
    """§10.21.2 Old-generation eviction contract."""

    def test_lexicon_old_gen_evicted_after_inflight_drain(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """After max_old_generations swaps, oldest generation is evicted."""
        caplog.set_level(logging.DEBUG, logger="nlp.lexicon_loader")
        clock, advance = _monotonic_factory()
        lexdir = _write_minimal_lexicon_dir(tmp_path)
        
        store = LexiconStore(
            lexdir, reload_s=5, max_old_generations=2, clock_mono=clock
        )

        # Initial load (generation 0 → 1).
        alerts = store.maybe_reload()
        assert alerts == []
        assert store.is_loaded
        assert len(caplog.records) == 1
        assert "old_gen=0, new_gen=1, in_flight_count=0" in caplog.text

        # Swap 1: v1 → v2 (generation 1 → 2).
        caplog.clear()
        (lexdir / "teams.tr.yaml").write_text(_TEAMS_YAML_V2, encoding="utf-8")
        advance(6.0)
        alerts = store.maybe_reload()
        assert alerts == []
        assert "old_gen=1, new_gen=2, in_flight_count=1" in caplog.text

        # Swap 2: v2 → v3 (generation 2 → 3).
        caplog.clear()
        (lexdir / "teams.tr.yaml").write_text(_TEAMS_YAML_V3, encoding="utf-8")
        advance(6.0)
        alerts = store.maybe_reload()
        assert alerts == []
        assert "old_gen=2, new_gen=3, in_flight_count=2" in caplog.text

        # Swap 3: v3 → v4 (generation 3 → 4).
        # Deque is full (maxlen=2); oldest (gen 1) should be auto-evicted.
        caplog.clear()
        (lexdir / "teams.tr.yaml").write_text(_TEAMS_YAML_V4, encoding="utf-8")
        advance(6.0)
        alerts = store.maybe_reload()
        assert alerts == []
        # After this swap, in_flight_count should still be 2 (deque maxlen).
        assert "old_gen=3, new_gen=4, in_flight_count=2" in caplog.text

    def test_lexicon_generation_counter_increments(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Generation counter increments on each swap."""
        caplog.set_level(logging.DEBUG, logger="nlp.lexicon_loader")
        clock, advance = _monotonic_factory()
        lexdir = _write_minimal_lexicon_dir(tmp_path)
        store = LexiconStore(lexdir, reload_s=5, clock_mono=clock)

        store.maybe_reload()
        assert "old_gen=0, new_gen=1" in caplog.text

        caplog.clear()
        (lexdir / "teams.tr.yaml").write_text(_TEAMS_YAML_V2, encoding="utf-8")
        advance(6.0)
        store.maybe_reload()
        assert "old_gen=1, new_gen=2" in caplog.text

        caplog.clear()
        (lexdir / "teams.tr.yaml").write_text(_TEAMS_YAML_V3, encoding="utf-8")
        advance(6.0)
        store.maybe_reload()
        assert "old_gen=2, new_gen=3" in caplog.text

    def test_lexicon_max_old_generations_zero_disables_retention(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When max_old_generations=0, no old generations are retained."""
        caplog.set_level(logging.DEBUG, logger="nlp.lexicon_loader")
        clock, advance = _monotonic_factory()
        lexdir = _write_minimal_lexicon_dir(tmp_path)
        store = LexiconStore(
            lexdir, reload_s=5, max_old_generations=0, clock_mono=clock
        )

        store.maybe_reload()
        assert "in_flight_count=0" in caplog.text

        caplog.clear()
        (lexdir / "teams.tr.yaml").write_text(_TEAMS_YAML_V2, encoding="utf-8")
        advance(6.0)
        store.maybe_reload()
        assert "in_flight_count=0" in caplog.text

        caplog.clear()
        (lexdir / "teams.tr.yaml").write_text(_TEAMS_YAML_V3, encoding="utf-8")
        advance(6.0)
        store.maybe_reload()
        assert "in_flight_count=0" in caplog.text

    def test_lexicon_swap_logs_in_flight_count(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Log captures (old_gen, new_gen, in_flight_count) at swap time."""
        caplog.set_level(logging.DEBUG, logger="nlp.lexicon_loader")
        clock, advance = _monotonic_factory()
        lexdir = _write_minimal_lexicon_dir(tmp_path)
        store = LexiconStore(
            lexdir, reload_s=5, max_old_generations=3, clock_mono=clock
        )

        store.maybe_reload()
        assert "old_gen=0, new_gen=1, in_flight_count=0" in caplog.text

        caplog.clear()
        (lexdir / "teams.tr.yaml").write_text(_TEAMS_YAML_V2, encoding="utf-8")
        advance(6.0)
        store.maybe_reload()
        assert "old_gen=1, new_gen=2, in_flight_count=1" in caplog.text

        caplog.clear()
        (lexdir / "teams.tr.yaml").write_text(_TEAMS_YAML_V3, encoding="utf-8")
        advance(6.0)
        store.maybe_reload()
        assert "old_gen=2, new_gen=3, in_flight_count=2" in caplog.text

        caplog.clear()
        (lexdir / "teams.tr.yaml").write_text(_TEAMS_YAML_V4, encoding="utf-8")
        advance(6.0)
        store.maybe_reload()
        assert "old_gen=3, new_gen=4, in_flight_count=3" in caplog.text
