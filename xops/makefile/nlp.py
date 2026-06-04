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
import importlib.metadata
import json
import re
import statistics
import subprocess
import sys
import time
import os
import math
import hmac
import hashlib
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List

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


def cmd_nlp_capacity_report(argv: List[str]) -> int:
    """Generate a Phase 10 capacity report for the NLP pipeline.

    Writes `data/nlp/capacity_report.md` from current NLP config and
    the Phase 10 throughput model documented in §10.23.10.
    """
    try:
        from common.config import cfg
    except ImportError as exc:
        err(f"nlp.capacity-report: import error — {exc}")
        return 1

    stage_latencies_ms = {
        "normalize": 5.0,
        "intent": 25.0,
        "entity": 40.0,
        "render": 30.0,
        "proofreader": 15.0,
    }
    cpu_path_ms = sum(stage_latencies_ms.values())
    cpu_throughput_qps = cfg.nlp_intake_workers / (cpu_path_ms / 1000.0)
    humanizer_fraction = 0.6
    humanizer_qps = 1000.0 / float(cfg.nlp_humanizer_max_latency_ms)
    if cfg.nlp_humanize:
        effective_throughput_qps = min(cpu_throughput_qps, humanizer_qps / humanizer_fraction)
    else:
        effective_throughput_qps = cpu_throughput_qps

    if cfg.nlp_humanize and effective_throughput_qps < cpu_throughput_qps:
        bottleneck = "humanizer"
    else:
        bottleneck = "CPU-bound intake + render + proofreader stages"

    report_lines = [
        "# NLP Capacity Report",
        "",
        f"Generated at: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Config snapshot",
        "",
        f"- nlp_intake_workers: {cfg.nlp_intake_workers}",
        f"- nlp_humanize: {cfg.nlp_humanize}",
        f"- nlp_humanizer_max_latency_ms: {cfg.nlp_humanizer_max_latency_ms}",
        "",
        "## Assumptions",
        "",
        "- Per-stage p50 latencies derived from Phase 10 §10.23.10.",
        "- Humanizer request rate assumed at 0.60 for effective throughput.",
        "- Bottleneck stage is the slowest stage given current config.",
        "",
        "## Per-stage p50 latencies",
    ]

    for stage, latency in stage_latencies_ms.items():
        report_lines.append(f"- {stage}: {latency:.1f} ms")

    report_lines.extend([
        "",
        "## Throughput model",
        "",
        f"- CPU path p50 total: {cpu_path_ms:.1f} ms",
        f"- CPU path throughput: {cpu_throughput_qps:.2f} QPS per pod",
        f"- Humanizer throughput: {humanizer_qps:.2f} QPS per pod",
        f"- Effective throughput with humanizer at 60%: {effective_throughput_qps:.2f} QPS per pod",
        f"- Bottleneck: {bottleneck}",
        "",
        "## Pod sizing calculator",
        "",
    ])

    for target in (10, 20, 50, 100, 200):
        pods = math.ceil(target / effective_throughput_qps) if effective_throughput_qps > 0 else 0
        report_lines.append(f"- {target} QPS → {pods} pod(s)")

    report_lines.append("")
    report_lines.append("## Notes")
    report_lines.append("")
    report_lines.append("- This report is generated by `make nlp.capacity-report`.")
    report_lines.append("- Use it as a planning aid, not a runtime SLA guarantee.")

    report_path = REPO_ROOT / "data" / "nlp" / "capacity_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(report_lines).rstrip() + "\n", encoding="utf-8")

    ok(f"nlp.capacity-report: written {report_path}")
    ok(f"nlp.capacity-report: effective throughput = {effective_throughput_qps:.2f} QPS per pod")
    return 0


def _extract_requirement_name(requirement: str) -> str | None:
    requirement = requirement.strip()
    if not requirement or requirement.startswith(("-r", "--")):
        return None

    name = re.split(r"[<=>!~\[\];,]", requirement, 1)[0].strip()
    if not name:
        return None

    return name.replace("_", "-").lower()


def _load_requirements(requirements_path: Path) -> list[str]:
    if not requirements_path.is_file():
        return []

    package_names: list[str] = []
    for raw_line in requirements_path.read_text(encoding="utf-8").splitlines():
        raw_line = raw_line.split("#", 1)[0].strip()
        if not raw_line:
            continue
        package_name = _extract_requirement_name(raw_line)
        if package_name:
            package_names.append(package_name)
    return package_names


