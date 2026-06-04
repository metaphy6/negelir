"""Tests for Phase 10 §10.5 — Hybrid entity extraction pipeline.

Covers:
  * Gazetteer pass (team/player/league/competition/market)
  * Negative-rule suppression (entities_negative.tr.yaml)
  * Longest-match preference
  * Kind-priority tie-breaking
  * CrfExtractor graceful degradation (missing model)
  * Conflict resolution (gazetteer overrides CRF on overlap)
  * EntitySpan field invariants
  * EntityExtractor.extract end-to-end with a test LexiconStore
"""
from __future__ import annotations

import datetime
import hashlib
import io
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from common.config import cfg

import pytest

from nlp.entity import (
    DEFAULT_KIND_PRIORITY,
    GAZETTEER_KINDS,
    CRF_KINDS,
    AmbiguousHit,
    ExtractionResult,
    CrfExtractor,
    EntityExtractor,
    EntitySpan,
    _NegativeRule,
    _build_combined_alias_index,
    _bio_to_spans,
    _load_negative_rules,
    _merge_two_pass_gazetteer,
    _resolve_conflicts,
    gazetteer_pass,
    PhoneticAliasMatch,
    resolve_polarity,
)
from nlp.lexicon_loader import AliasHit, LexiconStore


# ── Helpers ────────────────────────────────────────────────────────────────

def _make_store_with_teams(tmp_path: Path) -> LexiconStore:
    """Create a minimal LexiconStore with a teams lexicon."""
    lexdir = tmp_path / "lexicon"
    lexdir.mkdir()
    (lexdir / "teams.tr.yaml").write_text(
        """\
_meta:
  schema_version: 1
  lexicon_version: 1.0.0
  generated_at_utc: "2026-01-01T00:00:00Z"
  generator: test
entries:
  - canonical_id: galatasaray_sk
    names:
      - Galatasaray
      - Galatasaray SK
    aliases:
      - gs
      - cimbom
  - canonical_id: fenerbahce_sk
    names:
      - Fenerbahçe
      - Fenerbahçe SK
    aliases:
      - fb
      - fener
""",
        encoding="utf-8",
    )
    (lexdir / "entities_negative.tr.yaml").write_text(
        """\
_meta:
  schema_version: 1
  lexicon_version: 1.0.0
  generated_at_utc: "2026-01-01T00:00:00Z"
  generator: test
entries:
  - token: fener
    requires_cotoken: bahçe
    ambiguous_between:
      - fenerbahce_sk
      - fenerbahce_beko
""",
        encoding="utf-8",
    )
    store = LexiconStore(lexdir, reload_s=9999, max_rss_mb=0)
    store.maybe_reload()
    return store


def _make_alias_index(
    aliases: dict[str, tuple[str, str, str]],
) -> dict[str, AliasHit]:
    """Build a fake alias index.  alias → (canonical_id, kind, lexicon_version)."""
    return {k: AliasHit(cid, kind, ver) for k, (cid, kind, ver) in aliases.items()}


# ── EntitySpan invariants ──────────────────────────────────────────────────

def test_entity_span_is_namedtuple() -> None:
    span = EntitySpan(0, 2, "team", "gs_id", 1.0, "1.0.0", "gazetteer")
    assert span.span_start == 0
    assert span.span_end == 2
    assert span.kind == "team"
    assert span.canonical_id == "gs_id"
    assert span.confidence == 1.0
    assert span.lexicon_version == "1.0.0"
    assert span.source == "gazetteer"


def test_entity_span_immutable() -> None:
    span = EntitySpan(0, 1, "team", "x", 1.0, "1.0.0", "gazetteer")
    with pytest.raises(AttributeError):
        span.kind = "player"  # type: ignore[misc]


# ── Kind constants ─────────────────────────────────────────────────────────

def test_gazetteer_and_crf_kinds_disjoint() -> None:
    assert GAZETTEER_KINDS.isdisjoint(CRF_KINDS)


def test_default_kind_priority_covers_all_kinds() -> None:
    all_kinds = GAZETTEER_KINDS | CRF_KINDS
    assert all_kinds == set(DEFAULT_KIND_PRIORITY)


def test_honorific_table_loaded_with_role_classes(tmp_path: Path) -> None:
    lexdir = tmp_path / "lexicon"
    lexdir.mkdir()
    (lexdir / "players.tr.yaml").write_text(
        """\
_meta:
  schema_version: 1
  lexicon_version: 1.0.0
  generated_at_utc: "2026-01-01T00:00:00Z"
  generator: test
entries:
  - canonical_id: buruk_id
    names:
      - Buruk
    aliases:
      - Buruk
""",
        encoding="utf-8",
    )
    (lexdir / "entities_negative.tr.yaml").write_text(
        """\
_meta:
  schema_version: 1
  lexicon_version: 1.0.0
  generated_at_utc: "2026-01-01T00:00:00Z"
  generator: test
entries: []
""",
        encoding="utf-8",
    )
    honorifics_path = tmp_path / "honorifics.tr.yaml"
    honorifics_path.write_text(
        """\
_meta:
  schema_version: 1
  table_version: "1.0.0"
  generated_at_utc: "2026-01-01T00:00:00Z"
entries:
  - honorific: hoca
    role_class: manager
    aliases:
      - teknik direktör
      - antrenör
""",
        encoding="utf-8",
    )
    store = LexiconStore(lexdir, reload_s=9999, max_rss_mb=0)
    store.maybe_reload()
    extractor = EntityExtractor(store, honorifics_path=honorifics_path)

    result = extractor.extract(["hoca", "Buruk", "istifa"])
    kinds = [span.kind for span in result.spans]
    assert kinds == ["role_prefix", "player"]
    assert result.spans[0].canonical_id == "manager"
    assert result.spans[1].canonical_id == "buruk_id"


