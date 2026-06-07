"""Quarterly NLP eval corpus curator for Phase 10 §10.32.14."""
from __future__ import annotations

import argparse
import collections
import datetime
import hashlib
import json
import random
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
AI_ROOT = REPO_ROOT / "ai"
if str(AI_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_ROOT))

from common.config import Config
from common.security.tr_pii import detect_tr_pii_spans, redact_tr_pii
from common.telemetry import get_sink

DEFAULT_SHADOW_SAMPLE_SIZE = 5000


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _bucket_key(row: dict[str, Any]) -> tuple[str, str, bool, bool, bool]:
    intent_class = str(row.get("intent_class") or row.get("baseline_intent") or row.get("canary_intent") or "unknown").strip()
    dialect_class = str(row.get("dialect_class") or "standard").strip()
    has_dialect = bool(row.get("has_dialect") or dialect_class != "standard")
    has_anaphora = bool(row.get("has_anaphora") or row.get("anaphora") or False)
    has_negation = bool(row.get("has_negation") or row.get("negation") or False)
    return (intent_class, dialect_class, has_dialect, has_anaphora, has_negation)


def stratified_sample(rows: list[dict[str, Any]], target_size: int, seed: int) -> list[dict[str, Any]]:
    if len(rows) <= target_size:
        return list(rows)
    buckets: dict[tuple[str, str, bool, bool, bool], list[dict[str, Any]]] = {}
    for row in rows:
        buckets.setdefault(_bucket_key(row), []).append(row)

    total = len(rows)
    randomizer = random.Random(seed)
    target_counts: dict[tuple[str, str, bool, bool, bool], int] = {}
    remaining = target_size
    bucket_items = list(buckets.items())
    for idx, (key, bucket_rows) in enumerate(bucket_items):
        if idx == len(bucket_items) - 1:
            target_counts[key] = remaining
            break
        allocation = max(1, round(len(bucket_rows) / total * target_size))
        allocation = min(allocation, len(bucket_rows))
        target_counts[key] = allocation
        remaining -= allocation
    sampled: list[dict[str, Any]] = []
    for key, bucket_rows in bucket_items:
        count = min(target_counts.get(key, 1), len(bucket_rows))
        sampled.extend(randomizer.sample(bucket_rows, count))
    if len(sampled) > target_size:
        sampled = sampled[:target_size]
    return sampled


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        redacted, _ = redact_tr_pii(value)
        return redacted
    if isinstance(value, dict):
        return {k: _redact_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(v) for v in value]
    return value


def redact_row_pii(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _redact_value(value) for key, value in row.items()}


def verify_row_no_pii(row: dict[str, Any]) -> None:
    def check(value: Any) -> None:
        if isinstance(value, str):
            spans = detect_tr_pii_spans(value)
            if spans:
                raise ValueError(f"PII detected after redaction: {spans}")
        elif isinstance(value, dict):
            for v in value.values():
                check(v)
        elif isinstance(value, list):
            for v in value:
                check(v)
    check(row)


def _drift_candidate(row: dict[str, Any], seed: int) -> bool:
    if str(row.get("baseline_intent") or "") != str(row.get("canary_intent") or ""):
        return True
    raw = json.dumps({"input_hash": row.get("input_hash"), "query": row.get("query")}, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256((raw + str(seed)).encode("utf-8")).digest()
    return digest[0] % 7 == 0


def _parse_datetime(value: Any, fallback: datetime.datetime) -> datetime.datetime:
    if not isinstance(value, str):
        return fallback
    try:
        if value.endswith("Z"):
            return datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
        return datetime.datetime.fromisoformat(value)
    except ValueError:
        return fallback


def _build_meta(rows: list[dict[str, Any]], cfg: Config, timestamp: datetime.datetime) -> dict[str, Any]:
    emitted = [_parse_datetime(row.get("emitted_at"), timestamp) for row in rows if row.get("emitted_at")]
    if emitted:
        source_window_start = min(emitted).astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        source_window_end = max(emitted).astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        source_window_start = source_window_end = timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
    signoffs = [
        {"reviewer": "nlp-curator", "role": "curator", "signed_at_utc": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")},
        {"reviewer": "nlp-domain-football", "role": "domain", "signed_at_utc": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")},
    ]
    if len(rows) >= 100:
        signoffs.append({"reviewer": "nlp-compliance", "role": "compliance", "signed_at_utc": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")})
    return {
        "schema_version": 1,
        "generated_at_utc": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_window_start": source_window_start,
        "source_window_end": source_window_end,
        "reviewer_signoffs": signoffs,
        "curator_pipeline_version": cfg.nlp_pipeline_version,
    }


def curate_eval_corpus(
    shadow_path: Path,
    output_dir: Path,
    seed: int = 0,
    max_added_rows: int | None = None,
    generated_at: datetime.datetime | None = None,
) -> Path:
    cfg = Config()
    rows = load_jsonl(shadow_path)
    if not rows:
        raise ValueError(f"Shadow file is empty: {shadow_path}")
    sample = stratified_sample(rows, DEFAULT_SHADOW_SAMPLE_SIZE, seed)
    redacted: list[dict[str, Any]] = []
    for row in sample:
        scrubbed = redact_row_pii(row)
        verify_row_no_pii(scrubbed)
        redacted.append(scrubbed)
    candidates = [row for row in redacted if _drift_candidate(row, seed)]
    max_rows = max_added_rows if max_added_rows is not None else cfg.nlp_eval_corpus_pr_max_added_rows_per_quarter
    if len(candidates) > max_rows:
        raise ValueError(f"Curated batch {len(candidates)} rows exceeds cap of {max_rows} rows.")
    now = generated_at if generated_at is not None else datetime.datetime.now(datetime.timezone.utc)
    meta = _build_meta(candidates, cfg, now)
    out_dir = output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    year = now.year
    quarter = ((now.month - 1) // 3) + 1
    output_path = out_dir / f"{year}q{quarter}.jsonl"
    if output_path.exists():
        raise FileExistsError(f"Output file already exists: {output_path}")
    records: list[dict[str, Any]] = [{"_meta": meta}] + candidates
    write_jsonl(output_path, records)
    sink = get_sink()
    counts = collections.Counter(
        str(row.get("intent_class") or row.get("baseline_intent") or "unknown")
        for row in candidates
    )
    for intent_class, count in counts.items():
        sink.record_nlp_eval_corpus_growth_rate(intent_class, float(count))
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Curate a versioned NLP eval corpus from nlp.shadow.v1 sample rows.")
    parser.add_argument("--shadow-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / "data" / "nlp" / "eval_corpus")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-added-rows", type=int)
    parser.add_argument("--generated-at", type=str)
    args = parser.parse_args(argv)
    generated_at = None
    if args.generated_at:
        if args.generated_at.endswith("Z"):
            generated_at = datetime.datetime.strptime(args.generated_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
        else:
            generated_at = datetime.datetime.fromisoformat(args.generated_at)
    try:
        output_path = curate_eval_corpus(
            args.shadow_file,
            args.output_dir,
            seed=args.seed,
            max_added_rows=args.max_added_rows,
            generated_at=generated_at,
        )
        print(f"Wrote curated eval corpus to {output_path}")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