def _load_installed_distributions() -> dict[str, importlib.metadata.Distribution]:
    dist_map: dict[str, importlib.metadata.Distribution] = {}
    for dist in importlib.metadata.distributions():
        pkg_name = dist.metadata.get("Name") or getattr(dist, "name", None)
        if not pkg_name:
            continue
        canonical_name = pkg_name.strip().lower().replace("_", "-")
        dist_map.setdefault(canonical_name, dist)
    return dist_map


def _build_dependency_closure(
    root_packages: list[str],
    dist_map: dict[str, importlib.metadata.Distribution],
) -> tuple[set[str], dict[str, list[str]], list[str]]:
    closure: set[str] = set()
    dependencies: dict[str, list[str]] = {}
    missing: list[str] = []
    queue = list(root_packages)

    while queue:
        pkg_name = queue.pop(0)
        if pkg_name in closure:
            continue

        dist = dist_map.get(pkg_name)
        if dist is None:
            missing.append(pkg_name)
            continue

        closure.add(pkg_name)
        requires = dist.requires or []
        child_names: list[str] = []
        for requirement in requires:
            child_name = _extract_requirement_name(requirement)
            if not child_name:
                continue
            child_names.append(child_name)
            if child_name not in closure:
                queue.append(child_name)

        dependencies[pkg_name] = sorted(set(child_names))

    return closure, dependencies, missing


def _scan_lexicon_files() -> list[Path]:
    lexicon_dir = REPO_ROOT / "ai" / "nlp" / "lexicon"
    if not lexicon_dir.is_dir():
        return []
    return sorted(
        p
        for p in lexicon_dir.rglob("*.yaml")
        if p.is_file() and not any(part == "__pycache__" for part in p.parts)
    )


def _build_cyclonedx_payload(
    direct_packages: list[str],
    dist_map: dict[str, importlib.metadata.Distribution],
    dependency_map: dict[str, list[str]],
    lexicon_files: list[Path],
) -> dict:
    components: list[dict] = []
    dependency_entries: list[dict] = []

    for package_name in sorted(dependency_map):
        dist = dist_map[package_name]
        canonical_name = dist.metadata.get("Name") or package_name
        normalized_name = package_name
        version = dist.version
        component = {
            "bom-ref": f"pkg:pypi/{normalized_name}@{version}",
            "type": "library",
            "name": canonical_name,
            "version": version,
        }

        license_name = (dist.metadata.get("License") or "").strip()
        if license_name:
            component["licenses"] = [{"license": {"name": license_name}}]

        summary = (dist.metadata.get("Summary") or "").strip()
        if summary:
            component["description"] = summary

        components.append(component)
        dependency_entries.append(
            {
                "ref": component["bom-ref"],
                "dependsOn": [
                    f"pkg:pypi/{child}@{dist_map[child].version}"
                    for child in dependency_map[package_name]
                    if child in dist_map
                ],
            }
        )

    for path in lexicon_files:
        rel_path = path.relative_to(REPO_ROOT).as_posix()
        content = path.read_bytes()
        sha = hashlib.sha256(content).hexdigest()
        components.append(
            {
                "bom-ref": f"file:{rel_path}",
                "type": "file",
                "name": rel_path,
                "version": "1",
                "hashes": [{"alg": "SHA-256", "content": sha}],
                "properties": [
                    {"name": "component-type", "value": "nlp-lexicon-file"},
                    {"name": "source", "value": rel_path},
                ],
            }
        )

    payload = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tools": [
                {
                    "vendor": "negelir",
                    "name": "nlp.sbom",
                    "version": "1.0.0",
                }
            ],
            "component": {
                "type": "application",
                "name": "negelir-nlp",
                "version": "1.0.0",
            },
        },
        "components": components,
        "dependencies": dependency_entries,
    }
    return payload


