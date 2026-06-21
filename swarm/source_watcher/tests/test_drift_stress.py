"""Drift stress harness for the source_watcher (Phase 2 deep-review).

This is NOT a unit test. It's an executable scenario catalogue: each
case takes the real captured openfootball seed (or a fake HTML payload),
mutates it the way a real upstream source might mutate, runs the
*integrated* pipeline (snapshot_store → differ → classifier → planner)
and asserts what the watcher decided.

Cases marked ``xfail(strict=True)`` document KNOWN BLIND SPOTS — they
must keep failing until the underlying issue is fixed; if one starts
passing, pytest will go red so we notice.

Run: ``pytest ai/swarm/source_watcher/tests/test_drift_stress.py -v``
"""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from typing import Any, Callable, List, Tuple

import pytest

from swarm.source_watcher import snapshot_store
from swarm.source_watcher.classifier import (
    COSMETIC,
    SCHEMA_BREAKING,
    SEMANTIC,
    classify,
)
from swarm.source_watcher.differ import diff_json
from swarm.source_watcher.planner import (
    ACTION_OPEN_TICKET,
    ACTION_PAGE_HUMAN,
    ACTION_REFRESH_FIXTURES,
    ACTION_RUN_PARITY_TESTS,
    ACTION_SKIP,
    plan,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
OPENFOOTBALL_SEED = REPO_ROOT / "infra" / "mock" / "seeds" / "openfootball" / "tr1_2024_25.json"


# ── fixtures ────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def baseline_json() -> dict:
    """The real captured openfootball seed."""
    return json.loads(OPENFOOTBALL_SEED.read_text(encoding="utf-8"))


@pytest.fixture
def history_root(tmp_path) -> Path:
    return tmp_path / "history"


def _run_pipeline(source: str, baseline: Any, mutated: Any, root: Path):
    """Snapshot baseline + mutated, return the planner's verdict.

    When ``mutated`` is byte-identical to ``baseline``, the snapshot store
    de-duplicates and ``previous()`` returns ``None``. We model that as
    "empty diff list" and run the planner directly so the cosmetic / SKIP
    contract is still asserted.
    """
    snapshot_store.store(source, baseline, root=root, now="2026-04-20T10-00-00Z")
    snapshot_store.store(source, mutated, root=root, now="2026-04-20T10-00-05Z")
    prev = snapshot_store.previous(source, root=root)
    last = snapshot_store.latest(source, root=root)
    if prev is None or prev.sha256 == last.sha256:
        # identical payload — simulate an empty diff cycle.
        diffs = []
    else:
        diffs = diff_json(prev.payload, last.payload)
    classified = classify(diffs)
    return plan(source, classified), classified, diffs


# ── JSON mutators (drive openfootball-style payloads) ───────────


def m_identical(p):
    return copy.deepcopy(p)


def m_whitespace_only(p):
    """Round-trip through json with different sort/indent — bytes change, semantics don't."""
    return json.loads(json.dumps(p, indent=4, sort_keys=False))


def m_added_field(p):
    out = copy.deepcopy(p)
    out["season_winner"] = "Galatasaray"
    return out


def m_removed_required(p):
    out = copy.deepcopy(p)
    if out.get("matches"):
        out["matches"][0].pop("team1", None)
    return out


def m_type_flip_score(p):
    """`score.ft: [2, 1]` → `score.ft: "2-1"` (real-world Yahoo→ESPN drift)."""
    out = copy.deepcopy(p)
    for m in out.get("matches", []):
        if isinstance(m.get("score", {}).get("ft"), list):
            ft = m["score"]["ft"]
            m["score"]["ft"] = f"{ft[0]}-{ft[1]}"
    return out


def m_number_to_string(p):
    """`score.ht[0]: 0` → `score.ht[0]: "0"` — same value, type changed."""
    out = copy.deepcopy(p)
    for m in out.get("matches", []):
        ht = m.get("score", {}).get("ht")
        if isinstance(ht, list) and ht and isinstance(ht[0], int):
            ht[0] = str(ht[0])
    return out


def m_match_reorder(p):
    """Swap matches[0] and matches[1] — schema unchanged, order changed."""
    out = copy.deepcopy(p)
    if len(out.get("matches", [])) >= 2:
        out["matches"][0], out["matches"][1] = out["matches"][1], out["matches"][0]
    return out


def m_added_match(p):
    """Append a brand-new match (legitimate weekly upstream update)."""
    out = copy.deepcopy(p)
    if out.get("matches"):
        new_m = copy.deepcopy(out["matches"][-1])
        new_m["date"] = "2026-04-25"
        out["matches"].append(new_m)
    return out


def m_removed_match(p):
    """Drop the oldest match (legitimate season-end pruning)."""
    out = copy.deepcopy(p)
    if out.get("matches"):
        out["matches"] = out["matches"][1:]
    return out


def m_diacritic_loss(p):
    """`Beşiktaş` → `Besiktas` (encoding drift)."""
    out = copy.deepcopy(p)
    for m in out.get("matches", []):
        for k in ("team1", "team2"):
            if isinstance(m.get(k), str):
                m[k] = (m[k].replace("ş", "s").replace("Ş", "S")
                              .replace("ı", "i").replace("İ", "I")
                              .replace("ğ", "g").replace("Ğ", "G")
                              .replace("ü", "u").replace("Ü", "U")
                              .replace("ö", "o").replace("Ö", "O")
                              .replace("ç", "c").replace("Ç", "C"))
    return out


def m_id_collision(p):
    """Swap match[0] and match[1] team1/team2 — fixture corruption."""
    out = copy.deepcopy(p)
    if len(out.get("matches", [])) >= 2:
        out["matches"][0]["team1"], out["matches"][1]["team1"] = (
            out["matches"][1]["team1"], out["matches"][0]["team1"],
        )
    return out


def m_silent_truncation(p):
    """Catastrophe: matches list cut from N to 2 — many removed records."""
    out = copy.deepcopy(p)
    if out.get("matches"):
        out["matches"] = out["matches"][:2]
    return out


def m_envelope_wrap(p):
    """Top-level `{matches: [...]}` becomes `{data: {matches: [...]}}`."""
    return {"data": copy.deepcopy(p)}


def m_locale_swap(p):
    """Date format US → ISO (very common Excel-export drift)."""
    out = copy.deepcopy(p)
    for m in out.get("matches", []):
        if isinstance(m.get("date"), str) and "-" in m["date"]:
            y, mo, d = m["date"].split("-")
            m["date"] = f"{mo}/{d}/{y}"
    return out


# ── HTML / status-code scenarios (faked seeds; not on disk) ─────


# These mimic what watch.run currently captures: the {_raw_len, _suffix} stub
# plus, after the proposed fix, sha256+status from the headers sidecar.

def html_baseline():
    return {
        "home": {
            "_raw_len": 117019,
            "_suffix": ".html",
            "_sha256": "699cfe33aa" + "0" * 54,  # length matches real
            "_status": 200,
        }
    }


def m_html_one_byte(p):
    out = copy.deepcopy(p)
    out["home"]["_raw_len"] += 1
    out["home"]["_sha256"] = "deadbeef" + "0" * 56
    return out


def m_html_dom_overhaul_same_size(p):
    """**The blind spot**: total DOM rewrite, identical byte count."""
    out = copy.deepcopy(p)
    # _raw_len stays the same — only sha256 changes (after the fix)
    out["home"]["_sha256"] = "ca11ed9e" + "0" * 56
    return out


def m_html_cloudflare_challenge(p):
    """200 OK with Cloudflare challenge body — anti-bot soft block."""
    out = copy.deepcopy(p)
    out["home"]["_raw_len"] = 14_000  # typical CF challenge size
    out["home"]["_sha256"] = "c10ud" + "f" * 59
    out["home"]["_status"] = 200  # the trap: status looks fine
    return out


def m_status_200_to_503(p):
    """Same body, status flips 200 → 503."""
    out = copy.deepcopy(p)
    out["home"]["_status"] = 503
    return out


# ── scenario table ──────────────────────────────────────────────


Mutator = Callable[[Any], Any]
SCENARIOS: List[Tuple[str, str, Mutator, str, set, str]] = [
    # id,                        domain, mutator,                   expected_severity,        must_include_actions,                                rationale
    ("S1_identical",             "json", m_identical,               COSMETIC,                 {ACTION_SKIP},                                       "no diff → no work"),
    ("S2_whitespace_only",       "json", m_whitespace_only,         COSMETIC,                 {ACTION_SKIP},                                       "JSON canonicalization absorbs reformatting"),
    ("S3_added_field",           "json", m_added_field,             SEMANTIC,                 {ACTION_RUN_PARITY_TESTS, ACTION_REFRESH_FIXTURES},  "new top-level field is benign drift"),
    ("S4_removed_required",      "json", m_removed_required,        SCHEMA_BREAKING,          {ACTION_OPEN_TICKET, ACTION_PAGE_HUMAN},             "missing required field is a real break"),
    ("S5_type_flip_score",       "json", m_type_flip_score,         SCHEMA_BREAKING,          {ACTION_OPEN_TICKET, ACTION_PAGE_HUMAN},             "list→string for score is a real break"),
    ("S6_number_to_string",      "json", m_number_to_string,        SEMANTIC,                 {ACTION_RUN_PARITY_TESTS},                           "1 → '1' is a coercion most scrapers absorb"),
    ("S7_match_reorder",         "json", m_match_reorder,           SEMANTIC,                 {ACTION_RUN_PARITY_TESTS},                           "row reorder ≠ schema break"),
    ("S8_added_match",           "json", m_added_match,             SEMANTIC,                 {ACTION_RUN_PARITY_TESTS, ACTION_REFRESH_FIXTURES},  "new match each week is normal upstream growth"),
    pytest.param(
        "S9_removed_match",      "json", m_removed_match,           SEMANTIC,                 {ACTION_RUN_PARITY_TESTS},                           "season-end pruning is normal",
        marks=pytest.mark.xfail(strict=True, reason="KNOWN LIMITATION: positional list diff treats heterogeneous-schema row shifts as dict-key add/remove → false SCHEMA_BREAKING. Fix needs identity-aware list diff (Phase 2.8.6 follow-up)."),
    ),
    ("S10_diacritic_loss",       "json", m_diacritic_loss,          SEMANTIC,                 {ACTION_RUN_PARITY_TESTS},                           "ş → s is encoding drift, recover by NFC"),
    pytest.param(
        "S11_id_collision",      "json", m_id_collision,            SCHEMA_BREAKING,          {ACTION_PAGE_HUMAN},                                 "team mix-up is silent corruption — must page",
        marks=pytest.mark.xfail(strict=True, reason="KNOWN LIMITATION: deterministic rules cannot detect entity-swap silent corruption; needs Phase 8 LLM narrator + cross-source proofreader"),
    ),
    ("S12_silent_truncation",    "json", m_silent_truncation,       SCHEMA_BREAKING,          {ACTION_OPEN_TICKET, ACTION_PAGE_HUMAN},             "list shrinks from N to 2 — likely truncation"),
    ("S13_envelope_wrap",        "json", m_envelope_wrap,           SCHEMA_BREAKING,          {ACTION_OPEN_TICKET, ACTION_PAGE_HUMAN},             "wrap-in-envelope breaks every selector"),
    ("S14_locale_swap",          "json", m_locale_swap,             SEMANTIC,                 {ACTION_RUN_PARITY_TESTS},                           "ISO → US dates needs a parser update, not a rewrite"),
    ("H1_html_byte_identical",   "html", m_identical,               COSMETIC,                 {ACTION_SKIP},                                       "no change → no work"),
    ("H2_html_one_byte",         "html", m_html_one_byte,           COSMETIC,                 {ACTION_SKIP},                                       "1-byte cosmetic edit (e.g. nbsp tweak)"),
    ("H3_html_dom_overhaul_same_size", "html", m_html_dom_overhaul_same_size, SCHEMA_BREAKING, {ACTION_PAGE_HUMAN},                                 "BLIND SPOT: full DOM rewrite at identical byte count"),
    ("H4_html_cloudflare_chal",  "html", m_html_cloudflare_challenge, SCHEMA_BREAKING,        {ACTION_PAGE_HUMAN},                                 "200 OK + CF challenge body == data blackout"),
    ("ST1_status_200_to_503",    "html", m_status_200_to_503,       SCHEMA_BREAKING,          {ACTION_PAGE_HUMAN},                                 "503 with old body cached must trip the watcher"),
]


# ── parametrized executor ───────────────────────────────────────


def _build_params():
    out = []
    for entry in SCENARIOS:
        # NB: pytest.param() returns a ParameterSet which is a NamedTuple,
        # so isinstance(entry, tuple) is True for both. Check ParameterSet first.
        if hasattr(entry, "values") and hasattr(entry, "marks"):
            out.append(entry)
        else:
            out.append(pytest.param(*entry, id=entry[0]))
    return out


_PARAMS = _build_params()


@pytest.mark.parametrize(
    "scenario_id,domain,mutator,expected_sev,must_actions,_rationale",
    _PARAMS,
)
def test_drift_scenario(
    scenario_id, domain, mutator, expected_sev, must_actions, _rationale,
    baseline_json, history_root,
):
    if domain == "json":
        baseline = baseline_json
    else:
        baseline = html_baseline()
    mutated = mutator(baseline)

    plan_, classified, diffs = _run_pipeline(scenario_id, baseline, mutated, history_root)

    # Helpful failure context.
    failure_ctx = (
        f"\n  scenario:  {scenario_id}\n"
        f"  rationale: {_rationale}\n"
        f"  diffs:     {len(diffs)}\n"
        f"  severity:  got={plan_.severity}  expected={expected_sev}\n"
        f"  actions:   got={plan_.actions}  must_include={must_actions}\n"
    )

    assert plan_.severity == expected_sev, failure_ctx
    missing = must_actions - set(plan_.actions)
    assert not missing, f"actions missing {missing}{failure_ctx}"
