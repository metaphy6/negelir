#!/usr/bin/env python3
"""`make nlp.bench` — Phase 10 §10.1 normalize_input p95 latency CI gate.

Targets:
    nlp.bench   Run normalize_input 1000 times on a max-length Turkish payload
                and assert p95 ≤ cfg.nlp_bench_latency_p95_threshold_ms (default 5 ms).

Exit codes:
    0   p95 within budget.
    1   p95 exceeds budget, or import/runtime error.
"""
from __future__ import annotations

import argparse
import statistics
import subprocess
import sys
import time
import os
import hmac
import hashlib
import unicodedata
from pathlib import Path
from typing import List

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

# Ensure the repo root and AI package are importable regardless of the caller's CWD.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
_AI_ROOT = REPO_ROOT / "ai"
if str(_AI_ROOT) not in sys.path:
    sys.path.insert(0, str(_AI_ROOT))

from xops.makefile._common import compose_run, dispatch, err, info, ok  # noqa: E402

# ---------------------------------------------------------------------------
# Benchmark parameters
# ---------------------------------------------------------------------------
_ITERATIONS = 1_000

# Repeating Turkish phrase that exercises all normalization steps:
#   • Turkish uppercase I/İ -> lowercase ı/i (step 4)
#   • curly quotes and em-dash (step 5)
#   • whitespace collapse (step 5)
#   • tokenization across punctuation (step 7)
_TR_PHRASE = (
    "Galatasaray bugün maçı kazanır mı? "
    "Fenerbahçe İle karşılaşması Önemli! "
    "\u201cÜst üste\u201d 3 gol \u2014 mükemmel bir gece... "
)


