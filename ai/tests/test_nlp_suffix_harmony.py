"""Phase 10 §10.7 — Suffix-harmony test harness.

Verifies every Turkish suffix filter in ``ai/nlp/jinja_filters_tr.py``
against a 200-row pinned golden table
(``ai/nlp/data/suffix_harmony_golden.yaml``).

Coverage categories in the golden table
-----------------------------------------
* Back-vowel (a/ı) proper nouns — e.g. Galatasaray, Beşiktaş, Adana.
* Back-rounded (o/u) proper nouns — e.g. Trabzonspor.
* Front-unrounded (e/i) proper nouns — e.g. Fenerbahçe, Başakşehir.
* Front-rounded (ö/ü) proper nouns — e.g. Büyükşehir, Türkgücü.
* Common nouns: vowel-final, voiced-consonant-final, voiceless-consonant-final.
* Terminal-consonant assimilation rows (k→ğ, p→b — current impl behaviour
  pinned; regenerate golden if the filter is intentionally extended).
* Apostrophe handling for proper nouns (e.g. "Galatasaray'da" not
  "Galatasarayda").

Drift policy
------------
Any change to ``jinja_filters_tr.py`` filter logic that alters output MUST
regenerate the golden file.  A diverging test is intentional — it forces a
deliberate update rather than silent regression.

Regenerating the golden file
-----------------------------
    PYTHONPATH=ai python3 - <<EOF
    import sys, yaml
    sys.path.insert(0, 'ai')
    from nlp.jinja_filters_tr import (
        locative, dative, ablative, accusative, genitive, plural as plural_f,
    )
    # … build rows list, dump YAML …
    EOF
(See the original generator used at Phase 10 §10.7 implementation time.)
"""
from __future__ import annotations

import pathlib
import yaml
import pytest

from nlp.jinja_filters_tr import (
    locative,
    dative,
    ablative,
    accusative,
    genitive,
    plural as plural_f,
)

_GOLDEN_PATH = pathlib.Path(__file__).parent.parent / "nlp" / "data" / "suffix_harmony_golden.yaml"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_golden() -> list[dict]:
    """Load the 200-row YAML table; fail loud if missing."""
    assert _GOLDEN_PATH.exists(), (
        f"Golden file not found: {_GOLDEN_PATH}\n"
        "Regenerate it using the generator described in this module's docstring."
    )
    with _GOLDEN_PATH.open(encoding="utf-8") as fh:
        rows = yaml.safe_load(fh)
    assert isinstance(rows, list), "Golden file must be a YAML list."
    return rows


_GOLDEN: list[dict] = _load_golden()

# ---------------------------------------------------------------------------
# Parametric golden tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("row", _GOLDEN, ids=[r["stem"] for r in _GOLDEN])
def test_locative_golden(row: dict) -> None:
    assert locative(row["stem"]) == row["locative"], (
        f"locative({row['stem']!r}) mismatch — golden drift detected"
    )


@pytest.mark.parametrize("row", _GOLDEN, ids=[r["stem"] for r in _GOLDEN])
def test_dative_golden(row: dict) -> None:
    assert dative(row["stem"]) == row["dative"], (
        f"dative({row['stem']!r}) mismatch — golden drift detected"
    )


@pytest.mark.parametrize("row", _GOLDEN, ids=[r["stem"] for r in _GOLDEN])
def test_ablative_golden(row: dict) -> None:
    assert ablative(row["stem"]) == row["ablative"], (
        f"ablative({row['stem']!r}) mismatch — golden drift detected"
    )


@pytest.mark.parametrize("row", _GOLDEN, ids=[r["stem"] for r in _GOLDEN])
def test_accusative_golden(row: dict) -> None:
    assert accusative(row["stem"]) == row["accusative"], (
        f"accusative({row['stem']!r}) mismatch — golden drift detected"
    )


@pytest.mark.parametrize("row", _GOLDEN, ids=[r["stem"] for r in _GOLDEN])
def test_genitive_golden(row: dict) -> None:
    assert genitive(row["stem"]) == row["genitive"], (
        f"genitive({row['stem']!r}) mismatch — golden drift detected"
    )