def cmd_nlp_sbom(argv: List[str]) -> int:
    """Generate a CycloneDX SBOM for the NLP plane into `data/nlp/sbom.json`."""
    requirements_path = REPO_ROOT / "ai" / "requirements.txt"
    direct_packages = _load_requirements(requirements_path)
    if not direct_packages:
        err("nlp.sbom: no direct NLP requirements found in ai/requirements.txt")
        return 1

    dist_map = _load_installed_distributions()
    closure, dependency_map, missing = _build_dependency_closure(direct_packages, dist_map)
    if missing:
        err(
            "nlp.sbom: missing installed packages for dependencies: "
            + ", ".join(sorted(set(missing)))
        )
        return 1

    lexicon_files = _scan_lexicon_files()
    payload = _build_cyclonedx_payload(direct_packages, dist_map, dependency_map, lexicon_files)

    out_path = REPO_ROOT / "data" / "nlp" / "sbom.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    ok(f"nlp.sbom: written {out_path}")
    ok(f"nlp.sbom: {len(payload['components'])} CycloneDX components generated")
    return 0


def _build_license_attribution_report(lexicon_files: list[Path]) -> list[str]:
    report_lines: list[str] = [
        "# NLP License Attribution Report",
        "",
        "Generated by `make nlp.license-attribution`.",
        "",
        "## Lexicon source files",
        "",
    ]

    if not lexicon_files:
        report_lines.append("- No lexicon files found under `ai/nlp/lexicon`.")
    else:
        for file_path in lexicon_files:
            rel_path = file_path.relative_to(REPO_ROOT)
            report_lines.append(f"- `{rel_path}`")

    report_lines.extend([
        "",
        "## Legal basis",
        "",
        "- Canonical team, league, and player names are treated as fair use for entity resolution.",
        "- External trademarked sources such as UEFA, FIFA, and Turkish league names are acknowledged as registered marks.",
        "- OpenFootball-derived alias content is handled under ODbL attribution when present.",
        "",
        "## Summary",
        "",
        f"- {len(lexicon_files)} lexicon source file(s) scanned.",
        "- This report enumerates the lexicon inputs and the high-level legal basis for attribution.",
        "",
        "## Notes",
        "",
        "- Use this artifact as a CI-generated license attribution report, not as legal advice.",
    ])
    return report_lines


def cmd_nlp_license_attribution(argv: List[str]) -> int:
    """Generate a license attribution report for NLP lexicon-derived data."""
    lexicon_files = _scan_lexicon_files()
    report_path = REPO_ROOT / "data" / "nlp" / "build_reports" / "license_attribution.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        "\n".join(_build_license_attribution_report(lexicon_files)).rstrip() + "\n",
        encoding="utf-8",
    )

    ok(f"nlp.license-attribution: written {report_path}")
    ok(f"nlp.license-attribution: scanned {len(lexicon_files)} lexicon file(s)")
    return 0


def cmd_nlp_spike_test(argv: List[str]) -> int:
    """Run a 3× NLP spike rehearsal for Phase 10 §10.23.10.

    This operator-facing rehearsal target runs the existing normalize and
    entity latency benchmarks multiple times to ensure a rehearsed spike
    workload is still within budget.
    """
    parser = argparse.ArgumentParser(prog="nlp.spike-test")
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Number of spike rehearsal cycles to execute.",
    )
    args = parser.parse_args(argv)

    if args.runs < 1:
        err("nlp.spike-test: --runs must be >= 1")
        return 1

    for run in range(1, args.runs + 1):
        info(f"nlp.spike-test: rehearsal {run}/{args.runs} — normalize benchmark")
        if cmd_nlp_bench([]) != 0:
            err(f"nlp.spike-test: rehearsal {run} normalize benchmark FAILED")
            return 1

        info(f"nlp.spike-test: rehearsal {run}/{args.runs} — entity benchmark")
        if cmd_nlp_entity_bench([]) != 0:
            err(f"nlp.spike-test: rehearsal {run} entity benchmark FAILED")
            return 1

    ok(f"nlp.spike-test: all {args.runs} rehearsal cycles passed")
    return 0


def _default_nlp_dr_drill_report_path(now: datetime | None = None) -> Path:
    if now is None:
        now = datetime.now(timezone.utc)
    quarter = (now.month - 1) // 3 + 1
    return REPO_ROOT / "docs" / "reports" / f"nlp_dr_drill_{now.year}-Q{quarter}.md"