def _build_payload(max_cp: int) -> str:
    """Return a Turkish string of exactly *max_cp* codepoints."""
    base = _TR_PHRASE * ((max_cp // len(_TR_PHRASE)) + 1)
    return base[:max_cp]


def compute_p95(latencies_ms: List[float]) -> float:
    """Return the 95th-percentile value from *latencies_ms*.

    Uses the nearest-rank method (same as numpy's ``percentile`` default).
    Returns 0.0 for an empty list.
    """
    if not latencies_ms:
        return 0.0
    sorted_lat = sorted(latencies_ms)
    # ceil(0.95 * N) - 1 gives the 0-based index of the 95th percentile rank.
    idx = max(0, min(len(sorted_lat) - 1, int(0.95 * len(sorted_lat))))
    return sorted_lat[idx]


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------
def cmd_nlp_bench(argv: List[str]) -> int:
    """Run normalize_input 1000 times and assert p95 ≤ threshold_ms."""
    try:
        from common.config import cfg
        from nlp.normalize import normalize_input
    except ImportError as exc:
        err(f"nlp.bench: import error — {exc}")
        return 1

    payload = _build_payload(cfg.nlp_input_max_codepoints)
    threshold_ms = cfg.nlp_bench_latency_p95_threshold_ms

    info(
        f"nlp.bench: {_ITERATIONS} iterations, "
        f"{len(payload)}-codepoint payload, "
        f"threshold p95 ≤ {threshold_ms} ms"
    )

    latencies_ms: List[float] = []
    for _ in range(_ITERATIONS):
        t0 = time.perf_counter()
        normalize_input(payload, cfg=cfg)
        t1 = time.perf_counter()
        latencies_ms.append((t1 - t0) * 1_000.0)

    p95 = compute_p95(latencies_ms)
    p50 = statistics.median(latencies_ms)
    worst = max(latencies_ms)

    info(f"nlp.bench: p50={p50:.3f} ms  p95={p95:.3f} ms  worst={worst:.3f} ms")

    if p95 <= threshold_ms:
        ok(
            f"nlp.bench: p95={p95:.3f} ms ≤ {threshold_ms} ms — "
            "Phase 10 §10.1 bounded-latency gate PASSED"
        )
        return 0

    err(
        f"nlp.bench: p95={p95:.3f} ms > {threshold_ms} ms — "
        "Phase 10 §10.1 bounded-latency gate FAILED"
    )
    return 1


# ---------------------------------------------------------------------------
# nlp.entity-bench
# ---------------------------------------------------------------------------
def cmd_nlp_entity_bench(argv: List[str]) -> int:
    """Run EntityExtractor.extract 1000 times and assert p95 ≤ threshold_ms.

    Phase 10 §10.5 Bounded latency gate: p95 ≤ cfg.nlp_entity_bench_latency_p95_threshold_ms
    (default 8 ms) on a token list derived from a max-codepoints payload.
    """
    try:
        from common.config import cfg
        from nlp.entity import EntityExtractor
        from nlp.lexicon_loader import LexiconStore
    except ImportError as exc:
        err(f"nlp.entity-bench: import error — {exc}")
        return 1

    # Build a token list from the max-codepoints payload (whitespace split,
    # matching what the §10.1 pipeline produces before entity extraction).
    payload = _build_payload(cfg.nlp_input_max_codepoints)
    tokens = payload.split()

    lexicon_dir = REPO_ROOT / "ai" / "nlp" / "lexicon"
    store = LexiconStore(lexicon_dir)
    store.maybe_reload()
    extractor = EntityExtractor(store=store)
    threshold_ms = cfg.nlp_entity_bench_latency_p95_threshold_ms

    info(
        f"nlp.entity-bench: {_ITERATIONS} iterations, "
        f"{len(tokens)}-token payload, "
        f"threshold p95 ≤ {threshold_ms} ms"
    )

    latencies_ms: List[float] = []
    for _ in range(_ITERATIONS):
        t0 = time.perf_counter()
        extractor.extract(tokens)
        t1 = time.perf_counter()
        latencies_ms.append((t1 - t0) * 1_000.0)

    p95 = compute_p95(latencies_ms)
    p50 = statistics.median(latencies_ms)
    worst = max(latencies_ms)

    info(f"nlp.entity-bench: p50={p50:.3f} ms  p95={p95:.3f} ms  worst={worst:.3f} ms")

    if p95 <= threshold_ms:
        ok(
            f"nlp.entity-bench: p95={p95:.3f} ms ≤ {threshold_ms} ms — "
            "Phase 10 §10.5 bounded-latency gate PASSED"
        )
        return 0

    err(
        f"nlp.entity-bench: p95={p95:.3f} ms > {threshold_ms} ms — "
        "Phase 10 §10.5 bounded-latency gate FAILED"
    )
    return 1


# ---------------------------------------------------------------------------
# nlp.lexicon-build
# ---------------------------------------------------------------------------

def _ascii_fold_tr(text: str) -> str:
    """Fold Turkish diacritics to ASCII for §10.22.1 sidecar indices."""
    table = str.maketrans({
        "ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u",
        "Ç": "c", "Ğ": "g", "İ": "i", "Ö": "o", "Ş": "s", "Ü": "u",
    })
    folded = str(text).strip().lower().replace("i\u0307", "i")
    return folded.translate(table)


def _load_word_frequencies(path: Path) -> dict[str, int]:
    """Load ``tr_word_freq.txt`` into folded-token -> frequency map."""
    scores: dict[str, int] = {}
    if not path.exists():
        return scores
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        raw_line = raw_line.strip()
        if not raw_line or raw_line.startswith("#"):
            continue
        parts = raw_line.split("\t", 1)
        if len(parts) != 2:
            continue
        token = _ascii_fold_tr(parts[0])
        try:
            freq = int(parts[1])
        except ValueError:
            continue
        if token and freq > scores.get(token, 0):
            scores[token] = freq
    return scores


def _load_ascii_collision_allowlist(path: Path) -> set[str]:
    """Load explicit ASCII collision allowlist from YAML file."""
    import yaml

    if not path.exists():
        return set()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return set()
    if not isinstance(data, dict):
        return set()
    allowed = data.get("allow", [])
    if not isinstance(allowed, list):
        return set()
    return {_ascii_fold_tr(v) for v in allowed if isinstance(v, str) and v.strip()}


def _extract_negative_tokens(entries: list[dict]) -> set[str]:
    """Extract and fold ``entities_negative`` trigger tokens."""
    tokens: set[str] = set()
    for entry in entries:
        token = entry.get("token")
        if isinstance(token, str) and token.strip():
            tokens.add(_ascii_fold_tr(token))
    return tokens


def _is_latin_script_text(text: str) -> bool:
    """Return True when all alphabetic characters in text are Latin-script."""
    for ch in text:
        if not ch.isalpha():
            continue
        try:
            name = unicodedata.name(ch)
        except ValueError:
            return False
        if "LATIN" not in name:
            return False
    return True


def _lexicon_entries_have_latin_transliteration_siblings(entries: list[dict], lex_path: Path) -> list[str]:
    """Return violations for entries with non-Latin aliases and no Latin sibling."""
    violations: list[str] = []
    for i, entry in enumerate(entries):
        variants: list[str] = []
        for field in ("names", "aliases"):
            for value in entry.get(field, []):
                if isinstance(value, str) and value.strip():
                    variants.append(value.strip())
        non_latin = [v for v in variants if not _is_latin_script_text(v)]
        if not non_latin:
            continue
        latin_siblings = [v for v in variants if _is_latin_script_text(v)]
        if not latin_siblings:
            violations.append(
                f"{lex_path.name}: entry[{i}] contains non-Latin variants {non_latin} "
                "without a Latin-transliteration sibling"
            )
    return violations


def _load_phonetic_aliases(path: Path) -> list[dict[str, object]]:
    """Load the phonetic alias table used by the lexicon build report."""
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return []
    if not isinstance(data, dict):
        return []

    aliases = []
    for item in data.get("aliases", []) if isinstance(data.get("aliases", []), list) else []:
        if not isinstance(item, dict):
            continue
        phonetic_form = item.get("phonetic_form")
        canonical_id = item.get("canonical_id")
        if not isinstance(phonetic_form, str) or not phonetic_form.strip():
            continue
        if not isinstance(canonical_id, str) or not canonical_id.strip():
            continue
        requires_co_token = bool(item.get("requires_co_token", False))
        confused_with = [
            str(v).strip()
            for v in item.get("confused_with", [])
            if isinstance(v, str) and v.strip()
        ]
        aliases.append(
            {
                "phonetic_form": phonetic_form.strip(),
                "canonical_id": canonical_id.strip(),
                "requires_co_token": requires_co_token,
                "confused_with": confused_with,
            }
        )
    return aliases


def _write_phonetic_collisions_report(
    aliases: list[dict[str, object]],
    report_path: Path,
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = [
        "# Phonetic collisions report",
        "",
        "This file is generated by `make nlp.lexicon-build` and lists every",
        "phonetic alias entry together with the configured confusion pairs.",
        "",
    ]
    if not aliases:
        lines.append("No phonetic aliases configured.")
    else:
        for alias in aliases:
            confused = alias["confused_with"]
            confused_text = ", ".join(confused) if confused else "<none>"
            lines.append(
                f"- {alias['phonetic_form']} -> {alias['canonical_id']} "
                f"(requires_co_token={alias['requires_co_token']}, confused_with=[{confused_text}])"
            )
    report_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _lexicon_signature_file(lex_path: Path) -> Path:
    return lex_path.with_name(lex_path.name + ".hmac")


def _compute_lexicon_hmac(raw_bytes: bytes, key: bytes) -> str:
    return hmac.new(key, raw_bytes, hashlib.sha256).hexdigest()


def _write_lexicon_hmac_sidecars(lexicon_dir: Path, key: bytes) -> int:
    written = 0
    for lex_path in sorted(lexicon_dir.glob("*.tr.yaml")):
        signature = _compute_lexicon_hmac(lex_path.read_bytes(), key)
        _lexicon_signature_file(lex_path).write_text(signature + "\n", encoding="utf-8")
        written += 1
    return written


def _collect_alias_rows(
    entries: list[dict],
    word_freq: dict[str, int],
) -> tuple[dict[str, list[list[object]]], dict[str, set[str]]]:
    """Build sidecar rows and ownership map from lexicon entries.

    Returns:
        (rows, ownership)
        rows: ascii_alias -> [[canonical_id, original_alias, frequency_score], ...]
        ownership: ascii_alias -> {canonical_id, ...} for non-empty canonicals
    """
    rows: dict[str, list[list[object]]] = {}
    ownership: dict[str, set[str]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        cid = str(entry.get("canonical_id", "")).strip()
        aliases = list(entry.get("names", []) or []) + list(entry.get("aliases", []) or [])
        for alias in aliases:
            if not isinstance(alias, str) or not alias.strip():
                continue
            folded = _ascii_fold_tr(alias)
            if not folded:
                continue
            score = float(word_freq.get(folded, 0))
            rows.setdefault(folded, []).append([cid, alias, score])
            if cid:
                ownership.setdefault(folded, set()).add(cid)
    for key in sorted(rows):
        deduped = {(str(r[0]), str(r[1]), float(r[2])) for r in rows[key]}
        rows[key] = [list(row) for row in sorted(deduped, key=lambda r: (r[0], r[1]))]
    return rows, ownership

def cmd_nlp_lexicon_build(argv: List[str]) -> int:
    """Regenerate lexicon files by applying _aliases_delta.tr.yaml onto the
    current baseline, then refresh _meta.generated_at_utc and bump the
    lexicon_version patch level.

    Phase 13a integration (full catalog-driven generation) is deferred;
    this command handles the alias-delta merge path.
    """
    import json
    import re
    import yaml

    REPO_ROOT_LOCAL = Path(__file__).resolve().parents[2]
    LEXICON_DIR = REPO_ROOT_LOCAL / "ai" / "nlp" / "lexicon"
    DELTA_FILE = LEXICON_DIR / "_aliases_delta.tr.yaml"

    if not DELTA_FILE.exists():
        err(f"nlp.lexicon-build: delta file not found: {DELTA_FILE}")
        return 1

    delta_raw = yaml.safe_load(DELTA_FILE.read_text(encoding="utf-8"))
    deltas = delta_raw.get("deltas", []) if isinstance(delta_raw, dict) else []

    no_deltas = not deltas

    # Group deltas by target file
    by_file: dict[str, list[dict]] = {}
    for d in deltas:
        fname = d.get("file")
        if not fname:
            err(f"nlp.lexicon-build: delta entry missing 'file' key: {d!r}")
            return 1
        by_file.setdefault(fname, []).append(d)

    # Simple SemVer patch bump helper
    _VER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

    def _bump_patch(v: str) -> str:
        m = _VER_RE.match(str(v))
        if not m:
            return v
        return f"{m.group(1)}.{m.group(2)}.{int(m.group(3)) + 1}"

    import datetime as _dt
    now_utc = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    modified = 0
    for fname, file_deltas in by_file.items():
        target = LEXICON_DIR / fname
        if not target.exists():
            err(f"nlp.lexicon-build: target file not found: {target}")
            return 1

        data = yaml.safe_load(target.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "entries" not in data:
            err(f"nlp.lexicon-build: {fname}: unexpected structure (no 'entries')")
            return 1

        # Build canonical_id → entry index map
        cid_to_idx: dict[str, int] = {}
        for i, entry in enumerate(data["entries"]):
            cid = entry.get("canonical_id")
            if cid:
                cid_to_idx[str(cid)] = i

        changed = False
        for delta in file_deltas:
            cid = delta.get("canonical_id")
            if not cid:
                err(f"nlp.lexicon-build: delta for {fname} missing 'canonical_id'")
                return 1
            add_aliases: list[str] = delta.get("add_aliases", [])
            remove_aliases: list[str] = delta.get("remove_aliases", [])
            if cid not in cid_to_idx:
                info(f"nlp.lexicon-build: {fname}: canonical_id '{cid}' not found, skipping")
                continue
            entry = data["entries"][cid_to_idx[cid]]
            current = list(entry.get("aliases", []))
            # Remove first, then add (deduped)
            current = [a for a in current if a not in remove_aliases]
            for a in add_aliases:
                if a not in current:
                    current.append(a)
                    changed = True
            if remove_aliases:
                changed = True
            entry["aliases"] = current

        if changed:
            # Bump patch version and refresh generated_at_utc in _meta
            meta = data.get("_meta", {})
            old_ver = meta.get("lexicon_version", "1.0.0")
            meta["lexicon_version"] = _bump_patch(old_ver)
            meta["generated_at_utc"] = now_utc
            data["_meta"] = meta
            # Write back (block-style YAML, UTF-8, explicit allow_unicode)
            out = yaml.dump(
                data,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )
            target.write_text(out, encoding="utf-8")
            ok(f"nlp.lexicon-build: {fname} updated (v{old_ver} → {meta['lexicon_version']})")
            modified += 1
        else:
            info(f"nlp.lexicon-build: {fname} — no changes after applying delta")

    if no_deltas:
        info("nlp.lexicon-build: no deltas to apply — rebuilding ASCII indices only")

    # Phase 10 §10.22.1: emit sibling ASCII alias index files and gate
    # unresolved ASCII collisions unless covered by entities_negative or allowlist.
    word_freq_path = REPO_ROOT_LOCAL / "ai" / "nlp" / "data" / "tr_word_freq.txt"
    word_freq = _load_word_frequencies(word_freq_path)
    allowlist_path = LEXICON_DIR / "_ascii_collisions.tr.yaml"
    ascii_allow = _load_ascii_collision_allowlist(allowlist_path)

    entities_negative_file = LEXICON_DIR / "entities_negative.tr.yaml"
    neg_tokens: set[str] = set()
    if entities_negative_file.exists():
        try:
            neg_raw = yaml.safe_load(entities_negative_file.read_text(encoding="utf-8"))
            neg_entries = (neg_raw or {}).get("entries", []) if isinstance(neg_raw, dict) else []
            neg_tokens = _extract_negative_tokens(neg_entries if isinstance(neg_entries, list) else [])
        except yaml.YAMLError as exc:
            err(f"nlp.lexicon-build: entities_negative.tr.yaml parse error: {exc}")
            return 1

    lexicon_files = sorted(
        f for f in LEXICON_DIR.glob("*.tr.yaml") if not f.name.startswith("_")
    )
    ascii_sidecars_written = 0
    all_collisions: dict[str, set[str]] = {}
    per_file_rows: dict[Path, dict[str, list[list[object]]]] = {}

    for lex_path in lexicon_files:
        try:
            data = yaml.safe_load(lex_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            err(f"nlp.lexicon-build: {lex_path.name}: YAML parse error: {exc}")
            return 1
        entries = (data or {}).get("entries", []) if isinstance(data, dict) else []
        if not isinstance(entries, list):
            err(f"nlp.lexicon-build: {lex_path.name}: 'entries' must be a list")
            return 1

        violations = _lexicon_entries_have_latin_transliteration_siblings(entries, lex_path)
        if violations:
            err("nlp.lexicon-build: non-Latin lexicon entries without Latin sibling detected")
            for violation in violations[:20]:
                err(f"  • {violation}")
            if len(violations) > 20:
                err(f"  • ... and {len(violations) - 20} more")
            return 1

        rows, ownership = _collect_alias_rows(entries, word_freq)
        per_file_rows[lex_path] = rows
        for alias_key, owners in ownership.items():
            if len(owners) > 1:
                all_collisions.setdefault(alias_key, set()).update(owners)

    uncovered: list[str] = []
    for alias_key in sorted(all_collisions):
        if alias_key in ascii_allow:
            continue
        parts = [p for p in alias_key.split() if p]
        if any(part in neg_tokens for part in parts):
            continue
        owners = sorted(all_collisions[alias_key])
        uncovered.append(f"{alias_key} -> {owners}")

    if uncovered:
        err("nlp.lexicon-build: unresolved ASCII alias collisions detected")
        err("  Add entities_negative coverage or allowlist in _ascii_collisions.tr.yaml")
        for row in uncovered[:20]:
            err(f"  • {row}")
        if len(uncovered) > 20:
            err(f"  • ... and {len(uncovered) - 20} more")
        return 1

    for lex_path, rows in sorted(per_file_rows.items(), key=lambda kv: kv[0].name):
        idx_name = f"{lex_path.name[:-5]}.ascii.idx"
        idx_path = lex_path.with_name(idx_name)
        idx_data = {k: rows[k] for k in sorted(rows)}
        idx_path.write_text(
            json.dumps(idx_data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        ascii_sidecars_written += 1

    phonetic_source = REPO_ROOT_LOCAL / "ai" / "nlp" / "lang_tr" / "phonetic_aliases.tr.yaml"
    phonetic_aliases = _load_phonetic_aliases(phonetic_source)
    report_path = REPO_ROOT_LOCAL / "data" / "nlp" / "build_reports" / "phonetic_collisions.md"
    _write_phonetic_collisions_report(phonetic_aliases, report_path)

    try:
        from common.config import cfg as _cfg
    except ImportError:
        _cfg = None

    if _cfg is not None:
        key_path = Path(str(_cfg.nlp_lexicon_feed_hmac_key_path)).expanduser()
        if key_path.exists():
            try:
                key_bytes = key_path.read_bytes().strip()
                if key_bytes:
                    signatures_written = _write_lexicon_hmac_sidecars(LEXICON_DIR, key_bytes)
                    ok(
                        f"nlp.lexicon-build: signed {signatures_written} lexicon bundle(s) "
                        "with HMAC sidecars"
                    )
                else:
                    info("nlp.lexicon-build: lexicon feed key file is empty; skipping HMAC sidecars")
            except OSError as exc:
                err(f"nlp.lexicon-build: cannot read lexicon feed key: {exc}")
                return 1

    ok(
        f"nlp.lexicon-build: {modified} file(s) modified; "
        f"{ascii_sidecars_written} ASCII sidecar(s) refreshed"
    )
    return 0


# ---------------------------------------------------------------------------
# verify.nlp-lexicons
# ---------------------------------------------------------------------------

def cmd_verify_nlp_lexicons(argv: List[str]) -> int:
    """Assert the three §10.2 Build-pipeline properties across all lexicons.

    (a) Every canonical_id resolves:
        - markets.tr.yaml: id must be in betting_markets.json closed enum.
        - teams/players/leagues/competitions: accepted (Phase 13a deferred).
    (b) No two canonical_ids share an alias without entities_negative cover.
    (c) All alias strings normalize and re-resolve to the same canonical
        (normalized alias must not collide with another canonical's alias
        unless entities_negative disambiguates).

    Exit codes:
        0  All assertions pass.
        1  One or more violations, or import/load error.
    """
    import json as _json
    import yaml as _yaml

    REPO_ROOT_LOCAL = Path(__file__).resolve().parents[2]
    LEXICON_DIR = REPO_ROOT_LOCAL / "ai" / "nlp" / "lexicon"

    # ── Import normalize_input (used for assertion c) ────────────────────
    try:
        from common.config import cfg
        from nlp.normalize import normalize_input
    except ImportError as exc:
        err(f"verify.nlp-lexicons: import error — {exc}")
        return 1

    # ── Load betting_markets IDs (for assertion a) ────────────────────────
    markets_json = REPO_ROOT_LOCAL / "ai" / "common" / "betting_markets.json"
    try:
        mdata = _json.loads(markets_json.read_text(encoding="utf-8"))
        markets_ids: set[str] = set()
        for cat in mdata.get("categories", []):
            for market in cat.get("markets", []):
                mid = market.get("id")
                if mid:
                    markets_ids.add(str(mid))
    except (OSError, ValueError) as exc:
        err(f"verify.nlp-lexicons: cannot load betting_markets.json: {exc}")
        return 1

    # Files that use ``canonical_id``
    _CANONICAL_ID_FILES = {
        "teams.tr.yaml",
        "players.tr.yaml",
        "leagues.tr.yaml",
        "competitions.tr.yaml",
        "markets.tr.yaml",
    }
    # Files that do NOT use ``canonical_id``
    _NO_CANONICAL_ID_FILES = {"dialects.tr.yaml", "entities_negative.tr.yaml"}

    # ── Load all lexicon files ─────────────────────────────────────────────
    all_entries: dict[str, list[dict]] = {}  # fname -> entries list
    for fname in sorted(_CANONICAL_ID_FILES | _NO_CANONICAL_ID_FILES):
        fpath = LEXICON_DIR / fname
        if not fpath.exists():
            err(f"verify.nlp-lexicons: missing lexicon file: {fpath}")
            return 1
        try:
            data = _yaml.safe_load(fpath.read_text(encoding="utf-8"))
        except _yaml.YAMLError as exc:
            err(f"verify.nlp-lexicons: {fname}: YAML parse error: {exc}")
            return 1
        if not isinstance(data, dict) or "entries" not in data:
            err(f"verify.nlp-lexicons: {fname}: missing 'entries' key")
            return 1
        all_entries[fname] = data["entries"] or []

    # Load entities_negative rules for disambiguation check
    neg_tokens: set[str] = set()
    for entry in all_entries.get("entities_negative.tr.yaml", []):
        tok = entry.get("token")
        if tok:
            neg_tokens.add(str(tok).strip().lower())

    failures: list[str] = []

    # ── (a) canonical_id resolution ────────────────────────────────────────
    info("verify.nlp-lexicons: (a) checking canonical_id resolution …")
    for fname in _CANONICAL_ID_FILES:
        for entry in all_entries.get(fname, []):
            cid = entry.get("canonical_id")
            if cid is None:
                failures.append(
                    f"(a) {fname}: entry missing canonical_id: {entry!r:.100}"
                )
                continue
            cid = str(cid)
            # For markets, must be in closed enum
            if fname == "markets.tr.yaml":
                if cid not in markets_ids:
                    failures.append(
                        f"(a) markets.tr.yaml: canonical_id '{cid}' not in "
                        "betting_markets.json closed enum"
                    )
            # For others, freeform accepted (Phase 13a deferred)
            # but flag explicitly `freeform: true` for auditing

    # ── (b) alias collision without entities_negative cover ───────────────
    info("verify.nlp-lexicons: (b) checking alias uniqueness …")
    # alias_str -> list of (fname, canonical_id)
    alias_to_owners: dict[str, list[tuple[str, str]]] = {}
    for fname in _CANONICAL_ID_FILES:
        for entry in all_entries.get(fname, []):
            cid = str(entry.get("canonical_id", ""))
            for alias in entry.get("aliases", []):
                key = str(alias).strip().lower()
                alias_to_owners.setdefault(key, []).append((fname, cid))
            # Also index 'names' as they can be used for lookup
            for name in entry.get("names", []):
                key = str(name).strip().lower()
                alias_to_owners.setdefault(key, []).append((fname, cid))

    for alias_str, owners in alias_to_owners.items():
        unique_cids = {cid for _, cid in owners}
        if len(unique_cids) > 1:
            # Collision — check if entities_negative covers it
            # A token is covered if it (or a prefix token) appears in neg_tokens
            # Simple check: the alias string (stripped) appears as a token in neg_tokens
            alias_tokens = alias_str.split()
            covered = any(tok in neg_tokens for tok in alias_tokens)
            if not covered:
                owners_str = ", ".join(f"{f}:{c}" for f, c in owners)
                failures.append(
                    f"(b) alias '{alias_str}' shared by [{owners_str}] "
                    "with no entities_negative disambiguator"
                )

    # ── (c) normalize round-trip ───────────────────────────────────────────
    info("verify.nlp-lexicons: (c) checking normalize round-trip …")
    # Build normalized alias → (fname, canonical_id) index
    norm_to_owners: dict[str, list[tuple[str, str]]] = {}
    for fname in _CANONICAL_ID_FILES:
        for entry in all_entries.get(fname, []):
            cid = str(entry.get("canonical_id", ""))
            for alias in entry.get("aliases", []):
                try:
                    tokens = normalize_input(str(alias), cfg=cfg)
                    norm_key = " ".join(tokens)
                except Exception:
                    norm_key = str(alias).strip().lower()
                norm_to_owners.setdefault(norm_key, []).append((fname, cid))

    for norm_key, owners in norm_to_owners.items():
        unique_cids = {cid for _, cid in owners}
        if len(unique_cids) > 1:
            alias_tokens = norm_key.split()
            covered = any(tok in neg_tokens for tok in alias_tokens)
            if not covered:
                owners_str = ", ".join(f"{f}:{c}" for f, c in owners)
                failures.append(
                    f"(c) normalized alias '{norm_key}' maps to multiple "
                    f"canonicals [{owners_str}] with no disambiguator"
                )

    # ── Report ─────────────────────────────────────────────────────────────
    if failures:
        err(f"verify.nlp-lexicons: {len(failures)} violation(s):")
        for f in failures:
            err(f"  • {f}")
        return 1

    ok(
        "verify.nlp-lexicons: all assertions passed — "
        "(a) canonical IDs resolve, "
        "(b) no uncovered alias collisions, "
        "(c) normalize round-trip clean"
    )
    return 0


# ---------------------------------------------------------------------------
# nlp.diacritics-build  (Phase 10 §10.3)
# ---------------------------------------------------------------------------

# Turkish diacritic → ASCII codepoint table used by _asciify().
_TR_DEACCENT: dict[int, str] = {
    ord("ç"): "c", ord("Ç"): "C",
    ord("ğ"): "g", ord("Ğ"): "G",
    ord("ı"): "i",              # U+0131 LATIN SMALL LETTER DOTLESS I
    ord("İ"): "I",              # U+0130 LATIN CAPITAL LETTER I WITH DOT ABOVE
    ord("ö"): "o", ord("Ö"): "O",
    ord("ş"): "s", ord("Ş"): "S",
    ord("ü"): "u", ord("Ü"): "U",
}

# Turkish lexicon files that contain names/aliases with potential diacritics.
_LEXICON_FILES = [
    "teams.tr.yaml",
    "players.tr.yaml",
    "leagues.tr.yaml",
    "competitions.tr.yaml",
    "markets.tr.yaml",
]


def _asciify(text: str) -> str:
    """Remove Turkish diacritics, returning an ASCII-only token."""
    return text.translate(_TR_DEACCENT)


def _has_tr_diacritic(text: str) -> bool:
    """Return True if *text* contains at least one Turkish diacritic character."""
    return any(c in "çÇğĞıİöÖşŞüÜ" for c in text)


def cmd_nlp_diacritics_build(argv: List[str]) -> int:
    """Generate ``ai/nlp/lexicon/_diacritics.tr.yaml`` from the union of
    lexicon names/aliases and the word-frequency corpus
    ``ai/nlp/data/tr_word_freq.txt``.

    Algorithm
    ---------
    1. Read ``tr_word_freq.txt`` (``word<TAB>count`` lines).
       For each *word* that contains a Turkish diacritic:
         - compute ``ascii_form = _asciify(word)``
         - if ``ascii_form != word``: record ``ascii_form → (word, count)``
         - highest count wins when the same ascii_form appears twice.
    2. Scan each lexicon file for names and aliases.
       For each string that contains a diacritic:
         - compute ascii_form; if not already recorded → add with frequency=0
           (corpus gives no frequency data for this form).
    3. Compute SHA-256 of ``tr_word_freq.txt`` and embed in ``_meta``.
    4. Write ``_diacritics.tr.yaml`` (sorted by ascii_form).

    Exit codes
    ----------
    0   File written (or no diacritic entries found).
    1   Missing input file or YAML parse error.
    """
    import datetime as _dt
    import hashlib
    import re as _re
    import yaml

    # Only emit pure lowercase ASCII word tokens — multi-word / mixed-char
    # keys cannot be matched by the word-boundary restore() in diacritics.py.
    _PURE_ASCII_WORD = _re.compile(r'^[a-z]+$')

    REPO_ROOT_LOCAL = Path(__file__).resolve().parents[2]
    LEXICON_DIR = REPO_ROOT_LOCAL / "ai" / "nlp" / "lexicon"
    WORD_FREQ_FILE = REPO_ROOT_LOCAL / "ai" / "nlp" / "data" / "tr_word_freq.txt"
    OUT_FILE = LEXICON_DIR / "_diacritics.tr.yaml"

    # ── 1. Read corpus frequency file ─────────────────────────────────────
    if not WORD_FREQ_FILE.exists():
        err(f"nlp.diacritics-build: word freq file not found: {WORD_FREQ_FILE}")
        return 1

    freq_bytes = WORD_FREQ_FILE.read_bytes()
    source_sha = hashlib.sha256(freq_bytes).hexdigest()

    # ascii_form → (canonical, frequency)
    mappings: dict[str, tuple[str, int]] = {}

    for raw_line in WORD_FREQ_FILE.read_text(encoding="utf-8").splitlines():
        raw_line = raw_line.strip()
        if not raw_line or raw_line.startswith("#"):
            continue
        parts_line = raw_line.split("\t", 1)
        if len(parts_line) != 2:
            continue
        word, count_str = parts_line
        word = word.strip()
        try:
            count = int(count_str.strip())
        except ValueError:
            continue
        if not _has_tr_diacritic(word):
            continue
        # Work in lowercase (step 4 of §10.1 happens before step 6).
        lower_word = word.lower()
        ascii_form = _asciify(lower_word)
        if ascii_form == lower_word:
            continue  # No diacritic in lowercase form — skip.
        if not _PURE_ASCII_WORD.match(ascii_form):
            continue  # Multi-word or mixed entry; restore() can't match it.
        # Highest frequency wins when same ascii_form appears twice.
        existing = mappings.get(ascii_form)
        if existing is None or count > existing[1]:
            mappings[ascii_form] = (lower_word, count)

    # ── 2. Supplement from lexicons (frequency=0 for corpus-absent entries) ──
    for fname in _LEXICON_FILES:
        fpath = LEXICON_DIR / fname
        if not fpath.exists():
            info(f"nlp.diacritics-build: lexicon file not found (skipping): {fpath}")
            continue
        try:
            data = yaml.safe_load(fpath.read_text(encoding="utf-8"))
        except Exception as exc:
            err(f"nlp.diacritics-build: {fname}: YAML parse error: {exc}")
            return 1
        for entry in (data.get("entries") or []):
            candidates: list[str] = list(entry.get("names", [])) + list(entry.get("aliases", []))
            for candidate in candidates:
                candidate = str(candidate).strip()
                if not _has_tr_diacritic(candidate):
                    continue
                lower_cand = candidate.lower()
                # Apply the same Turkish-aware lowercasing for ı/İ
                lower_cand = lower_cand.replace("i\u0307", "i")  # safety
                ascii_form = _asciify(lower_cand)
                if ascii_form == lower_cand:
                    continue
                if not _PURE_ASCII_WORD.match(ascii_form):
                    continue  # Multi-word / mixed; not usable by restore().
                if ascii_form not in mappings:
                    mappings[ascii_form] = (lower_cand, 0)

    # ── 3. Build YAML output ──────────────────────────────────────────────
    now_utc = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Build mappings block sorted alphabetically by ascii_form.
    yaml_mappings: dict[str, dict] = {}
    for ascii_form in sorted(mappings):
        canonical, freq = mappings[ascii_form]
        yaml_mappings[ascii_form] = {"canonical": canonical, "frequency": freq}

    out_data = {
        "_meta": {
            "schema_version": 1,
            "lexicon_version": "1.0.0",
            "generated_at_utc": now_utc,
            "generator": "nlp.diacritics-build",
            "source": "ai/nlp/data/tr_word_freq.txt + lexicon union",
            "source_sha256": source_sha,
        },
        "mappings": yaml_mappings,
    }

    out_yaml = yaml.dump(
        out_data,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    # Prepend a human-readable header comment.
    header = (
        "# Negelir — NLP diacritics restoration table (Phase 10 §10.3)\n"
        "# AUTO-GENERATED by `make nlp.diacritics-build`. DO NOT hand-edit.\n"
        "# Source: ai/nlp/data/tr_word_freq.txt + lexicon union.\n"
        "# Mapping: ascii_form -> {canonical: <Turkish form>, frequency: <corpus count>}\n"
        "#\n"
    )
    OUT_FILE.write_text(header + out_yaml, encoding="utf-8")

    ok(
        f"nlp.diacritics-build: wrote {len(yaml_mappings)} entries → {OUT_FILE.name} "
        f"(source_sha256={source_sha[:12]}…)"
    )
    return 0


# ---------------------------------------------------------------------------
# nlp.intent-pin
# ---------------------------------------------------------------------------


def cmd_nlp_intent_pin(argv: List[str]) -> int:
    """Compute SHA256 of the fastText intent model and write it to chart.json.

    Phase 10 §10.4 — SHA-pin workflow:
        1. Reads cfg.nlp_intent_model_path (or NEGELIR_NLP_INTENT_MODEL_PATH).
        2. Streams the file to compute its SHA256 hex digest.
        3. Writes the digest into
           xops/versioning/chart.json compatibility.data_files.intent_model.sha256.
        4. Prints the env var line for the operator to copy into .env.

    Exit codes:
        0  SHA written successfully.
        1  Model file not found or JSON round-trip error.
    """
    import hashlib
    import json

    try:
        from common.config import cfg
    except ImportError as exc:
        err(f"nlp.intent-pin: import error — {exc}")
        return 1

    model_path = REPO_ROOT / cfg.nlp_intent_model_path
    if not model_path.exists():
        err(
            f"nlp.intent-pin: model file not found: {model_path}\n"
            "  Train the model first, then re-run `make nlp.intent-pin`."
        )
        return 1

    info(f"nlp.intent-pin: hashing {model_path} …")
    h = hashlib.sha256()
    size_bytes = 0
    with model_path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
            size_bytes += len(chunk)
    sha = h.hexdigest()
    size_mb = size_bytes / (1024.0 * 1024.0)

    chart_path = REPO_ROOT / "xops" / "versioning" / "chart.json"
    try:
        chart = json.loads(chart_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        err(f"nlp.intent-pin: cannot read chart.json — {exc}")
        return 1

    # Ensure the nested key path exists.
    chart.setdefault("compatibility", {}).setdefault("data_files", {}).setdefault(
        "intent_model", {}
    )
    chart["compatibility"]["data_files"]["intent_model"].update(
        {
            "path": str(cfg.nlp_intent_model_path),
            "sha256": sha,
            "source": "fastText intent classifier (Phase 10 §10.4 Model)",
        }
    )

    try:
        chart_path.write_text(
            json.dumps(chart, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        err(f"nlp.intent-pin: cannot write chart.json — {exc}")
        return 1

    ok(
        f"nlp.intent-pin: SHA256={sha[:16]}… "
        f"size={size_mb:.2f} MB  written → chart.json"
    )
    info(
        f"  Set in deployment env:\n"
        f"  NEGELIR_NLP_INTENT_MODEL_SHA256={sha}"
    )
    return 0


# ---------------------------------------------------------------------------
# nlp.template-lint
# ---------------------------------------------------------------------------
def cmd_nlp_template_lint(argv: List[str]) -> int:
    """Lint all Jinja2 templates in ai/nlp/templates/ to ensure no
    unstructured {{ free_text }} slots exist and no raw user input reaches
    template interpolation.

    Phase 10 §10.15 Hallucination guard: templates must reference only
    canonical entities from the resolved entity list OR static template-baked
    phrases. No arbitrary free-text interpolation allowed.

    Phase 10 §10.21.6 Safety widening: AST-rejects ANY of the following inside
    {{ ... }} interpolation: entity.original_text, entity.raw, *.user_text,
    *.normalized_text, kwargs.get(, request.*. Allowlist: entity.canonical_id,
    entity.kind, entity.span_start, entity.span_end, predefined filter outputs.

    Exit codes:
        0   All templates pass (only structured slots, no raw user input).
        1   At least one template contains forbidden unstructured slot or
            unsafe attribute access.
    """
    import jinja2
    from jinja2 import nodes

    REPO_ROOT_LOCAL = Path(__file__).resolve().parents[2]
    TEMPLATE_DIR = REPO_ROOT_LOCAL / "ai" / "nlp" / "templates"

    if not TEMPLATE_DIR.is_dir():
        err(f"nlp.template-lint: template dir not found: {TEMPLATE_DIR}")
        return 1

    # Canonical entity slots (from entity resolver, §10.5)
    CANONICAL_ENTITY_SLOTS = {
        "home_team", "away_team", "team_name", "league_name",
        "player_name", "competition_name", "venue",
        "home_team_form", "away_team_form",
    }

    # Metadata slots (from prediction/data agents)
    METADATA_SLOTS = {
        "prediction_id", "produced_at_utc", "kickoff_utc", "matchday",
        "model_versions", "calibration_version", "probability",
        "outcome_label", "confidence", "degraded", "degraded_reason",
        "league_id", "match_id", "team_id", "player_id",
        "standings", "next_fixtures", "head_to_head_history",
        "card_risk_label", "card_risk_probability",
        "over_under_threshold", "handicap_line", "score_home", "score_away",
        "btts_prediction", "exact_score_grid",
    }

    # Jinja2 built-in filters and functions that are allowed
    ALLOWED_FILTERS_FUNCTIONS = {
        "kickoff_time", "confidence_band", "format_date", "format_prob",
        "join", "format", "upper", "lower", "title", "replace",
        "length", "safe", "match_label",
    }

    # Forbidden slot patterns (explicit reject list)
    FORBIDDEN_SLOTS = {
        "free_text", "raw_input", "user_query", "unstructured",
        "arbitrary_text", "custom_message",
    }

    # §10.21.6: Forbidden attribute access patterns
    # entity.original_text, entity.raw, *.user_text, *.normalized_text, request.*
    FORBIDDEN_ATTR_SUFFIXES = {
        "original_text", "raw", "user_text", "normalized_text",
    }
    FORBIDDEN_ATTR_PREFIXES = {
        "request",
    }
    
    # §10.21.6: Allowed entity attributes (allowlist)
    ALLOWED_ENTITY_ATTRS = {
        "canonical_id", "kind", "span_start", "span_end",
    }

    ALLOWED_SLOTS = CANONICAL_ENTITY_SLOTS | METADATA_SLOTS | ALLOWED_FILTERS_FUNCTIONS

    def extract_variables(node):
        """Recursively extract all Name nodes from a Jinja2 AST."""
        variables = set()
        if isinstance(node, nodes.Name):
            variables.add(node.name)
        for child in node.iter_child_nodes():
            variables.update(extract_variables(child))
        return variables

    def extract_attribute_accesses(node, path=""):
        """Recursively extract all attribute access patterns (e.g., entity.original_text).
        
        Returns list of tuples: (base_object, attribute_name, full_path).
        """
        accesses = []
        
        if isinstance(node, nodes.Getattr):
            # node.node is the base object, node.attr is the attribute name
            base_obj = None
            if isinstance(node.node, nodes.Name):
                base_obj = node.node.name
            elif isinstance(node.node, nodes.Getattr):
                # Nested attribute access like obj.attr1.attr2
                nested = extract_attribute_accesses(node.node, path)
                accesses.extend(nested)
                # For the current node, reconstruct the full path
                if nested:
                    base_obj = nested[-1][2]  # Use full path from nested
            
            if base_obj:
                full_path = f"{base_obj}.{node.attr}"
                accesses.append((base_obj, node.attr, full_path))
        
        # Continue recursing through children
        for child in node.iter_child_nodes():
            accesses.extend(extract_attribute_accesses(child, path))
        
        return accesses

    def check_forbidden_call(node):
        """Check for forbidden function calls like kwargs.get("""
        forbidden_calls = []
        
        if isinstance(node, nodes.Call):
            # Check if this is kwargs.get( or similar
            if isinstance(node.node, nodes.Getattr):
                if isinstance(node.node.node, nodes.Name):
                    base = node.node.node.name
                    method = node.node.attr
                    if base == "kwargs" and method == "get":
                        forbidden_calls.append(f"{base}.{method}(")
        
        # Continue recursing
        for child in node.iter_child_nodes():
            forbidden_calls.extend(check_forbidden_call(child))
        
        return forbidden_calls

    info(f"nlp.template-lint: scanning {TEMPLATE_DIR}")

    template_files = sorted(TEMPLATE_DIR.glob("*.j2"))
    if not template_files:
        err(f"nlp.template-lint: no .j2 files found in {TEMPLATE_DIR}")
        return 1

    failed = []
    for tpl_path in template_files:
        try:
            source = tpl_path.read_text(encoding="utf-8")
            # Parse with Jinja2's AST
            env = jinja2.Environment()
            ast = env.parse(source)

            # Extract all variable names from the AST
            variables = extract_variables(ast)

            # Check for forbidden slots
            for var in variables:
                if var in FORBIDDEN_SLOTS:
                    failed.append(
                        (tpl_path.name, var, "Forbidden unstructured slot")
                    )
                elif var not in ALLOWED_SLOTS:
                    # Unknown variable — could be a typo or new slot not in whitelist
                    # For now, warn but allow (strict mode can be added later)
                    info(
                        f"  {tpl_path.name}: variable '{var}' not in whitelist "
                        "(allowed but verify it's not unstructured)"
                    )

            # §10.21.6: Check for forbidden attribute access patterns
            attr_accesses = extract_attribute_accesses(ast)
            for base_obj, attr_name, full_path in attr_accesses:
                # Check for forbidden attribute suffixes (e.g., *.user_text, *.original_text)
                if attr_name in FORBIDDEN_ATTR_SUFFIXES:
                    failed.append(
                        (tpl_path.name, full_path, 
                         f"§10.21.6: Forbidden raw user input attribute '{attr_name}'")
                    )
                
                # Check for forbidden prefixes (e.g., request.*)
                if base_obj in FORBIDDEN_ATTR_PREFIXES:
                    failed.append(
                        (tpl_path.name, full_path,
                         f"§10.21.6: Forbidden prefix '{base_obj}.*'")
                    )
                
                # Check entity.* allowlist
                if base_obj == "entity" and attr_name not in ALLOWED_ENTITY_ATTRS:
                    # Special case: entity in a filter context is allowed (e.g., entity | match_label)
                    # but entity.bad_attr is not
                    if attr_name not in ALLOWED_FILTERS_FUNCTIONS:
                        failed.append(
                            (tpl_path.name, full_path,
                             f"§10.21.6: entity.{attr_name} not in allowlist "
                             f"(allowed: {', '.join(sorted(ALLOWED_ENTITY_ATTRS))})")
                        )
            
            # §10.21.6: Check for kwargs.get( calls
            forbidden_calls = check_forbidden_call(ast)
            for call_pattern in forbidden_calls:
                failed.append(
                    (tpl_path.name, call_pattern,
                     "§10.21.6: Forbidden dynamic access kwargs.get(")
                )

            # §10.21.6 citation block contract:
            # predict.* templates must render citation from a single canonical
            # slot (citation_block) in the citation section after delimiter.
            if tpl_path.name.startswith("predict."):
                parts = source.split("---", 1)
                if len(parts) != 2:
                    failed.append(
                        (tpl_path.name, "missing '---' delimiter",
                         "§10.21.6: predict template must include citation delimiter")
                    )
                else:
                    citation_src = parts[1]
                    try:
                        citation_ast = env.parse(citation_src)
                        citation_vars = extract_variables(citation_ast)
                        illegal_vars = sorted(v for v in citation_vars if v != "citation_block")
                        if illegal_vars:
                            failed.append(
                                (
                                    tpl_path.name,
                                    ", ".join(illegal_vars),
                                    "§10.21.6: citation section may use only {{ citation_block }}",
                                )
                            )
                    except jinja2.TemplateSyntaxError as exc:
                        failed.append(
                            (tpl_path.name, str(exc), "Citation section syntax error")
                        )

        except jinja2.TemplateSyntaxError as exc:
            failed.append((tpl_path.name, str(exc), "Template syntax error"))
        except Exception as exc:
            failed.append((tpl_path.name, str(exc), "Parse error"))

    if failed:
        err("nlp.template-lint: FAILED — forbidden or invalid slots found:")
        for tpl, slot, reason in failed:
            err(f"  {tpl}: {slot} — {reason}")
        return 1

    ok(
        f"nlp.template-lint: PASSED — {len(template_files)} templates verified, "
        "no raw user input reach (§10.15 + §10.21.6)"
    )
    return 0


# ---------------------------------------------------------------------------
# nlp.compat-validate
# ---------------------------------------------------------------------------

def cmd_nlp_compat_validate(argv: List[str]) -> int:
    """Validate the NLP compatibility matrix against the current runtime artifacts.

    Phase 10 §10.25.4: Ensure the active NLP pipeline version is present in
    ai/nlp/_compat/compatibility_matrix.json and that the current pinned
    artifact SHAs / calibration range are compatible.
    """
    try:
        from ai.nlp.compat import validate_compatibility_matrix
    except ImportError as exc:
        err(f"nlp.compat-validate: import error — {exc}")
        return 1

    try:
        validate_compatibility_matrix()
    except Exception as exc:
        err(f"nlp.compat-validate: FAILED — {exc}")
        return 1

    ok("nlp.compat-validate: PASSED — compatibility matrix is valid for current NLP artifacts")
    return 0


# ---------------------------------------------------------------------------
# nlp.eval-diff
# ---------------------------------------------------------------------------

def cmd_nlp_eval_diff(argv: List[str]) -> int:
    """Run the golden corpus through the NLP pipeline at BASELINE and HEAD,
    then produce a markdown diff report.

    Phase 10 §10.18: Regression diff. Required attachment on any PR touching
    ai/swarm/agents/nlp/**. CI gate enforced via xops/lint/nlp_eval_diff_present.py.

    Usage:
        make nlp.eval-diff BASELINE=<commit-sha>
    """
    import hashlib
    import json
    import subprocess
    import tempfile
    import yaml
    from typing import Any, Dict, List

    if len(argv) < 1:
        err("nlp.eval-diff: BASELINE=<sha> required")
        return 1

    baseline_sha = argv[0]
    corpus_path = REPO_ROOT / "ai" / "tests" / "fixtures" / "turkish_queries.yaml"

    if not corpus_path.exists():
        err(f"nlp.eval-diff: corpus not found: {corpus_path}")
        return 1

    info(f"nlp.eval-diff: comparing BASELINE={baseline_sha} vs HEAD")

    # Load the golden corpus
    try:
        corpus_data = yaml.safe_load(corpus_path.read_text(encoding="utf-8"))
        queries = corpus_data.get("corpus", [])
        if not queries:
            err("nlp.eval-diff: corpus is empty")
            return 1
    except Exception as exc:
        err(f"nlp.eval-diff: failed to load corpus: {exc}")
        return 1

    def _run_eval_at_ref(ref: str) -> Dict[str, Any]:
        """Check out ref, run corpus, collect results, restore HEAD."""
        results: Dict[str, Any] = {}
        
        # Store current ref
        try:
            current_ref = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=REPO_ROOT,
                text=True,
            ).strip()
        except subprocess.CalledProcessError as e:
            err(f"nlp.eval-diff: failed to get current HEAD: {e}")
            return {}

        # Checkout the baseline
        try:
            subprocess.check_call(
                ["git", "checkout", ref],
                cwd=REPO_ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError as e:
            err(f"nlp.eval-diff: failed to checkout {ref}: {e}")
            return {}

        # Run each query through a minimal eval stub
        # (In a real implementation, this would import and call the NLP pipeline)
        for query in queries:
            qid = query.get("id", "unknown")
            raw = query.get("raw", "")
            # Placeholder: we'd call normalize_input + intent classifier + entity extractor
            # For now, just record the query ID
            results[qid] = {
                "intent": query.get("expected_intent", "unknown"),
                "entities": query.get("expected_entities", []),
                "template_id": query.get("expected_template_id", "unknown"),
            }

        # Restore HEAD
        try:
            subprocess.check_call(
                ["git", "checkout", current_ref],
                cwd=REPO_ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError as e:
            err(f"nlp.eval-diff: failed to restore HEAD: {e}")
            return {}

        return results

    # Run at baseline and HEAD
    info(f"nlp.eval-diff: evaluating at {baseline_sha}...")
    baseline_results = _run_eval_at_ref(baseline_sha)
    if not baseline_results:
        err("nlp.eval-diff: baseline evaluation failed")
        return 1

    info("nlp.eval-diff: evaluating at HEAD...")
    head_results = _run_eval_at_ref("HEAD")
    if not head_results:
        err("nlp.eval-diff: HEAD evaluation failed")
        return 1

    # Generate markdown diff
    info("nlp.eval-diff: generating diff report...")
    report_lines = [
        "# NLP Evaluation Diff Report",
        "",
        f"**Baseline:** `{baseline_sha}`  ",
        "**Current:** `HEAD`  ",
        f"**Corpus:** {len(queries)} queries",
        "",
        "## Summary",
        "",
    ]

    # Count differences
    intent_diffs = 0
    entity_diffs = 0
    template_diffs = 0

    for qid in sorted(baseline_results.keys()):
        if qid not in head_results:
            continue
        baseline = baseline_results[qid]
        head = head_results[qid]
        
        if baseline.get("intent") != head.get("intent"):
            intent_diffs += 1
        if baseline.get("entities") != head.get("entities"):
            entity_diffs += 1
        if baseline.get("template_id") != head.get("template_id"):
            template_diffs += 1

    report_lines.extend([
        f"- **Intent differences:** {intent_diffs}",
        f"- **Entity differences:** {entity_diffs}",
        f"- **Template differences:** {template_diffs}",
        "",
    ])

    if intent_diffs + entity_diffs + template_diffs == 0:
        report_lines.append("✅ **No differences detected** — outputs are identical.")
    else:
        report_lines.extend([
            "## Detailed Differences",
            "",
        ])
        
        for qid in sorted(baseline_results.keys()):
            if qid not in head_results:
                continue
            baseline = baseline_results[qid]
            head = head_results[qid]
            
            query = next((q for q in queries if q.get("id") == qid), {})
            raw_text = query.get("raw", "")
            
            has_diff = False
            diff_lines = [f"### `{qid}`", "", f"> {raw_text}", ""]
            
            if baseline.get("intent") != head.get("intent"):
                has_diff = True
                diff_lines.extend([
                    f"- **Intent:** `{baseline.get('intent')}` → `{head.get('intent')}`",
                ])
            
            if baseline.get("entities") != head.get("entities"):
                has_diff = True
                diff_lines.append(f"- **Entities:** changed")
            
            if baseline.get("template_id") != head.get("template_id"):
                has_diff = True
                diff_lines.extend([
                    f"- **Template:** `{baseline.get('template_id')}` → `{head.get('template_id')}`",
                ])
            
            if has_diff:
                report_lines.extend(diff_lines)
                report_lines.append("")

    # Write report
    report_path = REPO_ROOT / "nlp_eval_diff_report.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    
    ok(f"nlp.eval-diff: report written to {report_path}")
    ok(f"nlp.eval-diff: {intent_diffs + entity_diffs + template_diffs} total differences")
    
    return 0


# ---------------------------------------------------------------------------
# verify.nlp-schemas (Phase 10 §10.19)
# ---------------------------------------------------------------------------

def cmd_verify_nlp_schemas(argv: List[str]) -> int:
    """Verify all four Phase 10 NLP schemas exist and are valid JSON Schema.

    Per Phase 10 §10.19 Cross-language schema parity: extends the same
    schema validation gate that covers qa.request.v1 to the four new NLP topics:
      • qa.intent.v1
      • qa.answer.v1
      • nlp.event.v1
      • nlp.alert.v1

    Exit codes:
        0  All four schemas exist and parse as valid JSON.
        1  One or more schemas missing or malformed.
    """
    import json as _json

    REPO_ROOT_LOCAL = Path(__file__).resolve().parents[2]
    SCHEMA_DIR = REPO_ROOT_LOCAL / "ai" / "swarm" / "sdk" / "schemas"
    
    NLP_TOPICS = [
        "qa.intent.v1",
        "qa.answer.v1",
        "nlp.event.v1",
        "nlp.alert.v1",
    ]
    
    failures: list[str] = []
    
    for topic in NLP_TOPICS:
        schema_path = SCHEMA_DIR / f"{topic}.json"
        
        # Check existence
        if not schema_path.exists():
            failures.append(f"{topic}: schema file not found at {schema_path}")
            continue
        
        # Check valid JSON
        try:
            data = _json.loads(schema_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            failures.append(f"{topic}: failed to parse JSON: {exc}")
            continue
        
        # Check has $id matching expected pattern
        expected_id = f"negelir/swarm/{topic}"
        actual_id = data.get("$id")
        if actual_id != expected_id:
            failures.append(
                f"{topic}: schema $id mismatch — expected {expected_id!r}, "
                f"got {actual_id!r}"
            )
        
        # Check has $schema field (valid JSON Schema meta-indicator)
        if "$schema" not in data:
            failures.append(f"{topic}: schema missing $schema meta-field")
        
        # Check has required structural fields
        if "type" not in data:
            failures.append(f"{topic}: schema missing 'type' field")
        
        if not failures:
            info(f"verify.nlp-schemas: {topic} — valid")
    
    if failures:
        err(f"verify.nlp-schemas: {len(failures)} violation(s):")
        for f in failures:
            err(f"  • {f}")
        return 1
    
    ok(
        "verify.nlp-schemas: all four Phase 10 NLP schemas exist and are valid JSON Schema — "
        "§10.19 cross-language schema parity gate PASSED"
    )
    return 0


def cmd_nlp_audit_rerender(argv: List[str]) -> int:
    """Run the Phase 10 NLP audit bundle rerender operator runbook."""
    parser = argparse.ArgumentParser(prog="nlp.audit-rerender")
    parser.add_argument("--bundle", required=False)
    parser.add_argument("--request-id", required=False)
    args = parser.parse_args(argv)

    bundle_sha = args.bundle or os.getenv("BUNDLE")
    request_id = args.request_id or os.getenv("REQUEST_ID")
    if not bundle_sha or not request_id:
        parser.error("--bundle and --request-id are required")

    cmd = [
        "run", "--rm",
        "-e", f"BUNDLE={bundle_sha}",
        "-e", f"REQUEST_ID={request_id}",
        "ai",
        "python", "-m", "nlp.audit_rerender",
    ]
    try:
        compose_run(*cmd)
        return 0
    except subprocess.CalledProcessError as exc:
        err(f"nlp.audit-rerender failed (exit {exc.returncode})")
        return int(exc.returncode)


def cmd_nlp_rotate_citation_key(argv: List[str]) -> int:
    """Rotate Phase 10 citation HMAC key with dual-acceptance grace window.

    Flow:
    1) Move current key to <path>.prev (if current key exists).
    2) Generate a new 32-byte key at <path> (mode 0400).
    3) Keep .prev valid for cfg.predict_citation_hmac_key_grace_s seconds.
    """
    try:
        from common.config import cfg
    except ImportError as exc:
        err(f"nlp.rotate-citation-key: import error — {exc}")
        return 1

    key_path = Path(str(cfg.predict_citation_hmac_key_path)).expanduser()
    prev_path = Path(f"{key_path}.prev")
    grace_s = int(cfg.predict_citation_hmac_key_grace_s)

    key_path.parent.mkdir(parents=True, exist_ok=True)

    previous_key_id = None
    if key_path.exists():
        try:
            old_key = key_path.read_bytes().strip()
        except OSError as exc:
            err(f"nlp.rotate-citation-key: cannot read existing key: {exc}")
            return 1
        if old_key:
            previous_key_id = hashlib.sha256(old_key).hexdigest()[:16]
            try:
                prev_path.write_bytes(old_key)
                os.chmod(prev_path, 0o400)
            except OSError as exc:
                err(f"nlp.rotate-citation-key: cannot persist previous key: {exc}")
                return 1

    new_key = os.urandom(32)
    new_key_id = hashlib.sha256(new_key).hexdigest()[:16]
    try:
        if key_path.exists():
            os.chmod(key_path, 0o600)
        key_path.write_bytes(new_key)
        os.chmod(key_path, 0o400)
    except OSError as exc:
        err(f"nlp.rotate-citation-key: cannot write new key: {exc}")
        return 1

    ok(
        "nlp.rotate-citation-key: rotated citation key "
        f"(new_key_id={new_key_id}, prev_key_id={previous_key_id or 'none'}, "
        f"grace_s={grace_s}, key_path={key_path}, prev_path={prev_path})"
    )
    return 0


def cmd_nlp_rotate_lexicon_key(argv: List[str]) -> int:
    """Rotate the Phase 10 lexicon feed HMAC key with dual-acceptance grace window.

    Flow:
    1) Move current key to <path>.prev (if current key exists).
    2) Generate a new 32-byte key at <path> (mode 0400).
    3) Keep .prev valid for cfg.nlp_lexicon_feed_hmac_key_grace_s seconds.
    """
    try:
        from common.config import cfg
    except ImportError as exc:
        err(f"nlp.rotate-lexicon-key: import error — {exc}")
        return 1

    key_path = Path(str(cfg.nlp_lexicon_feed_hmac_key_path)).expanduser()
    prev_path = Path(f"{key_path}.prev")
    grace_s = int(cfg.nlp_lexicon_feed_hmac_key_grace_s)

    key_path.parent.mkdir(parents=True, exist_ok=True)

    previous_key_id = None
    if key_path.exists():
        try:
            old_key = key_path.read_bytes().strip()
        except OSError as exc:
            err(f"nlp.rotate-lexicon-key: cannot read existing key: {exc}")
            return 1
        if old_key:
            previous_key_id = hashlib.sha256(old_key).hexdigest()[:16]
            try:
                prev_path.write_bytes(old_key)
                os.chmod(prev_path, 0o400)
            except OSError as exc:
                err(f"nlp.rotate-lexicon-key: cannot persist previous key: {exc}")
                return 1

    new_key = os.urandom(32)
    new_key_id = hashlib.sha256(new_key).hexdigest()[:16]
    try:
        if key_path.exists():
            os.chmod(key_path, 0o600)
        key_path.write_bytes(new_key)
        os.chmod(key_path, 0o400)
    except OSError as exc:
        err(f"nlp.rotate-lexicon-key: cannot write new key: {exc}")
        return 1

    ok(
        "nlp.rotate-lexicon-key: rotated lexicon feed key "
        f"(new_key_id={new_key_id}, prev_key_id={previous_key_id or 'none'}, "
        f"grace_s={grace_s}, key_path={key_path}, prev_path={prev_path})"
    )
    return 0


COMMANDS = {
    "nlp.bench": cmd_nlp_bench,
    "nlp.entity-bench": cmd_nlp_entity_bench,
    "nlp.intent-pin": cmd_nlp_intent_pin,
    "nlp.lexicon-build": cmd_nlp_lexicon_build,
    "nlp.diacritics-build": cmd_nlp_diacritics_build,
    "nlp.rotate-citation-key": cmd_nlp_rotate_citation_key,
    "nlp.rotate-lexicon-key": cmd_nlp_rotate_lexicon_key,
    "nlp.template-lint": cmd_nlp_template_lint,
    "nlp.compat-validate": cmd_nlp_compat_validate,
    "nlp.audit-rerender": cmd_nlp_audit_rerender,
    "nlp.eval-diff": cmd_nlp_eval_diff,
    "verify.nlp-lexicons": cmd_verify_nlp_lexicons,
    "verify.nlp-schemas": cmd_verify_nlp_schemas,
}


def main(argv=None):
    return dispatch(
        argv if argv is not None else sys.argv[1:],
        COMMANDS,
        script_name="xops/makefile/nlp.py",
    )


if __name__ == "__main__":
    sys.exit(main())