def test_nlp_lastname_resolution_prefers_currently_active_player(tmp_path: Path) -> None:
    lexdir = tmp_path / "lexicon"
    lexdir.mkdir()
    (lexdir / "teams.tr.yaml").write_text(
        """\
_meta:
  schema_version: 1
  lexicon_version: 1.0.0
  generated_at_utc: "2026-01-01T00:00:00Z"
  generator: test
entries:
  - canonical_id: gs
    names:
      - Galatasaray
    aliases:
      - gs
  - canonical_id: fb
    names:
      - Fenerbahçe
    aliases:
      - fb
""",
        encoding="utf-8",
    )
    (lexdir / "players.tr.yaml").write_text(
        """\
_meta:
  schema_version: 1
  lexicon_version: 1.0.0
  generated_at_utc: "2026-01-01T00:00:00Z"
  generator: test
entries:
  - canonical_id: gs_player_id
    team_canonical_id: gs
    names:
      - Ali Yilmaz
    aliases:
      - Ali
      - Yilmaz
  - canonical_id: fb_player_id
    team_canonical_id: fb
    names:
      - Mehmet Yilmaz
    aliases:
      - Mehmet
      - Yilmaz
""",
        encoding="utf-8",
    )
    (lexdir / "entities_negative.tr.yaml").write_text(
        """\
_meta:
  schema_version: 1
  lexicon_version: 1.0.0
  generated_at_utc: "2026-01-01T00:00:00Z"
  generator: test
entries: []
""",
        encoding="utf-8",
    )
    honorifics_path = tmp_path / "honorifics.tr.yaml"
    honorifics_path.write_text(
        """\
_meta:
  schema_version: 1
  table_version: "1.0.0"
  generated_at_utc: "2026-01-01T00:00:00Z"
entries:
  - honorific: hoca
    role_class: manager
""",
        encoding="utf-8",
    )
    store = LexiconStore(lexdir, reload_s=9999, max_rss_mb=0)
    store.maybe_reload()
    extractor = EntityExtractor(store, honorifics_path=honorifics_path)

    result = extractor.extract(["hoca", "Yilmaz", "Galatasaray"])
    player_ids = [span.canonical_id for span in result.spans if span.kind == "player"]
    assert player_ids == ["gs_player_id"]


# ── Gazetteer pass: single-token match ────────────────────────────────────

def test_gazetteer_single_token_match() -> None:
    alias_index = _make_alias_index({"galatasaray": ("gs_id", "team", "1.0")})
    spans = gazetteer_pass(["galatasaray", "maç"], alias_index, [], DEFAULT_KIND_PRIORITY)
    assert len(spans) == 1
    s = spans[0]
    assert s.span_start == 0
    assert s.span_end == 1
    assert s.kind == "team"
    assert s.canonical_id == "gs_id"
    assert s.confidence == 1.0
    assert s.source == "gazetteer"


def test_gazetteer_multi_token_match() -> None:
    alias_index = _make_alias_index({"galatasaray sk": ("gs_id", "team", "1.0")})
    spans = gazetteer_pass(["galatasaray", "sk", "gol"], alias_index, [], DEFAULT_KIND_PRIORITY)
    assert len(spans) == 1
    assert spans[0].span_start == 0
    assert spans[0].span_end == 2


def test_gazetteer_no_match_returns_empty() -> None:
    alias_index = _make_alias_index({"galatasaray": ("gs_id", "team", "1.0")})
    spans = gazetteer_pass(["fenerbahçe", "maç"], alias_index, [], DEFAULT_KIND_PRIORITY)
    assert spans == []


def test_gazetteer_empty_tokens() -> None:
    alias_index = _make_alias_index({"x": ("x_id", "team", "1.0")})
    assert gazetteer_pass([], alias_index, [], DEFAULT_KIND_PRIORITY) == []


# ── Gazetteer pass: longest-match preference ──────────────────────────────

def test_gazetteer_longest_match_wins() -> None:
    """'galatasaray sk' (2-token) wins over 'galatasaray' (1-token)."""
    alias_index = _make_alias_index({
        "galatasaray": ("gs_id_short", "team", "1.0"),
        "galatasaray sk": ("gs_id_full", "team", "1.0"),
    })
    spans = gazetteer_pass(["galatasaray", "sk"], alias_index, [], DEFAULT_KIND_PRIORITY)
    assert len(spans) == 1
    assert spans[0].canonical_id == "gs_id_full"
    assert spans[0].span_end == 2