@pytest.mark.parametrize("row", _GOLDEN, ids=[r["stem"] for r in _GOLDEN])
def test_plural_golden(row: dict) -> None:
    assert plural_f(row["stem"]) == row["plural"], (
        f"plural({row['stem']!r}) mismatch — golden drift detected"
    )


# ---------------------------------------------------------------------------
# Golden-file integrity
# ---------------------------------------------------------------------------


def test_golden_has_200_rows() -> None:
    """The pinned table must contain exactly 200 rows."""
    assert len(_GOLDEN) == 200, (
        f"Expected 200 golden rows, got {len(_GOLDEN)}"
    )


def test_golden_columns_complete() -> None:
    """Every row must have all six output columns."""
    required = {"stem", "locative", "dative", "ablative", "accusative", "genitive", "plural"}
    for row in _GOLDEN:
        missing = required - set(row.keys())
        assert not missing, f"Row {row.get('stem')!r} is missing columns: {missing}"


def test_golden_stems_unique() -> None:
    """No stem appears twice in the golden table."""
    stems = [r["stem"] for r in _GOLDEN]
    assert len(stems) == len(set(stems)), "Duplicate stems in golden table"


# ---------------------------------------------------------------------------
# Apostrophe invariant — proper nouns always get apostrophe
# ---------------------------------------------------------------------------


def test_proper_nouns_have_apostrophe() -> None:
    """Every proper-noun row must contain an apostrophe in all six forms."""
    failures: list[str] = []
    for row in _GOLDEN:
        if not row["stem"][0].isupper():
            continue
        for col in ("locative", "dative", "ablative", "accusative", "genitive", "plural"):
            if "'" not in row[col]:
                failures.append(f"{row['stem']}.{col} = {row[col]!r}")
    assert not failures, "Missing apostrophe in proper-noun forms:\n" + "\n".join(failures)


# ---------------------------------------------------------------------------
# Vowel harmony invariant — suffix vowel must match harmony class
# ---------------------------------------------------------------------------

_BACK = frozenset("aıou")
_FRONT = frozenset("eiöü")


def _last_vowel(w: str) -> str | None:
    for ch in reversed(w.lower()):
        if ch in _BACK | _FRONT:
            return ch
    return None


def test_locative_vowel_harmony_class() -> None:
    """Locative suffix vowel (a/e) must match the stem's harmony class."""
    for row in _GOLDEN:
        lv = _last_vowel(row["stem"])
        if lv is None:
            continue
        # Strip apostrophe and prefix consonant to isolate suffix vowel
        suffix = row["locative"].replace(row["stem"], "").replace("'", "")
        # suffix is td + vowel, e.g. "da" or "te"
        if not suffix:
            continue
        sv = suffix[-1]  # last char of suffix is the harmony vowel
        if lv in _BACK:
            assert sv == "a", f"{row['stem']}: expected back suffix 'a', got {sv!r} (suffix={suffix!r})"
        else:
            assert sv == "e", f"{row['stem']}: expected front suffix 'e', got {sv!r} (suffix={suffix!r})"


def test_plural_vowel_harmony_class() -> None:
    """Plural suffix (-lar/-ler) vowel must match the stem's harmony class."""
    for row in _GOLDEN:
        lv = _last_vowel(row["stem"])
        if lv is None:
            continue
        suffix = row["plural"].replace(row["stem"], "").replace("'", "")
        # suffix is "lar" or "ler"
        if len(suffix) < 2:
            continue
        sv = suffix[1]  # 'a' or 'e'
        if lv in _BACK:
            assert sv == "a", f"{row['stem']}: expected back plural 'lar', got suffix={suffix!r}"
        else:
            assert sv == "e", f"{row['stem']}: expected front plural 'ler', got suffix={suffix!r}"


# ---------------------------------------------------------------------------
# Adversarial: empty string
# ---------------------------------------------------------------------------


def test_empty_string_passthrough() -> None:
    """All filters return empty string unchanged (boundary guard)."""
    for fn in (locative, dative, ablative, accusative, genitive, plural_f):
        assert fn("") == "", f"{fn.__name__}('') should return ''"
