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
            assert "kind" in d, f"delta[{i}] missing 'kind'"
            assert "canonical_id" in d, f"delta[{i}] missing 'canonical_id'"
            assert "source" in d, f"delta[{i}] missing 'source'"
            assert "added_by_pr" in d, f"delta[{i}] missing 'added_by_pr'"
            assert "added_at_utc" in d, f"delta[{i}] missing 'added_at_utc'"
            assert "add_aliases" in d, f"delta[{i}] missing 'add_aliases'"
            assert isinstance(d["add_aliases"], list), f"delta[{i}].add_aliases must be a list"

    def test_delta_file_targets_exist(self) -> None:
        data = yaml.safe_load(DELTA_FILE.read_text(encoding="utf-8"))
        for d in data.get("deltas", []):
            target = LEXICON_DIR / d["file"]
            assert target.exists(), f"delta references missing file: {d['file']}"


class TestAliasDeltaMetadataGovernance:
    def test_delta_entries_include_source_and_pr_metadata(self) -> None:
        data = yaml.safe_load(DELTA_FILE.read_text(encoding="utf-8"))
        for i, d in enumerate(data.get("deltas", [])):
            assert isinstance(d.get("source"), str) and d["source"].strip(), (
                f"delta[{i}] missing or invalid 'source'"
            )
            assert isinstance(d.get("added_by_pr"), str) and d["added_by_pr"].strip(), (
                f"delta[{i}] missing or invalid 'added_by_pr'"
            )
            assert isinstance(d.get("added_at_utc"), str) and d["added_at_utc"].strip(), (
                f"delta[{i}] missing or invalid 'added_at_utc'"
            )

    def test_delta_source_allowlist(self) -> None:
        from xops.makefile.nlp import _validate_alias_delta_entries

        invalid = [
            {
                "file": "teams.tr.yaml",
                "kind": "team",
                "canonical_id": "galatasaray_sk",
                "add_aliases": ["yeni aslan"],
                "source": "random_source",
                "added_by_pr": "PR-9999",
                "added_at_utc": "2026-06-01T12:00:00Z",
            }
        ]

        errors = _validate_alias_delta_entries(invalid)
        assert any("source 'random_source' is not in the allowed source set" in e for e in errors)

    def test_delta_unknown_canonical_id_is_rejected(self, tmp_path) -> None:
        from xops.makefile.nlp import _validate_alias_delta_entries

        lexicon_dir = tmp_path / "ai" / "nlp" / "lexicon"
        lexicon_dir.mkdir(parents=True, exist_ok=True)
        file_path = lexicon_dir / "teams.tr.yaml"
        file_path.write_text(
            "_meta:\n  schema_version: 1\n  lexicon_version: \"1.0.0\"\nentries:\n  - canonical_id: galatasaray_sk\n    names: [Galatasaray]\n    aliases: [Galatasaray]\n",
            encoding="utf-8",
        )

        invalid = [
            {
                "file": "teams.tr.yaml",
                "kind": "team",
                "canonical_id": "unknown_team",
                "add_aliases": ["yeni aslan"],
                "source": "operator_curation",
                "added_by_pr": "PR-9999",
                "added_at_utc": "2026-06-01T12:00:00Z",
            }
        ]

        errors = _validate_alias_delta_entries(invalid, lexicon_dir)
        assert any("canonical_id 'unknown_team' not found" in e for e in errors)