def test_affix_tolerant_team_name_enters_gazetteer_via_lexicon_store(tmp_path: Path) -> None:
    lexdir = tmp_path / "lexicon"
    lexdir.mkdir()
    (lexdir / "teams.tr.yaml").write_text(
        """\
_meta:
  schema_version: 1
  lexicon_version: 1.0.0
  generated_at_utc: "2026-01-01T00:00:00Z"
  generator: test
entries:
  - canonical_id: mke_ankaragucu
    names:
      - MKE Ankaragücü
    aliases: []
    affixes:
      prefix:
        - MKE
""",
        encoding="utf-8",
    )
    store = LexiconStore(lexdir, reload_s=9999, max_rss_mb=0)
    store.maybe_reload()
    extractor = EntityExtractor(store)

    result = extractor.extract(["ankaragücü", "maç"])
    assert len(result.spans) == 1
    assert result.spans[0].kind == "team"
    assert result.spans[0].canonical_id == "mke_ankaragucu"


def test_gazetteer_non_overlapping_multiple_matches() -> None:
    """Two non-overlapping spans are both kept."""
    alias_index = _make_alias_index({
        "galatasaray": ("gs_id", "team", "1.0"),
        "fenerbahçe": ("fb_id", "team", "1.0"),
    })
    tokens = ["galatasaray", "vs", "fenerbahçe"]
    spans = gazetteer_pass(tokens, alias_index, [], DEFAULT_KIND_PRIORITY)
    assert len(spans) == 2
    assert spans[0].canonical_id == "gs_id"
    assert spans[1].canonical_id == "fb_id"

def test_nlp_kara_kartal_compound_resolves_to_besiktas_after_backtrack(tmp_path: Path) -> None:
    lexdir = tmp_path / "lexicon"
    lexdir.mkdir()
    (lexdir / "teams.tr.yaml").write_text(
        """\
_meta:
  schema_version: 1
  lexicon_version: 1.0.0
  generated_at_utc: "2026-01-01T00:00:00Z"
  generator: test
entries:
  - canonical_id: besiktas_jk
    names:
      - Beşiktaş
    aliases:
      - besiktas
""",
        encoding="utf-8",
    )
    (lexdir / "entities_negative.tr.yaml").write_text(
        """\
_meta:
  schema_version: 1
  lexicon_version: 1.0.0
  generated_at_utc: "2026-01-01T00:00:00Z"
  generator: test
entries: []
""",
        encoding="utf-8",
    )
    team_nicknames_path = tmp_path / "team_nicknames.tr.yaml"
    team_nicknames_path.write_text(
        """\
_meta:
  schema_version: 1
  table_version: "1.0.0"
  generated_at_utc: "2026-06-03T00:00:00Z"
  source: "phase10-10.24.12"
aliases:
  - alias_form: "kara kartal"
    canonical_id: "besiktas_jk"
    requires_co_token: false
""",
        encoding="utf-8",
    )
    store = LexiconStore(lexdir, reload_s=9999, max_rss_mb=0)
    store.maybe_reload()

    extractor = EntityExtractor(store, team_nicknames_path=team_nicknames_path)
    result = extractor.extract(["kara", "kartal", "puan", "durumu"])

    assert len(result.spans) == 1
    span = result.spans[0]
    assert span.kind == "team"
    assert span.canonical_id == "besiktas_jk"
    assert span.span_start == 0
    assert span.span_end == 2


def test_nlp_backtrack_capped_at_one_retry(tmp_path: Path, monkeypatch: Any) -> None:
    lexdir = tmp_path / "lexicon"
    lexdir.mkdir()
    (lexdir / "teams.tr.yaml").write_text(
        """\
_meta:
  schema_version: 1
  lexicon_version: 1.0.0
  generated_at_utc: "2026-01-01T00:00:00Z"
  generator: test
entries:
  - canonical_id: besiktas_jk
    names:
      - Beşiktaş
    aliases:
      - besiktas
""",
        encoding="utf-8",
    )
    (lexdir / "entities_negative.tr.yaml").write_text(
        """\
_meta:
  schema_version: 1
  lexicon_version: 1.0.0
  generated_at_utc: "2026-01-01T00:00:00Z"
  generator: test
entries: []
""",
        encoding="utf-8",
    )
    team_nicknames_path = tmp_path / "team_nicknames.tr.yaml"
    team_nicknames_path.write_text(
        """\
_meta:
  schema_version: 1
  table_version: "1.0.0"
  generated_at_utc: "2026-06-03T00:00:00Z"
  source: "phase10-10.24.12"
aliases:
  - alias_form: "kara kartal"
    canonical_id: "besiktas_jk"
    requires_co_token: false
""",
        encoding="utf-8",
    )
    store = LexiconStore(lexdir, reload_s=9999, max_rss_mb=0)
    store.maybe_reload()

    monkeypatch.setattr(cfg, "nlp_backtrack_max_attempts", 0)
    extractor = EntityExtractor(store, team_nicknames_path=team_nicknames_path)
    result = extractor.extract(["kara", "kartal", "puan", "durumu"])

    assert all(span.canonical_id != "besiktas_jk" for span in result.spans)

