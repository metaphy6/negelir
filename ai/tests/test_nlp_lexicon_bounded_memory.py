"""Phase 10 §10.2 — Bounded memory tests for LexiconStore.

Verifies:
  * AliasHit is a NamedTuple with the correct three fields (immutable).
  * _build_alias_index collects names + aliases + token fields.
  * LexiconStore.get_alias_index returns populated index after load.
  * RSS budget exceeded → dictionary_overflow error alert + refuse swap.
  * RSS budget ok → swap proceeds normally with no alert.
  * Previous snapshot preserved on RSS overflow.
  * max_rss_mb=0 disables the RSS check.
  * Default max_rss_mb=128.

Per AGENTS.md Rule 10: new surface → happy path + adversarial tests.
"""
from __future__ import annotations

import inspect
import time as _time
from pathlib import Path

import pytest

from nlp.lexicon_loader import AliasHit, LexiconStore, _build_alias_index

# ── Shared YAML fixtures ───────────────────────────────────────────────────

_VALID_META = (
    "_meta:\n"
    "  schema_version: 1\n"
    "  lexicon_version: 1.0.0\n"
    '  generated_at_utc: "2026-05-27T00:00:00Z"\n'
    "  generator: nlp.lexicon-build\n"
)


def _make_teams_yaml(entries_extra: str = "") -> str:
    base = (
        _VALID_META
        + "entries:\n"
        + "  - canonical_id: gs\n"
        + "    names:\n"
        + "      - Galatasaray\n"
        + "    aliases:\n"
        + "      - cimbom\n"
        + "      - aslanlar\n"
    )
    return base + entries_extra


def _make_small_catalog_yaml() -> str:
    return (
        _VALID_META
        + "entries:\n"
        + "  - canonical_id: x\n"
        + "    names:\n"
        + "      - X\n"
        + "    aliases:\n"
        + "      - x1\n"
    )


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


def _write_lexicon_dir(tmp_path: Path, *, teams_content: str | None = None) -> Path:
    (tmp_path / "teams.tr.yaml").write_text(
        teams_content if teams_content is not None else _make_teams_yaml(),
        encoding="utf-8",
    )
    small = _make_small_catalog_yaml()
    for fname in ("players.tr.yaml", "leagues.tr.yaml", "competitions.tr.yaml"):
        (tmp_path / fname).write_text(small, encoding="utf-8")
    (tmp_path / "markets.tr.yaml").write_text(_make_markets_yaml(), encoding="utf-8")
    (tmp_path / "dialects.tr.yaml").write_text(_make_dialects_yaml(), encoding="utf-8")
    (tmp_path / "entities_negative.tr.yaml").write_text(
        _make_entities_neg_yaml(), encoding="utf-8"
    )
    return tmp_path


# ── AliasHit type ──────────────────────────────────────────────────────────

class TestAliasHitType:
    def test_is_named_tuple_with_correct_fields(self) -> None:
        hit = AliasHit(canonical_id="gs", kind="team", lexicon_version="1.0.0")
        assert isinstance(hit, tuple)
        assert hit.canonical_id == "gs"
        assert hit.kind == "team"
        assert hit.lexicon_version == "1.0.0"

    def test_field_names(self) -> None:
        assert AliasHit._fields == ("canonical_id", "kind", "lexicon_version")

    def test_is_immutable(self) -> None:
        hit = AliasHit(canonical_id="gs", kind="team", lexicon_version="1.0.0")
        with pytest.raises(AttributeError):
            hit.canonical_id = "fb"  # type: ignore[misc]

    def test_is_hashable(self) -> None:
        """AliasHit must be hashable so it can be stored in sets / dict values."""
        hit = AliasHit(canonical_id="gs", kind="team", lexicon_version="1.0.0")
        assert hash(hit) is not None
        s = {hit}
        assert hit in s


# ── _build_alias_index helper ─────────────────────────────────────────────

class TestBuildAliasIndex:
    def test_collects_names_and_aliases(self) -> None:
        entries = [
            {
                "canonical_id": "gs",
                "names": ["Galatasaray"],
                "aliases": ["cimbom", "aslanlar"],
            }
        ]
        index = _build_alias_index(entries, "1.0.0", "team")
        assert "Galatasaray" in index
        assert "cimbom" in index
        assert "aslanlar" in index
        hit = index["cimbom"]
        assert hit.canonical_id == "gs"
        assert hit.kind == "team"
        assert hit.lexicon_version == "1.0.0"

    def test_empty_entries_returns_empty_dict(self) -> None:
        assert _build_alias_index([], "1.0.0", "team") == {}

    def test_dialect_token_included(self) -> None:
        entries = [{"token": "kl", "canonical_tokens": ["kilit"]}]
        index = _build_alias_index(entries, "1.0.0", "dialect")
        assert "kl" in index
        hit = index["kl"]
        assert hit.kind == "dialect"
        assert hit.canonical_id == ""

    def test_skips_non_dict_entries(self) -> None:
        entries = [None, "bad", {"canonical_id": "gs", "names": ["GS"], "aliases": []}]  # type: ignore[list-item]
        index = _build_alias_index(entries, "1.0.0", "team")  # type: ignore[arg-type]
        assert "GS" in index
        assert len(index) == 1

    def test_empty_and_nonstring_aliases_skipped(self) -> None:
        entries = [
            {"canonical_id": "gs", "names": ["", None, 123, "Real"], "aliases": []}  # type: ignore[list-item]
        ]
        index = _build_alias_index(entries, "1.0.0", "team")  # type: ignore[arg-type]
        assert "Real" in index
        assert "" not in index
        assert None not in index  # type: ignore[operator]

    def test_multiple_entries_all_indexed(self) -> None:
        entries = [
            {"canonical_id": "gs", "names": ["Galatasaray"], "aliases": ["cimbom"]},
            {"canonical_id": "fb", "names": ["Fenerbahce"], "aliases": ["sari-lacivert"]},
        ]
        index = _build_alias_index(entries, "1.0.0", "team")
        assert index["Galatasaray"].canonical_id == "gs"
        assert index["Fenerbahce"].canonical_id == "fb"
        assert index["sari-lacivert"].canonical_id == "fb"