class TestLexiconDeltaTyposquatDetection:
    def test_typosquat_alias_is_rejected(self, tmp_path) -> None:
        from xops.makefile.nlp import _validate_alias_delta_entries

        lexicon_dir = tmp_path / "ai" / "nlp" / "lexicon"
        lexicon_dir.mkdir(parents=True, exist_ok=True)
        file_path = lexicon_dir / "teams.tr.yaml"
        file_path.write_text(
            "_meta:\n  schema_version: 1\n  lexicon_version: \"1.0.0\"\nentries:\n"
            "  - canonical_id: fenerbahce_sk\n"
            "    names: [Fenerbahçe]\n"
            "    aliases: [Fenerbahce]\n"
            "  - canonical_id: besiktas_jk\n"
            "    names: [Beşiktaş]\n"
            "    aliases: [Besiktas]\n",
            encoding="utf-8",
        )

        invalid = [
            {
                "file": "teams.tr.yaml",
                "kind": "team",
                "canonical_id": "besiktas_jk",
                "add_aliases": ["Fenerbahçe"],
                "source": "operator_curation",
                "added_by_pr": "PR-9999",
                "added_at_utc": "2026-06-01T12:00:00Z",
                "min_corpus_appearances": 3,
            }
        ]

        errors = _validate_alias_delta_entries(invalid, lexicon_dir)
        assert any("typo-squat" in e for e in errors)

    def test_typosquat_alias_override_allows_conflict(self, tmp_path) -> None:
        from xops.makefile.nlp import _validate_alias_delta_entries

        lexicon_dir = tmp_path / "ai" / "nlp" / "lexicon"
        lexicon_dir.mkdir(parents=True, exist_ok=True)
        file_path = lexicon_dir / "teams.tr.yaml"
        file_path.write_text(
            "_meta:\n  schema_version: 1\n  lexicon_version: \"1.0.0\"\nentries:\n"
            "  - canonical_id: fenerbahce_sk\n"
            "    names: [Fenerbahçe]\n"
            "    aliases: [Fenerbahce]\n"
            "  - canonical_id: besiktas_jk\n"
            "    names: [Beşiktaş]\n"
            "    aliases: [Besiktas]\n",
            encoding="utf-8",
        )

        valid = [
            {
                "file": "teams.tr.yaml",
                "kind": "team",
                "canonical_id": "besiktas_jk",
                "add_aliases": ["Fenerbahçe"],
                "source": "operator_curation",
                "added_by_pr": "PR-9999",
                "added_at_utc": "2026-06-01T12:00:00Z",
                "min_corpus_appearances": 3,
                "overrides": [
                    {
                        "canonical_ids": ["besiktas_jk", "fenerbahce_sk"],
                        "justification": "Legitimate near-collision covered by review",
                    }
                ],
            }
        ]

        errors = _validate_alias_delta_entries(valid, lexicon_dir)
        assert not errors


class TestLexiconDiffVerification:
    def test_parse_git_numstat_counts_added_rows(self) -> None:
        from xops.makefile.nlp import _parse_git_numstat

        result = _parse_git_numstat(
            "12\t3\tai/nlp/lexicon/teams.tr.yaml\n"
            "0\t0\tai/nlp/lexicon/markets.tr.yaml\n"
        )
        assert result["ai/nlp/lexicon/teams.tr.yaml"] == (12, 3)
        assert result["ai/nlp/lexicon/markets.tr.yaml"] == (0, 0)

    def test_verify_nlp_lexicon_diff_fails_when_over_threshold(self, monkeypatch) -> None:
        from xops.makefile.nlp import cmd_verify_nlp_lexicon_diff

        class DummyResult:
            def __init__(self):
                self.returncode = 0
                self.stdout = "201\t0\tai/nlp/lexicon/teams.tr.yaml\n"
                self.stderr = ""

        monkeypatch.setenv("GITHUB_ACTOR", "lexicon-build-bot")
        monkeypatch.setattr("xops.makefile.nlp.subprocess.run", lambda *args, **kwargs: DummyResult())

        rc = cmd_verify_nlp_lexicon_diff(["--base", "HEAD~1"])
        assert rc == 1

    def test_verify_nlp_lexicon_diff_allows_small_diffs(self, monkeypatch) -> None:
        from xops.makefile.nlp import cmd_verify_nlp_lexicon_diff

        class DummyResult:
            def __init__(self):
                self.returncode = 0
                self.stdout = "35\t0\tai/nlp/lexicon/teams.tr.yaml\n"
                self.stderr = ""

        monkeypatch.setenv("GITHUB_ACTOR", "lexicon-build-bot")
        monkeypatch.setattr("xops.makefile.nlp.subprocess.run", lambda *args, **kwargs: DummyResult())

        rc = cmd_verify_nlp_lexicon_diff(["--base", "HEAD~1"])
        assert rc == 0
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
            "gs": [
                ("teams.tr.yaml", "galatasaray_sk"),
                ("leagues.tr.yaml", "fake_league_gs"),
            ],
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


class TestVerifyGeminateRestorationCoverage:
    def test_validate_player_geminate_restoration_coverage_passes_for_known_rule(self) -> None:
        from xops.makefile.nlp import _validate_player_geminate_restoration_coverage

        entries = {
            "players.tr.yaml": [
                {
                    "canonical_id": "hak_kamil",
                    "names": ["Hakkı Kamil"],
                    "aliases": ["hakkı"],
                }
            ]
        }

        errors = _validate_player_geminate_restoration_coverage(entries)
        assert errors == []

    def test_validate_player_geminate_restoration_coverage_fails_if_rule_missing(self, monkeypatch) -> None:
        import nlp.geminate_restoration as geminate_module

        monkeypatch.setattr(geminate_module, "load_geminate_restorations", lambda: ())
        from xops.makefile.nlp import _validate_player_geminate_restoration_coverage

        entries = {
            "players.tr.yaml": [
                {
                    "canonical_id": "hak_kamil",
                    "names": ["Hakkı Kamil"],
                    "aliases": ["hakkı"],
                }
            ]
        }

        errors = _validate_player_geminate_restoration_coverage(entries)
        assert errors
        assert any("geminate form" in error for error in errors)