# ── Gazetteer pass: kind priority tie-breaking ────────────────────────────

def test_gazetteer_kind_priority_tiebreak() -> None:
    """When two aliases overlap at the same length, kind_priority decides."""
    alias_index = _make_alias_index({
        "gs": ("gs_team", "team", "1.0"),
        "gs": ("gs_league", "league", "1.0"),  # last write wins in dict —
        # simulate with separate index and check priority ordering
    })
    # With only one entry per alias the priority doesn't conflict in the
    # alias_index dict itself.  Test that the sort order is correct by having
    # two equal-length single-token spans that compete for the same slot.
    alias_index2 = {
        "gs": AliasHit("gs_team", "team", "1.0"),
    }
    alias_index3 = {
        "gs": AliasHit("gs_league", "league", "1.0"),
    }
    # team ranks before league in DEFAULT_KIND_PRIORITY
    priority = ["team", "league"]
    # Dict only has one key; whichever is in the index wins.
    spans_team = gazetteer_pass(["gs"], alias_index2, [], priority)
    spans_league = gazetteer_pass(["gs"], alias_index3, [], priority)
    assert spans_team[0].kind == "team"
    assert spans_league[0].kind == "league"


# ── Negative-rule suppression ─────────────────────────────────────────────

def test_negative_rule_suppresses_standalone_token() -> None:
    """'fener' alone should be suppressed if 'bahçe' is absent."""
    alias_index = _make_alias_index({"fener": ("fb_id", "team", "1.0")})
    rules = [_NegativeRule(token="fener", requires_cotokens=frozenset({"bahçe"}))]
    spans = gazetteer_pass(["fener", "maç"], alias_index, rules, DEFAULT_KIND_PRIORITY)
    assert spans == []


def test_negative_rule_allows_match_with_cotoken() -> None:
    """'fener bahçe' should NOT be suppressed because 'bahçe' is present."""
    alias_index = _make_alias_index({"fener": ("fb_id", "team", "1.0")})
    rules = [_NegativeRule(token="fener", requires_cotokens=frozenset({"bahçe"}))]
    spans = gazetteer_pass(["fener", "bahçe", "maç"], alias_index, rules, DEFAULT_KIND_PRIORITY)
    assert len(spans) == 1
    assert spans[0].canonical_id == "fb_id"


def test_nlp_bare_city_rize_requires_co_token_for_club() -> None:
    alias_index = _make_alias_index({"rize": ("rizespor", "team", "1.0")})
    rules = [
        _NegativeRule(
            token="rize",
            requires_cotokens=frozenset({"maç", "skor", "kadro", "fikstür", "puan", "forma", "hocası", "teknik"}),
            requires_cotoken_radius=4,
            ambiguous_between=("rize_city", "rizespor"),
        )
    ]

    ambiguous: list[AmbiguousHit] = []
    spans = gazetteer_pass(["rize", "maç"], alias_index, rules, DEFAULT_KIND_PRIORITY, out_ambiguous=ambiguous)
    assert len(spans) == 1
    assert spans[0].canonical_id == "rizespor"
    assert ambiguous == []

    ambiguous.clear()
    spans = gazetteer_pass(["rize", "yeni", "haber"], alias_index, rules, DEFAULT_KIND_PRIORITY, out_ambiguous=ambiguous)
    assert spans == []
    assert len(ambiguous) == 1
    assert ambiguous[0].alias == "rize"
    assert ambiguous[0].candidates == ("rize_city", "rizespor")


def test_gazetteer_negation_marker_extracts_token_span() -> None:
    alias_index = _make_alias_index({"değil": ("", "negation", "1.0")})
    spans = gazetteer_pass(["o", "değil", "mi"], alias_index, [], DEFAULT_KIND_PRIORITY)
    assert len(spans) == 1
    assert spans[0].kind == "negation"
    assert spans[0].span_start == 1
    assert spans[0].span_end == 2


def test_gazetteer_verbal_negation_suffix_is_recognized() -> None:
    alias_index = _make_alias_index({})
    spans = gazetteer_pass(["kazanmadı", "mi"], alias_index, [], DEFAULT_KIND_PRIORITY)
    assert len(spans) == 1
    assert spans[0].kind == "negation"
    assert spans[0].span_start == 0
    assert spans[0].span_end == 1


def test_resolve_polarity_uses_double_negation_patterns() -> None:
    tokens = ["kazanmadı", "değil", "mi"]
    entities = [EntitySpan(0, 1, "negation", "", 1.0, "", "gazetteer")]
    assert resolve_polarity(entities, tokens) == "affirm"


def test_resolve_polarity_returns_negate_for_single_negation() -> None:
    tokens = ["kazanmadı", "mi"]
    entities = [EntitySpan(0, 1, "negation", "", 1.0, "", "gazetteer")]
    assert resolve_polarity(entities, tokens) == "negate"