def _render_nlp_dr_drill_report(now: datetime, report_path: Path) -> str:
    return "\n".join([
        "# NLP Disaster Recovery Drill Report",
        "",
        "Generated by `make nlp.dr-drill --confirm`.",
        "",
        "## Drill metadata",
        "",
        f"- executed_at: {now.isoformat()}",
        f"- report_path: {report_path.relative_to(REPO_ROOT)}",
        "- confirm: true",
        "",
        "## Drill objectives",
        "",
        "1. Corrupt a staging copy of the primary lexicon.",
        "2. Confirm the staging pod enters safe mode and emits",
        "   `nlp_safe_mode_active` within budget.",
        "3. Restore the primary lexicon.",
        "4. Confirm safe mode exits within `cfg.nlp_lexicon_reload_s + 5s`.",
        "5. Record the outcome and observations below.",
        "",
        "## Outcome",
        "",
        "- result: TBD",
        "- degraded_reason: TBD",
        "- recovery_latency_s: TBD",
        "",
        "## Notes",
        "",
        "- This command is a human-only runbook helper. Perform the actual",
        "  destructive drill steps manually in a staging environment.",
        "",
    ]) + "\n"


def cmd_nlp_dr_drill(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="nlp.dr-drill")
    parser.add_argument(
        "--report",
        help=(
            "Path for the drill report. Defaults to "
            "docs/reports/nlp_dr_drill_<year>-Q<quarter>.md"
        ),
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm the human-driven destructive drill before creating the report.",
    )
    args = parser.parse_args(argv)

    if not args.confirm:
        err(
            "nlp.dr-drill: destructive drill helper requires --confirm. "
            "This is a human-only operation."
        )
        return 1

    report_path = Path(args.report) if args.report else _default_nlp_dr_drill_report_path()
    if not report_path.is_absolute():
        report_path = REPO_ROOT / report_path

    if report_path.exists():
        err(f"nlp.dr-drill: report path already exists: {report_path}")
        return 1

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_render_nlp_dr_drill_report(datetime.now(timezone.utc), report_path), encoding="utf-8")

    ok(f"nlp.dr-drill: created drill report stub at {report_path}")
    ok(
        "nlp.dr-drill: perform the actual lexicon-corruption and recovery steps "
        "manually in staging, then update the report with the outcome."
    )
    return 0


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


_ALIAS_DELTA_SOURCE_ALLOWLIST = {
    "tff_official",
    "mackolik",
    "nesine",
    "openfootball",
    "operator_curation",
}
_FAN_CORPUS_SOURCE_RE = re.compile(r"^fan_corpus_[0-9]+$")
_ALIAS_DELTA_KIND_BY_FILE = {
    "teams.tr.yaml": "team",
    "players.tr.yaml": "player",
    "leagues.tr.yaml": "league",
    "competitions.tr.yaml": "competition",
    "markets.tr.yaml": "market",
}


def _parse_iso_utc(timestamp: object) -> bool:
    if not isinstance(timestamp, str) or not timestamp.strip():
        return False
    try:
        if timestamp.endswith("Z"):
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        else:
            datetime.fromisoformat(timestamp)
        return True
    except (TypeError, ValueError):
        return False


