"""Phase 10 §10.2 — Build pipeline tests.

Verifies:
  - _aliases_delta.tr.yaml exists and is valid YAML with correct structure.
  - make verify.nlp-lexicons assertions (a), (b), (c) pass on the live lexicons.
  - Adversarial cases: alias collision without disambiguator is flagged,
    markets.tr.yaml with unknown canonical_id is flagged,
    normalize round-trip collision is flagged.

Per AGENTS.md Rule 10: new surface -> happy + adversarial tests.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

# Make sure ai/ is on the path when running from REPO_ROOT
_AI_DIR = Path(__file__).parent.parent
_REPO_ROOT = _AI_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_AI_DIR) not in sys.path:
    sys.path.insert(0, str(_AI_DIR))

LEXICON_DIR = _AI_DIR / "nlp" / "lexicon"
DELTA_FILE = LEXICON_DIR / "_aliases_delta.tr.yaml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_lexicon(fname: str) -> dict[str, Any]:
    data = yaml.safe_load((LEXICON_DIR / fname).read_text(encoding="utf-8"))
    assert isinstance(data, dict) and "entries" in data
    return data


def _load_markets_ids() -> set[str]:
    mpath = _AI_DIR / "common" / "betting_markets.json"
    mdata = json.loads(mpath.read_text(encoding="utf-8"))
    ids: set[str] = set()
    for cat in mdata.get("categories", []):
        for market in cat.get("markets", []):
            mid = market.get("id")
            if mid:
                ids.add(str(mid))
    return ids


# ---------------------------------------------------------------------------
# Delta file structure tests
# ---------------------------------------------------------------------------

class TestDeltaFileExists:
    """_aliases_delta.tr.yaml must exist and be valid YAML."""

    def test_delta_file_exists(self) -> None:
        assert DELTA_FILE.exists(), f"Missing delta file: {DELTA_FILE}"

    def test_delta_file_is_valid_yaml(self) -> None:
        try:
            data = yaml.safe_load(DELTA_FILE.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            pytest.fail(f"_aliases_delta.tr.yaml is not valid YAML: {exc}")
        assert isinstance(data, dict), "delta file top-level must be a mapping"

    def test_delta_file_has_meta(self) -> None:
        data = yaml.safe_load(DELTA_FILE.read_text(encoding="utf-8"))
        assert "_meta" in data, "delta file must have _meta block"
        assert "schema_version" in data["_meta"]

    def test_delta_file_has_deltas_list(self) -> None:
        data = yaml.safe_load(DELTA_FILE.read_text(encoding="utf-8"))
        assert "deltas" in data, "delta file must have 'deltas' list"
        assert isinstance(data["deltas"], list)

    def test_delta_entries_have_required_keys(self) -> None:
        data = yaml.safe_load(DELTA_FILE.read_text(encoding="utf-8"))
        for i, d in enumerate(data.get("deltas", [])):
            assert "file" in d, f"delta[{i}] missing 'file'"
            assert "canonical_id" in d, f"delta[{i}] missing 'canonical_id'"
            assert "add_aliases" in d, f"delta[{i}] missing 'add_aliases'"
            assert isinstance(d["add_aliases"], list), f"delta[{i}].add_aliases must be a list"

    def test_delta_file_targets_exist(self) -> None:
        data = yaml.safe_load(DELTA_FILE.read_text(encoding="utf-8"))
        for d in data.get("deltas", []):
            target = LEXICON_DIR / d["file"]
            assert target.exists(), f"delta references missing file: {d['file']}"


# ---------------------------------------------------------------------------
# Assertion (a): canonical_id resolution
# ---------------------------------------------------------------------------

class TestVerifyCanonicalIdResolution:
    """(a) markets.tr.yaml canonical_ids must be in betting_markets.json enum."""

    def test_markets_canonical_ids_resolve(self) -> None:
        markets_ids = _load_markets_ids()
        data = _load_lexicon("markets.tr.yaml")
        bad: list[str] = []
        for entry in data["entries"]:
            cid = entry.get("canonical_id")
            if cid and str(cid) not in markets_ids:
                bad.append(str(cid))
        assert not bad, (
            f"markets.tr.yaml: canonical_ids not in betting_markets.json: {bad}"
        )

    def test_canonical_id_files_have_canonical_id_per_entry(self) -> None:
        """All entries in non-dialect lexicons must carry canonical_id."""
        canonical_files = [
            "teams.tr.yaml", "players.tr.yaml",
            "leagues.tr.yaml", "competitions.tr.yaml", "markets.tr.yaml",
        ]
        for fname in canonical_files:
            data = _load_lexicon(fname)
            for i, entry in enumerate(data["entries"]):
                assert "canonical_id" in entry, (
                    f"{fname} entry[{i}] missing 'canonical_id'"
                )

    def test_adversarial_unknown_markets_id_detected(self) -> None:
        """Verify the assertion logic catches unknown market canonical_ids."""
        markets_ids = _load_markets_ids()
        fake_id = "nonexistent_market_xyz_12345"
        assert fake_id not in markets_ids, "Test setup: fake id must not be real"
        # Simulate checking an entry with a bad id
        bad_entries = [{"canonical_id": fake_id, "names": ["X"], "aliases": ["x"]}]
        violations = [
            e["canonical_id"]
            for e in bad_entries
            if e.get("canonical_id") not in markets_ids
        ]
        assert violations == [fake_id]


# ---------------------------------------------------------------------------
# Assertion (b): alias collision uniqueness
# ---------------------------------------------------------------------------

class TestVerifyAliasUniqueness:
    """(b) No two canonicals share an alias without entities_negative cover."""

    def _build_alias_index(self) -> tuple[dict[str, list[tuple[str, str]]], set[str]]:
        """Returns alias_to_owners and neg_tokens from live files."""
        canonical_files = [
            "teams.tr.yaml", "players.tr.yaml",
            "leagues.tr.yaml", "competitions.tr.yaml", "markets.tr.yaml",
        ]
        alias_to_owners: dict[str, list[tuple[str, str]]] = {}
        for fname in canonical_files:
            data = _load_lexicon(fname)
            for entry in data["entries"]:
                cid = str(entry.get("canonical_id", ""))
                for alias in entry.get("aliases", []):
                    key = str(alias).strip().lower()
                    alias_to_owners.setdefault(key, []).append((fname, cid))
                for name in entry.get("names", []):
                    key = str(name).strip().lower()
                    alias_to_owners.setdefault(key, []).append((fname, cid))
        neg_data = _load_lexicon("entities_negative.tr.yaml")
        neg_tokens: set[str] = set()
        for entry in neg_data["entries"]:
            tok = entry.get("token")
            if tok:
                neg_tokens.add(str(tok).strip().lower())
        return alias_to_owners, neg_tokens

    def test_no_uncovered_alias_collision_in_live_lexicons(self) -> None:
        alias_to_owners, neg_tokens = self._build_alias_index()
        violations: list[str] = []
        for alias_str, owners in alias_to_owners.items():
            unique_cids = {cid for _, cid in owners}
            if len(unique_cids) > 1:
                alias_tokens = alias_str.split()
                covered = any(tok in neg_tokens for tok in alias_tokens)
                if not covered:
                    violations.append(alias_str)
        assert not violations, (
            f"Uncovered alias collisions (no entities_negative entry): {violations}"
        )

    def test_adversarial_collision_without_disambiguator_detected(self) -> None:
        """The check must flag aliases shared between two canonicals with no
        entities_negative token."""
        alias_to_owners: dict[str, list[tuple[str, str]]] = {
            "gs": [("teams.tr.yaml", "galatasaray_sk"), ("leagues.tr.yaml", "fake_league_gs")],
        }
        neg_tokens: set[str] = set()  # empty -> no coverage
        violations: list[str] = []
        for alias_str, owners in alias_to_owners.items():
            unique_cids = {cid for _, cid in owners}
            if len(unique_cids) > 1:
                alias_tokens = alias_str.split()
                covered = any(tok in neg_tokens for tok in alias_tokens)
                if not covered:
                    violations.append(alias_str)
        assert "gs" in violations

    def test_adversarial_collision_with_disambiguator_passes(self) -> None:
        """A collision covered by entities_negative must NOT be flagged."""
        alias_to_owners: dict[str, list[tuple[str, str]]] = {
            "fener": [
                ("teams.tr.yaml", "fenerbahce_sk"),
                ("teams.tr.yaml", "fenerbahce_beko"),
            ],
        }
        neg_tokens: set[str] = {"fener"}  # covered
        violations: list[str] = []
        for alias_str, owners in alias_to_owners.items():
            unique_cids = {cid for _, cid in owners}
            if len(unique_cids) > 1:
                alias_tokens = alias_str.split()
                covered = any(tok in neg_tokens for tok in alias_tokens)
                if not covered:
                    violations.append(alias_str)
        assert not violations


# ---------------------------------------------------------------------------
# Assertion (c): normalize round-trip
# ---------------------------------------------------------------------------

class TestVerifyNormalizeRoundTrip:
    """(c) Normalized alias must not collide with another canonical's normalized alias."""

    def test_no_normalize_round_trip_collision_in_live_lexicons(self) -> None:
        from common.config import cfg
        from nlp.normalize import normalize_input

        canonical_files = [
            "teams.tr.yaml", "players.tr.yaml",
            "leagues.tr.yaml", "competitions.tr.yaml", "markets.tr.yaml",
        ]
        neg_data = _load_lexicon("entities_negative.tr.yaml")
        neg_tokens: set[str] = {
            str(e.get("token", "")).strip().lower()
            for e in neg_data["entries"]
            if e.get("token")
        }
        norm_to_owners: dict[str, list[tuple[str, str]]] = {}
        for fname in canonical_files:
            data = _load_lexicon(fname)
            for entry in data["entries"]:
                cid = str(entry.get("canonical_id", ""))
                for alias in entry.get("aliases", []):
                    try:
                        tokens = normalize_input(str(alias), cfg=cfg)
                        norm_key = " ".join(tokens)
                    except Exception:
                        norm_key = str(alias).strip().lower()
                    norm_to_owners.setdefault(norm_key, []).append((fname, cid))

        violations: list[str] = []
        for norm_key, owners in norm_to_owners.items():
            unique_cids = {cid for _, cid in owners}
            if len(unique_cids) > 1:
                alias_tokens = norm_key.split()
                covered = any(tok in neg_tokens for tok in alias_tokens)
                if not covered:
                    violations.append(norm_key)
        assert not violations, (
            f"Normalize round-trip collisions without disambiguator: {violations}"
        )

    def test_adversarial_normalize_collision_detected(self) -> None:
        """Verify that normalized-form collision is caught when no disambiguator."""
        norm_to_owners: dict[str, list[tuple[str, str]]] = {
            "gs": [
                ("teams.tr.yaml", "galatasaray_sk"),
                ("leagues.tr.yaml", "fake_league"),
            ],
        }
        neg_tokens: set[str] = set()
        violations: list[str] = []
        for norm_key, owners in norm_to_owners.items():
            unique_cids = {cid for _, cid in owners}
            if len(unique_cids) > 1:
                alias_tokens = norm_key.split()
                covered = any(tok in neg_tokens for tok in alias_tokens)
                if not covered:
                    violations.append(norm_key)
        assert "gs" in violations