# ── BIO → spans conversion ─────────────────────────────────────────────────

def test_bio_to_spans_single_entity() -> None:
    tokens = ["bugün", "maç", "var"]
    labels = ["B-date", "O", "O"]
    spans = _bio_to_spans(tokens, labels)
    assert len(spans) == 1
    assert spans[0].span_start == 0
    assert spans[0].span_end == 1
    assert spans[0].kind == "date"
    assert spans[0].source == "crf"


def test_bio_to_spans_multi_token_entity() -> None:
    tokens = ["27", "nisan", "saat", "21:30"]
    labels = ["B-date", "I-date", "B-time", "I-time"]
    spans = _bio_to_spans(tokens, labels)
    assert len(spans) == 2
    assert spans[0] == EntitySpan(0, 2, "date", "", 1.0, "", "crf")
    assert spans[1] == EntitySpan(2, 4, "time", "", 1.0, "", "crf")


def test_bio_to_spans_all_outside() -> None:
    tokens = ["merhaba", "dünya"]
    labels = ["O", "O"]
    assert _bio_to_spans(tokens, labels) == []


# ── CrfExtractor: graceful degradation ────────────────────────────────────

def test_crf_extractor_no_model_path() -> None:
    crf = CrfExtractor(model_path="")
    assert not crf.available
    assert "not set" in crf.load_error
    assert crf.extract(["bugün"]) == []


def test_crf_extractor_missing_file(tmp_path: Path) -> None:
    crf = CrfExtractor(model_path=str(tmp_path / "nonexistent.crfsuite"))
    assert not crf.available
    assert "not found" in crf.load_error
    assert crf.extract(["bugün"]) == []


def test_crf_extractor_size_cap(tmp_path: Path) -> None:
    model = tmp_path / "huge.crfsuite"
    model.write_bytes(b"\x00" * (6 * 1024 * 1024))  # 6 MB > 5 MB cap
    crf = CrfExtractor(model_path=str(model), model_max_size_mb=5)
    assert not crf.available
    assert "exceeds cap" in crf.load_error


def test_crf_extractor_sha256_mismatch(tmp_path: Path) -> None:
    model = tmp_path / "model.crfsuite"
    model.write_bytes(b"fake crfsuite model bytes")
    crf = CrfExtractor(
        model_path=str(model),
        model_sha256="0000000000000000000000000000000000000000000000000000000000000000",
    )
    assert not crf.available
    assert "SHA256 mismatch" in crf.load_error


# ── Conflict resolution ────────────────────────────────────────────────────

def test_resolve_conflicts_gazetteer_overrides_crf() -> None:
    gazetteer = [EntitySpan(0, 1, "team", "gs_id", 1.0, "1.0", "gazetteer")]
    crf = [EntitySpan(0, 1, "date", "", 1.0, "", "crf")]  # overlaps token 0
    result = _resolve_conflicts(gazetteer, crf)
    assert len(result) == 1
    assert result[0].source == "gazetteer"


def test_resolve_conflicts_non_overlapping_crf_kept() -> None:
    gazetteer = [EntitySpan(0, 1, "team", "gs_id", 1.0, "1.0", "gazetteer")]
    crf = [EntitySpan(2, 3, "date", "", 1.0, "", "crf")]  # token 2 — no overlap
    result = _resolve_conflicts(gazetteer, crf)
    assert len(result) == 2
    kinds = {s.source for s in result}
    assert kinds == {"gazetteer", "crf"}


def test_resolve_conflicts_sorted_by_span_start() -> None:
    gazetteer = [EntitySpan(2, 3, "team", "x", 1.0, "1.0", "gazetteer")]
    crf = [EntitySpan(0, 1, "date", "", 1.0, "", "crf")]
    result = _resolve_conflicts(gazetteer, crf)
    assert result[0].span_start == 0
    assert result[1].span_start == 2


# ── EntityExtractor end-to-end with real LexiconStore ─────────────────────

def test_extractor_finds_team_in_real_lexicon(tmp_path: Path) -> None:
    store = _make_store_with_teams(tmp_path)
    extractor = EntityExtractor(store=store)
    result = extractor.extract(["galatasaray", "maç", "tahmini"])
    assert isinstance(result, ExtractionResult)
    spans = result.spans
    assert len(spans) == 1
    assert spans[0].kind == "team"
    assert spans[0].canonical_id == "galatasaray_sk"


def test_extractor_finds_multi_token_team(tmp_path: Path) -> None:
    store = _make_store_with_teams(tmp_path)
    extractor = EntityExtractor(store=store)
    result = extractor.extract(["galatasaray", "sk", "kadro"])
    spans = result.spans
    assert len(spans) == 1
    assert spans[0].span_end == 2  # "Galatasaray SK" is a 2-token alias


def test_extractor_suppresses_negative_entity(tmp_path: Path) -> None:
    """'fener' alone is suppressed; co-token 'bahçe' absent."""
    store = _make_store_with_teams(tmp_path)
    extractor = EntityExtractor(store=store)
    result = extractor.extract(["fener", "maçı"])
    # The negative rule should suppress "fener" without "bahçe" co-token
    assert all(s.canonical_id != "fenerbahce_sk" for s in result.spans)