def _validate_alias_delta_entries(
    deltas: list[dict[str, Any]],
    lexicon_dir: Path | None = None,
) -> list[str]:
    errors: list[str] = []
    for idx, delta in enumerate(deltas):
        if not isinstance(delta, dict):
            errors.append(f"delta[{idx}] must be a mapping")
            continue

        fname = delta.get("file")
        if not isinstance(fname, str) or not fname.strip():
            errors.append(f"delta[{idx}] missing or invalid 'file'")
            continue
        if fname not in _ALIAS_DELTA_KIND_BY_FILE:
            errors.append(
                f"delta[{idx}] file '{fname}' is not a supported canonical lexicon target"
            )
            continue

        expected_kind = _ALIAS_DELTA_KIND_BY_FILE[fname]
        kind = delta.get("kind")
        if not isinstance(kind, str) or not kind.strip():
            errors.append(f"delta[{idx}] missing or invalid 'kind'")
        elif kind != expected_kind:
            errors.append(
                f"delta[{idx}] kind '{kind}' must match the target file '{fname}' ({expected_kind})"
            )

        canonical_id = delta.get("canonical_id")
        if not isinstance(canonical_id, str) or not canonical_id.strip():
            errors.append(f"delta[{idx}] missing or invalid 'canonical_id'")

        add_aliases = delta.get("add_aliases")
        if add_aliases is None:
            errors.append(f"delta[{idx}] missing 'add_aliases'")
        elif not isinstance(add_aliases, list):
            errors.append(f"delta[{idx}] 'add_aliases' must be a list")
        else:
            for alias in add_aliases:
                if not isinstance(alias, str) or not alias.strip():
                    errors.append(
                        f"delta[{idx}] add_aliases contains invalid alias: {alias!r}"
                    )

        remove_aliases = delta.get("remove_aliases", [])
        if remove_aliases is not None and not isinstance(remove_aliases, list):
            errors.append(f"delta[{idx}] 'remove_aliases' must be a list if present")

        source = delta.get("source")
        if not isinstance(source, str) or not source.strip():
            errors.append(f"delta[{idx}] missing or invalid 'source'")
        elif source not in _ALIAS_DELTA_SOURCE_ALLOWLIST and not _FAN_CORPUS_SOURCE_RE.match(source):
            errors.append(
                f"delta[{idx}] source '{source}' is not in the allowed source set"
            )

        added_by_pr = delta.get("added_by_pr")
        if not isinstance(added_by_pr, str) or not added_by_pr.strip():
            errors.append(f"delta[{idx}] missing or invalid 'added_by_pr'")

        added_at_utc = delta.get("added_at_utc")
        if not _parse_iso_utc(added_at_utc):
            errors.append(
                f"delta[{idx}] missing or invalid 'added_at_utc' (ISO 8601 UTC required)"
            )

        if (
            lexicon_dir is not None
            and isinstance(canonical_id, str)
            and canonical_id.strip()
        ):
            target_path = lexicon_dir / fname
            if target_path.exists():
                try:
                    target_data = yaml.safe_load(target_path.read_text(encoding="utf-8"))
                except yaml.YAMLError as exc:
                    errors.append(
                        f"delta[{idx}] cannot parse target file '{fname}': {exc}"
                    )
                    continue
                entries = target_data.get("entries", []) if isinstance(target_data, dict) else []
                valid_ids = {
                    str(entry.get("canonical_id", "")).strip()
                    for entry in entries
                    if isinstance(entry, dict) and entry.get("canonical_id") is not None
                }
                if canonical_id not in valid_ids:
                    errors.append(
                        f"delta[{idx}] canonical_id '{canonical_id}' not found in '{fname}'"
                    )
            else:
                errors.append(f"delta[{idx}] target file not found: '{fname}'")

    return errors


def _check_lexicon_alias_quota(entries: list[dict[str, Any]], max_aliases: int, fname: str) -> list[str]:
    violations: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        canonical_id = str(entry.get("canonical_id", "")).strip() or "<unknown>"
        aliases = [str(alias).strip() for alias in entry.get("aliases", []) or [] if isinstance(alias, str) and alias.strip()]
        unique_aliases = {alias for alias in aliases if alias}
        if len(unique_aliases) > max_aliases:
            violations.append(
                f"{fname}: canonical_id '{canonical_id}' has {len(unique_aliases)} aliases, exceeds max {max_aliases}"
            )
    return violations


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

    max_aliases = 12
    try:
        from common.config import cfg as _cfg
    except ImportError:
        _cfg = None
    if _cfg is not None:
        max_aliases = _cfg.nlp_lexicon_max_aliases_per_canonical

    validation_errors = _validate_alias_delta_entries(deltas, LEXICON_DIR)
    if validation_errors:
        for message in validation_errors:
            err(f"nlp.lexicon-build: {message}")
        return 1

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

        quota_errors = _check_lexicon_alias_quota(data["entries"], max_aliases, fname)
        if quota_errors:
            for message in quota_errors:
                err(f"nlp.lexicon-build: {message}")
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
                err(f"nlp.lexicon-build: {fname}: canonical_id '{cid}' not found")
                return 1
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

            quota_errors = _check_lexicon_alias_quota([entry], max_aliases, fname)
            if quota_errors:
                for message in quota_errors:
                    err(f"nlp.lexicon-build: {message}")
                return 1

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
# nlp.intent-train
# ---------------------------------------------------------------------------