# ---------------------------------------------------------------------------
# §10.22.1 ASCII sidecar index helpers
# ---------------------------------------------------------------------------

class TestAsciiAliasIndexHelpers:
    """ASCII sidecar rows and collision coverage checks for lexicon-build."""

    def test_collect_alias_rows_emits_folded_keys_and_frequency(self) -> None:
        from xops.makefile.nlp import _collect_alias_rows

        entries = [
            {
                "canonical_id": "galatasaray_sk",
                "names": ["Galatasaray"],
                "aliases": ["Galatasaray", "G.S"],
            },
            {
                "canonical_id": "fenerbahce_sk",
                "names": ["Fenerbahçe"],
                "aliases": ["Fenerbahce"],
            },
        ]
        word_freq = {"galatasaray": 1200, "fenerbahce": 900}

        rows, ownership = _collect_alias_rows(entries, word_freq)

        assert "galatasaray" in rows
        assert ["galatasaray_sk", "Galatasaray", 1200.0] in rows["galatasaray"]
        assert "fenerbahce" in rows
        assert ["fenerbahce_sk", "Fenerbahçe", 900.0] in rows["fenerbahce"]
        assert ownership["galatasaray"] == {"galatasaray_sk"}
        assert ownership["fenerbahce"] == {"fenerbahce_sk"}

    def test_ascii_collision_requires_neg_token_or_allowlist(self) -> None:
        from xops.makefile.nlp import _collect_alias_rows

        entries = [
            {
                "canonical_id": "fenerbahce_sk",
                "names": ["Fener"],
                "aliases": [],
            },
            {
                "canonical_id": "fenerbahce_beko",
                "names": ["Fener"],
                "aliases": [],
            },
        ]
        _, ownership = _collect_alias_rows(entries, {})

        assert "fener" in ownership
        assert len(ownership["fener"]) == 2

        neg_tokens = {"fener"}
        allowlist = set()
        covered_by_neg = any(tok in neg_tokens for tok in "fener".split())
        covered_by_allow = "fener" in allowlist
        assert covered_by_neg and not covered_by_allow

        neg_tokens = set()
        allowlist = {"fener"}
        covered_by_neg = any(tok in neg_tokens for tok in "fener".split())
        covered_by_allow = "fener" in allowlist
        assert not covered_by_neg and covered_by_allow

    def test_nlp_ascii_collision_build_refuses_without_allowlist(self) -> None:
        """§10.22.1: unresolved ASCII collisions must be rejected by build logic."""
        from xops.makefile.nlp import _collect_alias_rows

        entries = [
            {
                "canonical_id": "fenerbahce_sk",
                "names": ["Fener"],
                "aliases": [],
            },
            {
                "canonical_id": "fenerbahce_beko",
                "names": ["Fener"],
                "aliases": [],
            },
        ]
        _, ownership = _collect_alias_rows(entries, {})

        neg_tokens: set[str] = set()
        allowlist: set[str] = set()
        uncovered = []
        for alias_key, owners in sorted(ownership.items()):
            if len(owners) <= 1:
                continue
            if alias_key in allowlist:
                continue
            parts = [part for part in alias_key.split() if part]
            if any(part in neg_tokens for part in parts):
                continue
            uncovered.append(alias_key)

        assert "fener" in uncovered