# ── get_alias_index integration ───────────────────────────────────────────

class TestGetAliasIndex:
    def test_alias_index_available_after_load(self, tmp_path: Path) -> None:
        lexdir = _write_lexicon_dir(tmp_path)
        store = LexiconStore(lexdir, max_rss_mb=0)
        store.maybe_reload()
        index = store.get_alias_index("teams.tr.yaml")
        assert index is not None
        assert "Galatasaray" in index
        assert "cimbom" in index
        hit = index["cimbom"]
        assert hit.canonical_id == "gs"
        assert hit.kind == "team"

    def test_dialect_kind_correct(self, tmp_path: Path) -> None:
        lexdir = _write_lexicon_dir(tmp_path)
        store = LexiconStore(lexdir, max_rss_mb=0)
        store.maybe_reload()
        index = store.get_alias_index("dialects.tr.yaml")
        assert index is not None
        assert "kl" in index
        assert index["kl"].kind == "dialect"

    def test_market_kind_correct(self, tmp_path: Path) -> None:
        lexdir = _write_lexicon_dir(tmp_path)
        store = LexiconStore(lexdir, max_rss_mb=0)
        store.maybe_reload()
        index = store.get_alias_index("markets.tr.yaml")
        assert index is not None
        assert "Mac Sonucu" in index
        assert index["Mac Sonucu"].kind == "market"

    def test_not_loaded_returns_none(self, tmp_path: Path) -> None:
        store = LexiconStore(tmp_path, max_rss_mb=0)
        assert store.get_alias_index("teams.tr.yaml") is None


# ── RSS budget ─────────────────────────────────────────────────────────────

class TestRssBudget:
    @staticmethod
    def _low_rss() -> int:
        return 10 * 1024  # 10 MB — well within 128 MB

    @staticmethod
    def _high_rss() -> int:
        return 200 * 1024  # 200 MB — over any sensible cap

    def test_rss_ok_loads_and_no_alert(self, tmp_path: Path) -> None:
        lexdir = _write_lexicon_dir(tmp_path)
        store = LexiconStore(lexdir, max_rss_mb=128, rss_kb_fn=self._low_rss)
        alerts = store.maybe_reload()
        assert alerts == []
        assert store.is_loaded

    def test_rss_exceeded_emits_dictionary_overflow_error(self, tmp_path: Path) -> None:
        lexdir = _write_lexicon_dir(tmp_path)
        store = LexiconStore(lexdir, max_rss_mb=128, rss_kb_fn=self._high_rss)
        alerts = store.maybe_reload()
        assert len(alerts) == 1, f"Expected 1 alert; got {alerts}"
        assert alerts[0]["kind"] == "dictionary_overflow"
        assert alerts[0]["severity"] == "error"

    def test_rss_exceeded_refuses_load(self, tmp_path: Path) -> None:
        lexdir = _write_lexicon_dir(tmp_path)
        store = LexiconStore(lexdir, max_rss_mb=128, rss_kb_fn=self._high_rss)
        store.maybe_reload()
        assert not store.is_loaded

    def test_rss_exceeded_preserves_old_snapshot(self, tmp_path: Path) -> None:
        """After a good load, RSS-exceeded reload must keep old snapshot intact."""
        lexdir = _write_lexicon_dir(tmp_path)
        store = LexiconStore(
            lexdir, max_rss_mb=128, reload_s=1, rss_kb_fn=self._low_rss
        )
        store.maybe_reload()
        assert store.is_loaded

        # Switch to high-RSS injector and touch a file to force reload.
        store._rss_kb_fn = self._high_rss
        (lexdir / "teams.tr.yaml").write_text(
            _make_teams_yaml(
                "  - canonical_id: fb\n"
                "    names:\n"
                "      - Fenerbahce\n"
                "    aliases:\n"
                "      - sarikanarya\n"
            ),
            encoding="utf-8",
        )
        _time.sleep(1.1)  # exceed reload_s=1
        alerts = store.maybe_reload()

        assert any(a["kind"] == "dictionary_overflow" for a in alerts)
        # Old snapshot must still be intact.
        result = store.get("teams.tr.yaml")
        assert result is not None
        _, old_entries = result
        assert any(e.get("canonical_id") == "gs" for e in old_entries)

    def test_rss_zero_disables_check(self, tmp_path: Path) -> None:
        """max_rss_mb=0 must disable the RSS check entirely."""
        lexdir = _write_lexicon_dir(tmp_path)
        store = LexiconStore(lexdir, max_rss_mb=0, rss_kb_fn=self._high_rss)
        alerts = store.maybe_reload()
        assert alerts == []
        assert store.is_loaded

    def test_default_max_rss_mb_is_128(self) -> None:
        """Default must match cfg.nlp_lexicon_max_rss_mb default (128 MB)."""
        sig = inspect.signature(LexiconStore.__init__)
        assert sig.parameters["max_rss_mb"].default == 128

    def test_alert_reason_mentions_rss(self, tmp_path: Path) -> None:
        lexdir = _write_lexicon_dir(tmp_path)
        store = LexiconStore(lexdir, max_rss_mb=128, rss_kb_fn=self._high_rss)
        alerts = store.maybe_reload()
        assert alerts
        reason = alerts[0]["reason"]
        assert "RSS" in reason or "rss" in reason.lower() or "budget" in reason