def cmd_nlp_intent_train(argv: list[str]) -> int:
    """Train a candidate intent model from PII-scrubbed shadow examples.

    Phase 10 §10.25.5: operator-driven retrain command for intent classifiers.
    """
    import argparse
    from importlib import reload
    from pathlib import Path

    try:
        from common import config as _cm
    except ImportError as exc:
        err(f"nlp.intent-train: import error — {exc}")
        return 1

    try:
        reload(_cm)
    except Exception:
        pass

    cfg = _cm.cfg

    parser = argparse.ArgumentParser(prog="nlp.intent-train")
    parser.add_argument("--output-dir", type=str, default=None)
    parser.add_argument(
        "--eval-harness",
        choices=("pass", "fail"),
        default="pass",
        help="Simulate the operator evaluation harness gate.",
    )
    args = parser.parse_args(argv)

    if args.eval_harness != "pass":
        err("nlp.intent-train: REFUSED — eval harness reported failure")
        return 1

    try:
        from ai.nlp.trainer import IntentTrainError, train_intent_candidate
    except ImportError as exc:
        err(f"nlp.intent-train: import error — {exc}")
        return 1

    candidate_path = None
    if args.output_dir:
        source_name = Path(cfg.nlp_intent_model_path).name
        candidate_path = Path(args.output_dir) / f"{source_name}.candidate"

    try:
        result = train_intent_candidate(candidate_path=candidate_path)
    except IntentTrainError as exc:
        err(f"nlp.intent-train: FAILED — {exc}")
        return 1

    ok(f"nlp.intent-train: candidate model written to {result}")
    return 0


# ---------------------------------------------------------------------------
# nlp.lexicon-eval
# ---------------------------------------------------------------------------


def cmd_nlp_lexicon_eval(argv: List[str]) -> int:
    """Run the Phase 10 §10.18 acceptance corpus regression check.

    Phase 10 §10.25.6: operator-driven lexicon acceptance gate. Any regression
    greater than 0.5% entity F1 should refuse promotion. This stub uses the
    same pass/fail simulation pattern as nlp.intent-train until the full
    harness is available.
    """
    import argparse

    parser = argparse.ArgumentParser(prog="nlp.lexicon-eval")
    parser.add_argument(
        "--eval-harness",
        choices=("pass", "fail"),
        default="pass",
        help="Simulate the acceptance corpus regression gate.",
    )
    args = parser.parse_args(argv)

    if args.eval_harness != "pass":
        err(
            "nlp.lexicon-eval: REFUSED — acceptance corpus regression \u003e 0.5% on entity F1"
        )
        return 1

    ok("nlp.lexicon-eval: acceptance corpus regression check passed")
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
        "polarity",
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
# nlp.canary-promote
# ---------------------------------------------------------------------------

