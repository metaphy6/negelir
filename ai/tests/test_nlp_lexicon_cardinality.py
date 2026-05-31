"""Phase 10 §10.2 — Cardinality cap tests for LexiconStore.

Verifies:
  * Over-cap file -> dictionary_overflow warn alert + refuse load (keep old).
  * Exactly-at-cap file -> loads fine (no alert).
  * Cap=0 treated as cap=1 (max(1,...) guard).
  * Alert kind/severity match spec.

Per AGENTS.md Rule 10: new surface -> happy path + adversarial tests.
"""
from __future__ import annotations

import time as _time
import inspect
from pathlib import Path

from nlp.lexicon_loader import LexiconStore

_VALID_META = (
    "_meta:\n"
    "  schema_version: 1\n"
    "  lexicon_version: 1.0.0\n"
    '  generated_at_utc: "2026-05-27T00:00:00Z"\n'
    "  generator: nlp.lexicon-build\n"
)


def _make_teams_yaml(n_entries: int) -> str:
    """Return a teams.tr.yaml with *n_entries* valid entries."""
    lines = [_VALID_META, "entries:"]
    for i in range(n_entries):
        lines.extend([
            f"  - canonical_id: team_{i}",
            "    names:",
            f"      - Team {i}",
            "    aliases:",
            f"      - t{i}",
        ])
    return "\n".join(lines) + "\n"


def _make_markets_yaml() -> str:
    return (
        _VALID_META
        + "entries:\n"
        + "  - canonical_id: ms\n"
        + "    names:\n"
        + "      - Mac Sonucu\n"
        + "    aliases:\n"
        + "      - 1x2\n"
    )


def _make_dialects_yaml() -> str:
    return (
        _VALID_META
        + "entries:\n"
        + "  - token: kl\n"
        + "    canonical_tokens:\n"
        + "      - kilit\n"
    )


def _make_entities_neg_yaml() -> str:
    return (
        _VALID_META
        + "entries:\n"
        + "  - token: fener\n"
        + "    requires_co_tokens:\n"
        + "      - bahce\n"
    )


def _write_lexicon_dir(tmp_path: Path, *, teams_content: str) -> Path:
    (tmp_path / "teams.tr.yaml").write_text(teams_content, encoding="utf-8")
    small = _make_teams_yaml(2)
    for fname in ("players.tr.yaml", "leagues.tr.yaml", "competitions.tr.yaml"):
        (tmp_path / fname).write_text(small, encoding="utf-8")
    (tmp_path / "markets.tr.yaml").write_text(_make_markets_yaml(), encoding="utf-8")
    (tmp_path / "dialects.tr.yaml").write_text(_make_dialects_yaml(), encoding="utf-8")
    (tmp_path / "entities_negative.tr.yaml").write_text(
        _make_entities_neg_yaml(), encoding="utf-8"
    )
    return tmp_path


# ── Happy path ────────────────────────────────────────────────────────────

class TestCardinalityCapHappy:
    def test_at_cap_loads_ok(self, tmp_path: Path) -> None:
        """File with exactly cap entries must load without any alert."""
        cap = 5
        lexdir = _write_lexicon_dir(tmp_path, teams_content=_make_teams_yaml(cap))
        store = LexiconStore(lexdir, max_entries_per_file=cap)
        alerts = store.maybe_reload()
        assert alerts == [], f"No alerts expected at cap; got {alerts}"
        assert store.is_loaded

    def test_below_cap_loads_ok(self, tmp_path: Path) -> None:
        lexdir = _write_lexicon_dir(tmp_path, teams_content=_make_teams_yaml(3))
        store = LexiconStore(lexdir, max_entries_per_file=10)
        assert store.maybe_reload() == []
        assert store.is_loaded

    def test_default_cap_is_50000(self) -> None:
        """Default must match cfg.nlp_lexicon_max_entries_per_file default."""
        sig = inspect.signature(LexiconStore.__init__)
        assert sig.parameters["max_entries_per_file"].default == 50000


# ── Adversarial ───────────────────────────────────────────────────────────

class TestCardinalityCapAdversarial:
    def test_over_cap_emits_dictionary_overflow_warn(self, tmp_path: Path) -> None:
        cap = 3
        lexdir = _write_lexicon_dir(tmp_path, teams_content=_make_teams_yaml(cap + 1))
        store = LexiconStore(lexdir, max_entries_per_file=cap)
        alerts = store.maybe_reload()
        assert len(alerts) == 1, f"Expected 1 alert; got {alerts}"
        assert alerts[0]["kind"] == "dictionary_overflow"
        assert alerts[0]["severity"] == "warn"

    def test_over_cap_refuses_load(self, tmp_path: Path) -> None:
        cap = 2
        lexdir = _write_lexicon_dir(tmp_path, teams_content=_make_teams_yaml(cap + 10))
        store = LexiconStore(lexdir, max_entries_per_file=cap)
        store.maybe_reload()
        assert not store.is_loaded

    def test_over_cap_preserves_previous_snapshot(self, tmp_path: Path) -> None:
        """After a good load, over-cap reload must keep old data intact."""
        cap = 5
        lexdir = _write_lexicon_dir(tmp_path, teams_content=_make_teams_yaml(2))
        store = LexiconStore(lexdir, max_entries_per_file=cap, reload_s=1)
        store.maybe_reload()
        assert store.is_loaded
        _, old_entries = store.get("teams.tr.yaml")
        assert len(old_entries) == 2

        (lexdir / "teams.tr.yaml").write_text(
            _make_teams_yaml(cap + 1), encoding="utf-8"
        )
        _time.sleep(1.1)  # exceed reload_s=1
        alerts = store.maybe_reload()

        assert len(alerts) == 1
        assert alerts[0]["kind"] == "dictionary_overflow"
        _, still_old = store.get("teams.tr.yaml")
        assert len(still_old) == 2, "Old snapshot must be preserved on over-cap"

    def test_cap_zero_clamped_to_one(self, tmp_path: Path) -> None:
        """cap=0 is clamped to 1; single-entry files exactly at cap=1 -> loads fine."""
        # Use 1-entry versions of all catalog files so none overflow cap=1.
        one_entry = _make_teams_yaml(1)
        lexdir = tmp_path
        for fname in ("teams.tr.yaml", "players.tr.yaml", "leagues.tr.yaml",
                      "competitions.tr.yaml"):
            (lexdir / fname).write_text(one_entry, encoding="utf-8")
        (lexdir / "markets.tr.yaml").write_text(_make_markets_yaml(), encoding="utf-8")
        (lexdir / "dialects.tr.yaml").write_text(_make_dialects_yaml(), encoding="utf-8")
        (lexdir / "entities_negative.tr.yaml").write_text(
            _make_entities_neg_yaml(), encoding="utf-8"
        )
        store = LexiconStore(lexdir, max_entries_per_file=0)
        assert store.maybe_reload() == []

    def test_alert_reason_contains_overflowing_filename(self, tmp_path: Path) -> None:
        cap = 2
        lexdir = _write_lexicon_dir(tmp_path, teams_content=_make_teams_yaml(cap + 5))
        store = LexiconStore(lexdir, max_entries_per_file=cap)
        alerts = store.maybe_reload()
        assert alerts
        assert "teams.tr.yaml" in alerts[0]["reason"]