def test_extractor_uses_phonetic_alias_allowlist(tmp_path: Path) -> None:
    store = _make_store_with_teams(tmp_path)
    alias_file = tmp_path / "phonetic_aliases.tr.yaml"
    alias_file.write_text(
        """\
_meta:
  schema_version: 1
  lexicon_version: 1.0.0
  generated_at_utc: "2026-01-01T00:00:00Z"
  generator: test
aliases:
  - canonical_id: galatasaray_sk
    kind: team
    phonetic_form: gs
""",
        encoding="utf-8",
    )
    extractor = EntityExtractor(store=store, phonetic_aliases_path=alias_file)
    result = extractor.extract(["gs", "maç"])
    assert any(s.canonical_id == "galatasaray_sk" for s in result.spans)
    assert result.phonetic_alias_matches == (
        PhoneticAliasMatch(
            alias="gs",
            canonical_id="galatasaray_sk",
            kind="team",
            confused_with=(),
        ),
    )


def test_extractor_ignores_non_allowlisted_phonetic_form(tmp_path: Path) -> None:
    store = _make_store_with_teams(tmp_path)
    alias_file = tmp_path / "phonetic_aliases.tr.yaml"
    alias_file.write_text(
        """\
_meta:
  schema_version: 1
  lexicon_version: 1.0.0
  generated_at_utc: "2026-01-01T00:00:00Z"
  generator: test
aliases:
  - canonical_id: unknown_id
    kind: team
    phonetic_form: qq
""",
        encoding="utf-8",
    )
    extractor = EntityExtractor(store=store, phonetic_aliases_path=alias_file)
    result = extractor.extract(["qq", "maç"])
    assert result.spans == []
    assert result.phonetic_alias_matches == ()


def test_extractor_empty_store_returns_empty(tmp_path: Path) -> None:
    lexdir = tmp_path / "empty"
    lexdir.mkdir()
    store = LexiconStore(lexdir, reload_s=9999, max_rss_mb=0)
    # Deliberately do NOT call maybe_reload (no files present anyway)
    extractor = EntityExtractor(store=store)
    result = extractor.extract(["galatasaray"])
    assert result.spans == []
    assert result.ambiguous == []


def test_extractor_with_crf_no_overlap(tmp_path: Path) -> None:
    """CRF spans that don't overlap with gazetteer are preserved."""
    store = _make_store_with_teams(tmp_path)
    # Inject a mock CRF that returns a date span at position 2
    mock_crf = MagicMock(spec=CrfExtractor)
    mock_crf.extract.return_value = [
        EntitySpan(2, 3, "date", "", 1.0, "", "crf")
    ]
    extractor = EntityExtractor(store=store, crf=mock_crf)
    result = extractor.extract(["galatasaray", "vs", "bugün"])
    assert any(s.kind == "team" for s in result.spans)
    assert any(s.kind == "date" for s in result.spans)


# ── §10.5 Ambiguity policy ─────────────────────────────────────────────────

def test_ambiguous_hit_is_namedtuple() -> None:
    hit = AmbiguousHit(alias="fener", candidates=("fenerbahce_sk", "fenerbahce_beko"))
    assert hit.alias == "fener"
    assert hit.candidates == ("fenerbahce_sk", "fenerbahce_beko")


def test_extraction_result_is_namedtuple() -> None:
    span = EntitySpan(0, 1, "team", "gs_id", 1.0, "1.0", "gazetteer")
    hit = AmbiguousHit(alias="fener", candidates=("fb_sk", "fb_beko"))
    result = ExtractionResult(spans=[span], ambiguous=[hit])
    assert result.spans == [span]
    assert result.ambiguous == [hit]


def test_negative_rule_parses_ambiguous_between(tmp_path: Path) -> None:
    """_load_negative_rules should populate ambiguous_between from YAML."""
    from nlp.lexicon_loader import LexiconStore
    lexdir = tmp_path / "lex"
    lexdir.mkdir()
    (lexdir / "entities_negative.tr.yaml").write_text(
        """\
_meta:
  schema_version: 1
  lexicon_version: 1.0.0
  generated_at_utc: "2026-01-01T00:00:00Z"
  generator: test
entries:
  - token: fener
    requires_cotoken: bahçe
    ambiguous_between:
      - fenerbahce_sk
      - fenerbahce_beko
""",
        encoding="utf-8",
    )
    store = LexiconStore(lexdir, reload_s=9999, max_rss_mb=0)
    store.maybe_reload()
    rules = _load_negative_rules(store)
    assert len(rules) == 1
    assert rules[0].token == "fener"
    assert rules[0].ambiguous_between == ("fenerbahce_sk", "fenerbahce_beko")