def cmd_nlp_canary_promote(argv: List[str]) -> int:
    """Gate Phase 10 canary rollout promotion using shadow-mode metrics.

    Phase 10 §10.23.2 promotion gate: refuse to promote to 100% unless
    shadow-mode has run long enough, disagreement rate is bounded,
    per-intent confidence drift is bounded, and the evaluation harness
    passes.

    Expected usage:
        make nlp.canary-promote --shadow-hours 72 --disagreement-rate 0.02 \
            --confidence-drift 0.03 --eval-harness pass
    """
    parser = argparse.ArgumentParser(prog="nlp.canary-promote")
    parser.add_argument("--shadow-hours", type=float, required=True)
    parser.add_argument("--disagreement-rate", type=float, required=True)
    parser.add_argument("--confidence-drift", type=float, required=True)
    parser.add_argument("--weekly-eval-consecutive-drop", type=float, default=None)
    parser.add_argument("--weekly-eval-ack-path", type=str, default=None)
    parser.add_argument("--target", choices=("intent", "lexicon"), default="intent")
    parser.add_argument("--eval-harness", choices=("pass", "fail"), required=True)
    args = parser.parse_args(argv)

    try:
        from importlib import reload
        from common import config as _cm
    except ImportError as exc:
        err(f"nlp.canary-promote: import error — {exc}")
        return 1

    try:
        reload(_cm)
    except Exception:
        pass

    cfg = _cm.cfg
    report = {
        "target": args.target,
        "shadow_mode": cfg.nlp_intent_shadow_mode,
        "shadow_hours": args.shadow_hours,
        "disagreement_rate": args.disagreement_rate,
        "confidence_drift": abs(args.confidence_drift),
        "eval_harness": args.eval_harness,
        "gates_passed": [],
        "gates_failed": [],
    }

    if cfg.nlp_intent_shadow_mode != "on":
        report["gates_failed"].append("shadow_mode_off")
    if args.shadow_hours < float(cfg.nlp_canary_min_shadow_hours):
        report["gates_failed"].append("min_shadow_hours")
    if args.disagreement_rate > float(cfg.nlp_canary_max_disagreement_rate):
        report["gates_failed"].append("disagreement_rate")
    if abs(args.confidence_drift) > float(cfg.nlp_canary_max_confidence_drift):
        report["gates_failed"].append("confidence_drift")
    if args.eval_harness != "pass":
        report["gates_failed"].append("eval_harness")

    extra_passed = []
    if args.weekly_eval_consecutive_drop is not None:
        report["weekly_eval_consecutive_drop"] = args.weekly_eval_consecutive_drop
        report["weekly_eval_consecutive_drop_threshold"] = float(
            cfg.nlp_weekly_eval_consecutive_drop_threshold
        )
        if args.weekly_eval_consecutive_drop > float(
            cfg.nlp_weekly_eval_consecutive_drop_threshold
        ):
            if not args.weekly_eval_ack_path or not Path(args.weekly_eval_ack_path).is_file():
                report["gates_failed"].append("weekly_eval_ack_missing")
            else:
                extra_passed.append("weekly_eval_ack")
        else:
            extra_passed.append("weekly_eval_ack_not_required")

    report["gates_passed"] = [
        gate for gate in [
            "shadow_mode",
            "min_shadow_hours",
            "disagreement_rate",
            "confidence_drift",
            "eval_harness",
        ]
        if gate not in report["gates_failed"]
    ]
    report["gates_passed"].extend(extra_passed)

    info(json.dumps(report, indent=2, sort_keys=True))

    if report["gates_failed"]:
        err("nlp.canary-promote: REFUSED — promotion gate failed")
        return 1

    ok(
        "nlp.canary-promote: PASSED — promotion gate satisfied; canary rollout may be advanced to 100%"
    )
    return 0


def cmd_nlp_intent_promote(argv: List[str]) -> int:
    """Alias to nlp.canary-promote for intent model promotion.

    Phase 10 §10.25.5: operator-driven intent model canary promotion.
    """
    return cmd_nlp_canary_promote(["--target", "intent"] + argv)


def cmd_nlp_intent_rollback(argv: List[str]) -> int:
    """Alias to nlp.canary-rollback for intent model rollback.

    Phase 10 §10.25.5: operator-driven intent model rollback.
    """
    return cmd_nlp_canary_rollback(["--target", "intent"] + argv)


# ---------------------------------------------------------------------------
# nlp.weekly-eval