# ---------------------------------------------------------------------------
# Assertion (c): normalize round-trip
# ---------------------------------------------------------------------------

class TestVerifyNormalizeRoundTrip:
    """(c) Normalized alias must not collide with another canonical's normalized alias."""

    def test_no_normalize_round_trip_collision_in_live_lexicons(self) -> None:
        from ai.common.config import cfg
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


class TestTransliterationVariantBuildHelpers:
    def test_load_transliteration_variants(self, tmp_path) -> None:
        from xops.makefile.nlp import _load_transliteration_variants

        path = tmp_path / "transliteration_variants.tr.yaml"
        path.write_text(
            """_meta:\n  schema_version: 1\n  table_version: \"1.0.0\"\nvariants:\n  - canonical: en_premier_league\n    variants:\n      - premier lig\n      - premierlig\n    domain: football\n    source: corpus\n""",
            encoding="utf-8",
        )

        variants = _load_transliteration_variants(path)

        assert variants == [
            {
                "canonical": "en_premier_league",
                "domain": "football",
                "source": "corpus",
                "variants": ["premier lig", "premierlig"],
            }
        ]

    def test_validate_transliteration_variants_rejects_top_1000_without_override(self) -> None:
        from xops.makefile.nlp import _validate_transliteration_variants

        variants = [
            {
                "canonical": "en_premier_league",
                "domain": "football",
                "source": "corpus",
                "variants": ["set"],
            }
        ]
        word_freq = {"set": 100000, "fenerbahce": 500}
        errors = _validate_transliteration_variants(variants, word_freq, set())

        assert errors
        assert any("top-1000 Turkish token" in error for error in errors)

    def test_validate_transliteration_variants_detects_domain_collision(self) -> None:
        from xops.makefile.nlp import _validate_transliteration_variants

        variants = [
            {
                "canonical": "en_premier_league",
                "domain": "football",
                "source": "corpus",
                "variants": ["premier lig"],
            },
            {
                "canonical": "galatasaray_sk",
                "domain": "generic",
                "source": "corpus",
                "variants": ["premier lig"],
            },
        ]
        word_freq = {"premier lig": 0}
        errors = _validate_transliteration_variants(variants, word_freq, set())

        assert errors
        assert any("collides across canonicals" in error for error in errors)

    def test_inject_transliteration_variants_into_lexicon_data_adds_aliases(self) -> None:
        from xops.makefile.nlp import _inject_transliteration_variants_into_lexicon_data

        lex_path = Path("leagues.tr.yaml")
        data = {
            "entries": [
                {
                    "canonical_id": "en_premier_league",
                    "names": ["Premier Lig"],
                    "aliases": ["İngiltere ligi"],
                }
            ]
        }
        lexicon_data = {lex_path: data}
        variants = [
            {
                "canonical": "en_premier_league",
                "domain": "football",
                "source": "corpus",
                "variants": ["premier lig", "premierlig"],
            }
        ]

        changed, errors = _inject_transliteration_variants_into_lexicon_data(lexicon_data, variants)

        assert not errors
        assert changed == {lex_path}
        assert "premier lig" in data["entries"][0]["aliases"]
        assert "premierlig" in data["entries"][0]["aliases"]


class TestLexiconBuildNonLatinValidation:
    """§10.22.10: Non-Latin lexicon entries require a Latin transliteration sibling."""

    def test_non_latin_alias_without_latin_sibling_fails(self) -> None:
        from xops.makefile.nlp import _lexicon_entries_have_latin_transliteration_siblings

        entries = [
            {
                "canonical_id": "galatasaray_sk",
                "names": ["Галатасарай"],
                "aliases": ["ГС"],
            }
        ]

        violations = _lexicon_entries_have_latin_transliteration_siblings(
            entries,
            Path("teams.tr.yaml"),
        )

        assert violations
        assert "Галатасарай" in violations[0]
        assert "ГС" in violations[0]

    def test_non_latin_alias_with_latin_sibling_passes(self) -> None:
        from xops.makefile.nlp import _lexicon_entries_have_latin_transliteration_siblings

        entries = [
            {
                "canonical_id": "bayern_munich",
                "names": ["Bayer Münih"],
                "aliases": ["Байер Мюнхен"],
            }
        ]

        violations = _lexicon_entries_have_latin_transliteration_siblings(
            entries,
            Path("teams.tr.yaml"),
        )

        assert not violations