def test_negative_rule_without_ambiguous_between_has_empty_tuple(tmp_path: Path) -> None:
    from nlp.lexicon_loader import LexiconStore
    lexdir = tmp_path / "lex"
    lexdir.mkdir()
    (lexdir / "entities_negative.tr.yaml").write_text(
        """\
_meta:
  schema_version: 1
  lexicon_version: 1.0.0
  generated_at_utc: "2026-01-01T00:00:00Z"
  generator: test
entries:
  - token: fener
    requires_cotoken: bahçe
""",
        encoding="utf-8",
    )
    store = LexiconStore(lexdir, reload_s=9999, max_rss_mb=0)
    store.maybe_reload()
    rules = _load_negative_rules(store)
    assert rules[0].ambiguous_between == ()


def test_load_negative_rules_accepts_cotoken_list_and_radius(tmp_path: Path) -> None:
    from nlp.lexicon_loader import LexiconStore

    lexdir = tmp_path / "lex"
    lexdir.mkdir()
    (lexdir / "entities_negative.tr.yaml").write_text(
        """\
_meta:
  schema_version: 1
  lexicon_version: 1.0.0
  generated_at_utc: "2026-01-01T00:00:00Z"
  generator: test
entries:
  - token: rize
    requires_cotoken:
      - maç
      - skor
    requires_cotoken_radius: 4
    ambiguous_between:
      - rize_city
      - rizespor
""",
        encoding="utf-8",
    )
    store = LexiconStore(lexdir, reload_s=9999, max_rss_mb=0)
    store.maybe_reload()
    rules = _load_negative_rules(store)
    assert len(rules) == 1
    assert rules[0].token == "rize"
    assert rules[0].requires_cotokens == frozenset({"maç", "skor"})
    assert rules[0].requires_cotoken_radius == 4
    assert rules[0].ambiguous_between == ("rize_city", "rizespor")


def test_gazetteer_pass_out_ambiguous_populated_on_suppression() -> None:
    """When a negative rule with ambiguous_between fires, out_ambiguous is filled."""
    alias_index = _make_alias_index({"fener": ("fb_id", "team", "1.0")})
    rules = [
        _NegativeRule(
            token="fener",
            requires_cotokens=frozenset({"bahçe"}),
            ambiguous_between=("fenerbahce_sk", "fenerbahce_beko"),
        )
    ]
    out: list[AmbiguousHit] = []
    spans = gazetteer_pass(
        ["fener", "maçı"], alias_index, rules, DEFAULT_KIND_PRIORITY,
        out_ambiguous=out,
    )
    # Span is suppressed (no "bahçe" co-token)
    assert spans == []
    # Ambiguous candidates surfaced to caller
    assert len(out) == 1
    assert out[0].alias == "fener"
    assert out[0].candidates == ("fenerbahce_sk", "fenerbahce_beko")


def test_gazetteer_pass_no_out_ambiguous_when_cotoken_present() -> None:
    """When co-token is present the span is NOT suppressed — no ambiguous hit."""
    alias_index = _make_alias_index({"fener": ("fb_id", "team", "1.0")})
    rules = [
        _NegativeRule(
            token="fener",
            requires_cotokens=frozenset({"bahçe"}),
            ambiguous_between=("fenerbahce_sk", "fenerbahce_beko"),
        )
    ]
    out: list[AmbiguousHit] = []
    spans = gazetteer_pass(
        ["fener", "bahçe", "maçı"], alias_index, rules, DEFAULT_KIND_PRIORITY,
        out_ambiguous=out,
    )
    assert len(spans) == 1
    assert spans[0].canonical_id == "fb_id"
    # No ambiguity — co-token resolved it
    assert out == []


def test_gazetteer_pass_no_ambiguous_hit_without_ambiguous_between() -> None:
    """Suppression without ambiguous_between declaration → out_ambiguous stays empty."""
    alias_index = _make_alias_index({"fener": ("fb_id", "team", "1.0")})
    rules = [_NegativeRule(token="fener", requires_cotokens=frozenset({"bahçe"}))]
    out: list[AmbiguousHit] = []
    spans = gazetteer_pass(
        ["fener", "maçı"], alias_index, rules, DEFAULT_KIND_PRIORITY,
        out_ambiguous=out,
    )
    assert spans == []
    assert out == []  # no ambiguous_between declared → nothing surfaced


def test_gazetteer_pass_out_ambiguous_none_does_not_crash() -> None:
    """Passing out_ambiguous=None (default) should not crash."""
    alias_index = _make_alias_index({"fener": ("fb_id", "team", "1.0")})
    rules = [
        _NegativeRule(
            token="fener",
            requires_cotokens=frozenset({"bahçe"}),
            ambiguous_between=("fenerbahce_sk", "fenerbahce_beko"),
        )
    ]
    # Should complete without error even though out_ambiguous is None
    spans = gazetteer_pass(["fener", "maçı"], alias_index, rules, DEFAULT_KIND_PRIORITY)
    assert spans == []