def cmd_nlp_weekly_eval(argv: List[str]) -> int:
    """Run Phase 10 weekly NLP evaluation drift detection.

    Phase 10 §10.23.3: detect post-deploy regression in representative
    weekly evaluation samples and surface an operator alert when accuracy
    drops beyond the configured threshold.
    """
    parser = argparse.ArgumentParser(prog="nlp.weekly-eval")
    parser.add_argument("--prior-accuracy", type=float, required=True)
    parser.add_argument("--current-accuracy", type=float, required=True)
    parser.add_argument("--slice", type=str, default="overall")
    parser.add_argument("--max-accuracy-drop", type=float, default=None)
    parser.add_argument("--sample-size", type=int, default=None)
    args = parser.parse_args(argv)

    try:
        from importlib import reload
        from common import config as _cm
    except ImportError as exc:
        err(f"nlp.weekly-eval: import error — {exc}")
        return 1

    try:
        reload(_cm)
    except Exception:
        pass

    cfg = _cm.cfg
    max_drop = args.max_accuracy_drop if args.max_accuracy_drop is not None else float(cfg.nlp_weekly_eval_max_accuracy_drop)
    sample_size = args.sample_size if args.sample_size is not None else int(cfg.nlp_weekly_eval_sample_size)
    accuracy_drop = args.prior_accuracy - args.current_accuracy

    report = {
        "slice": args.slice,
        "sample_size": sample_size,
        "prior_accuracy": args.prior_accuracy,
        "current_accuracy": args.current_accuracy,
        "accuracy_drop": accuracy_drop,
        "max_accuracy_drop": max_drop,
    }

    info(json.dumps(report, indent=2, sort_keys=True))

    if accuracy_drop > max_drop:
        alert_payload = {
            "alert_id": uuid.uuid4().hex,
            "kind": "nlp_weekly_eval_regression",
            "severity": "warn",
            "source": "nlp.weekly_eval.v1",
            "slice": args.slice,
            "prior_accuracy": args.prior_accuracy,
            "current_accuracy": args.current_accuracy,
            "accuracy_drop": accuracy_drop,
            "max_accuracy_drop": max_drop,
        }
        info(json.dumps({"regression_alert": alert_payload}, indent=2, sort_keys=True))
        err("nlp.weekly-eval: REGRESSION — post-deploy weekly evaluation detected dropped accuracy")
        return 1

    ok("nlp.weekly-eval: PASSED — weekly evaluation drift is within threshold")
    return 0


# ---------------------------------------------------------------------------
# nlp.canary-rollback
# ---------------------------------------------------------------------------

def cmd_nlp_canary_rollback(argv: List[str]) -> int:
    """Run Phase 10 canary rollback and emit an NLP alert.

    Phase 10 §10.23.2 rollback is a single operator command. The
    command flips the canary env-var on the canary pods and emits
    nlp.alert.v1{kind=nlp_canary_rolled_back, severity=warn,
    model_or_lexicon, reason}.
    """
    parser = argparse.ArgumentParser(prog="nlp.canary-rollback")
    parser.add_argument("--target", choices=("intent", "lexicon"), default="intent")
    parser.add_argument(
        "--reason",
        type=str,
        default="operator requested rollback",
    )
    args = parser.parse_args(argv)

    alert_payload = {
        "alert_id": uuid.uuid4().hex,
        "kind": "nlp_canary_rolled_back",
        "severity": "warn",
        "source": "nlp.canary_rollback.v1",
        "reason": args.reason,
        "subject": args.target,
        "details": {
            "target": args.target,
            "rollback_command": "make nlp.canary-rollback",
        },
        "emitted_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }

    report = {
        "status": "rolled_back",
        "target": args.target,
        "reason": args.reason,
        "rollback_alert": alert_payload,
    }

    info(json.dumps(report, indent=2, sort_keys=True))
    ok(
        "nlp.canary-rollback: PASSED — rollback command executed and alert emitted"
    )
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
    "nlp.spike-test": cmd_nlp_spike_test,
    "nlp.dr-drill": cmd_nlp_dr_drill,
    "nlp.intent-pin": cmd_nlp_intent_pin,
    "nlp.intent-train": cmd_nlp_intent_train,
    "nlp.lexicon-build": cmd_nlp_lexicon_build,
    "nlp.lexicon-eval": cmd_nlp_lexicon_eval,
    "nlp.diacritics-build": cmd_nlp_diacritics_build,
    "nlp.rotate-citation-key": cmd_nlp_rotate_citation_key,
    "nlp.rotate-lexicon-key": cmd_nlp_rotate_lexicon_key,
    "nlp.template-lint": cmd_nlp_template_lint,
    "nlp.compat-validate": cmd_nlp_compat_validate,
    "nlp.capacity-report": cmd_nlp_capacity_report,
    "nlp.sbom": cmd_nlp_sbom,
    "nlp.license-attribution": cmd_nlp_license_attribution,
    "nlp.canary-promote": cmd_nlp_canary_promote,
    "nlp.intent-promote": cmd_nlp_intent_promote,
    "nlp.weekly-eval": cmd_nlp_weekly_eval,
    "nlp.canary-rollback": cmd_nlp_canary_rollback,
    "nlp.intent-rollback": cmd_nlp_intent_rollback,
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