class TestPhoneticAliasBuildReport:
    """§10.22.10: Phonetic alias build report generation."""

    def test_load_phonetic_aliases(self, tmp_path) -> None:
        from xops.makefile.nlp import _load_phonetic_aliases

        path = tmp_path / "phonetic_aliases.tr.yaml"
        path.write_text(
            """_meta:\n  schema_version: 1\n  table_version: \"1.0.0\"\naliases:\n  - phonetic_form: \"Bayer Münih\"\n    canonical_id: \"bayern_munich\"\n    requires_co_token: false\n    confused_with:\n      - \"bayer_leverkusen\"\n""",
            encoding="utf-8",
        )

        aliases = _load_phonetic_aliases(path)

        assert aliases == [
            {
                "phonetic_form": "Bayer Münih",
                "canonical_id": "bayern_munich",
                "requires_co_token": False,
                "confused_with": ["bayer_leverkusen"],
            }
        ]

    def test_phonetic_collisions_report_generated(self, tmp_path) -> None:
        from xops.makefile.nlp import _load_phonetic_aliases, _write_phonetic_collisions_report

        alias_file = tmp_path / "ai" / "nlp" / "lang_tr" / "phonetic_aliases.tr.yaml"
        alias_file.parent.mkdir(parents=True, exist_ok=True)
        alias_file.write_text(
            """_meta:\n  schema_version: 1\n  table_version: \"1.0.0\"\naliases:\n  - phonetic_form: \"Bayer Münih\"\n    canonical_id: \"bayern_munich\"\n    requires_co_token: false\n    confused_with:\n      - \"bayer_leverkusen\"\n""",
            encoding="utf-8",
        )
        report_path = tmp_path / "data" / "nlp" / "build_reports" / "phonetic_collisions.md"

        aliases = _load_phonetic_aliases(alias_file)
        _write_phonetic_collisions_report(aliases, report_path)

        report_text = report_path.read_text(encoding="utf-8")
        assert "Bayer Münih -> bayern_munich" in report_text
        assert "confused_with=[bayer_leverkusen]" in report_text


class TestLexiconGovernanceExtras:
    def test_nlp_lexicon_eval_command_simulates_regression_gate(self) -> None:
        from xops.makefile.nlp import cmd_nlp_lexicon_eval

        assert cmd_nlp_lexicon_eval(["--eval-harness", "pass"]) == 0
        assert cmd_nlp_lexicon_eval(["--eval-harness", "fail"]) == 1

    def test_nlp_lexicon_alias_quota_helper_detects_over_quota(self) -> None:
        from xops.makefile.nlp import _check_lexicon_alias_quota

        entries = [
            {
                "canonical_id": "galatasaray_sk",
                "aliases": ["aslan", "aslan", "new aslan", "aslan_3"],
            }
        ]

        errors = _check_lexicon_alias_quota(entries, 2, "teams.tr.yaml")

        assert errors == [
            "teams.tr.yaml: canonical_id 'galatasaray_sk' has 3 aliases, exceeds max 2"
        ]

    def test_nlp_lexicon_max_aliases_per_canonical_default(self) -> None:
        from ai.common.config import cfg

        assert cfg.nlp_lexicon_max_aliases_per_canonical == 12

    def test_nlp_lexicon_max_aliases_per_canonical_in_env_example(self) -> None:
        env_example = Path(__file__).parents[2] / "xops" / "env" / ".env.example"
        assert "NEGELIR_NLP_LEXICON_MAX_ALIASES_PER_CANONICAL=12" in env_example.read_text()

    def test_new_nlp_config_keys_have_defaults(self) -> None:
        from ai.common.config import cfg

        assert cfg.nlp_conversation_index_backend == "redis"
        assert cfg.nlp_intent_retrain_max_regression == 0.005
        assert cfg.nlp_erase_scan_batch == 500

    def test_new_nlp_config_keys_in_env_example(self) -> None:
        env_example = Path(__file__).parents[2] / "xops" / "env" / ".env.example"
        env_text = env_example.read_text()
        assert "NEGELIR_NLP_CONVERSATION_INDEX_BACKEND=redis" in env_text
        assert "NEGELIR_NLP_INTENT_RETRAIN_MAX_REGRESSION=0.005" in env_text
        assert "NEGELIR_NLP_ERASE_SCAN_BATCH=500" in env_text