def test_extractor_surfaces_ambiguous_hit_for_suppressed_alias(tmp_path: Path) -> None:
    """End-to-end: EntityExtractor surfaces AmbiguousHit from entities_negative."""
    store = _make_store_with_teams(tmp_path)  # fixture includes fener + ambiguous_between
    extractor = EntityExtractor(store=store)
    result = extractor.extract(["fener", "maçı"])
    # Span suppressed
    assert all(s.canonical_id != "fenerbahce_sk" for s in result.spans)
    # Ambiguity surfaced — caller must route to 'Did you mean?'
    assert len(result.ambiguous) == 1
    hit = result.ambiguous[0]
    assert hit.alias == "fener"
    assert "fenerbahce_sk" in hit.candidates
    assert "fenerbahce_beko" in hit.candidates


def test_extractor_no_ambiguous_when_cotoken_resolves(tmp_path: Path) -> None:
    """When co-token resolves the alias, no AmbiguousHit is emitted."""
    store = _make_store_with_teams(tmp_path)
    extractor = EntityExtractor(store=store)
    result = extractor.extract(["fener", "bahçe", "maçı"])
    # "fener bahçe" co-token present — not suppressed, no ambiguity
    assert result.ambiguous == []


def test_extractor_result_has_no_ambiguous_for_clean_match(tmp_path: Path) -> None:
    """Clean gazetteer hit (no negative rule firing) → ambiguous list empty."""
    store = _make_store_with_teams(tmp_path)
    extractor = EntityExtractor(store=store)
    result = extractor.extract(["galatasaray", "maç"])
    assert result.spans[0].canonical_id == "galatasaray_sk"
    assert result.ambiguous == []


def test_extractor_uses_restored_fallback_when_ascii_pass_has_no_primary_hit(tmp_path: Path) -> None:
    """§10.22.1: restored pass runs when ASCII pass cannot resolve a primary entity."""
    store = _make_store_with_teams(tmp_path)
    extractor = EntityExtractor(store=store)

    result = extractor.extract(
        ["fenerbahçe", "maç"],
        raw_tokens=["fenrbahce", "maç"],
    )

    assert any(s.kind == "team" and s.canonical_id == "fenerbahce_sk" for s in result.spans)


def test_merge_two_pass_prefers_ascii_on_conflict_without_margin() -> None:
    """§10.22.1: restored hit must clear margin before overriding ASCII hit."""
    ascii_spans = [EntitySpan(0, 1, "team", "ascii_team", 1.0, "1.0", "gazetteer")]
    restored_spans = [EntitySpan(0, 1, "team", "restored_team", 1.0, "1.0", "gazetteer")]

    merged = _merge_two_pass_gazetteer(
        ascii_spans,
        restored_spans,
        kind_priority=DEFAULT_KIND_PRIORITY,
        restored_margin=0.2,
    )

    assert len(merged) == 1
    assert merged[0].canonical_id == "ascii_team"


def test_merge_two_pass_prefers_restored_when_margin_cleared() -> None:
    """§10.22.1: restored hit can override when confidence exceeds the margin."""
    ascii_spans = [EntitySpan(0, 1, "team", "ascii_team", 0.70, "1.0", "gazetteer")]
    restored_spans = [EntitySpan(0, 1, "team", "restored_team", 0.91, "1.0", "gazetteer")]

    merged = _merge_two_pass_gazetteer(
        ascii_spans,
        restored_spans,
        kind_priority=DEFAULT_KIND_PRIORITY,
        restored_margin=0.2,
    )

    assert len(merged) == 1
    assert merged[0].canonical_id == "restored_team"


def test_nlp_ascii_pass_resolves_galatasaray_no_diacritics(tmp_path: Path) -> None:
    """§10.22.1: ASCII-first pass must resolve no-diacritic queries (100-case corpus)."""
    store = _make_store_with_teams(tmp_path)
    extractor = EntityExtractor(store=store)

    corpus = [["galatasaray", "mac", "tahmin", str(i)] for i in range(100)]
    resolved = 0
    for raw_tokens in corpus:
        result = extractor.extract(
            ["galatasaray", "maç", "tahmini"],
            raw_tokens=raw_tokens,
        )
        if any(s.kind == "team" and s.canonical_id == "galatasaray_sk" for s in result.spans):
            resolved += 1

    assert resolved == 100


@pytest.mark.parametrize(
    "ascii_conf,restored_conf",
    [(0.60 + i * 0.01, 0.60 + i * 0.01) for i in range(20)],
)
def test_nlp_double_pass_gazetteer_picks_longer_match(
    ascii_conf: float,
    restored_conf: float,
) -> None:
    """§10.22.1: two-pass merge keeps the longer overlap across ASCII/restored spans."""
    ascii_spans = [EntitySpan(0, 1, "team", "galatasaray_short", ascii_conf, "1.0", "gazetteer")]
    restored_spans = [EntitySpan(0, 2, "team", "galatasaray_full", restored_conf, "1.0", "gazetteer")]

    merged = _merge_two_pass_gazetteer(
        ascii_spans,
        restored_spans,
        kind_priority=DEFAULT_KIND_PRIORITY,
        restored_margin=0.2,
    )

    assert len(merged) == 1
    assert merged[0].canonical_id == "galatasaray_full"
    assert merged[0].span_start == 0
    assert merged[0].span_end == 2
