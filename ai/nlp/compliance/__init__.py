from __future__ import annotations

import functools
import hashlib
from pathlib import Path
from typing import Any

import yaml


def _disclosure_path(locale: str) -> Path:
    return Path(__file__).resolve().parent / f"disclosures.{locale}.yaml"


@functools.lru_cache(maxsize=8)
def load_disclosures(locale: str = "tr-TR") -> tuple[list[dict[str, Any]], str]:
    path = _disclosure_path(locale)
    if path.exists():
        return _load_disclosures(path), locale

    fallback = _disclosure_path("tr-TR")
    if locale != "tr-TR" and fallback.exists():
        return _load_disclosures(fallback), "tr-TR"

    return [], locale


def disclosures_snapshot_sha(disclosures: list[dict[str, Any]]) -> str:
    items = sorted(
        f"{d['disclosure_id']}:{d['version']}:{d.get('text','') or ''}"
        for d in disclosures
        if isinstance(d.get("disclosure_id"), str)
    )
    joined = "|".join(items)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _load_disclosures(path: Path) -> list[dict[str, Any]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    disclosures = raw.get("disclosures", [])
    if not isinstance(disclosures, list):
        raise ValueError(f"invalid disclosures file: {path}")
    result: list[dict[str, Any]] = []
    for item in disclosures:
        if not isinstance(item, dict):
            continue
        disclosure_id = item.get("disclosure_id")
        version = item.get("version")
        text = item.get("text")
        if not isinstance(disclosure_id, str) or not isinstance(version, int) or not isinstance(text, str):
            continue
        result.append({
            "disclosure_id": disclosure_id,
            "version": version,
            "effective_from_utc": str(item.get("effective_from_utc") or ""),
            "text": text,
            "disclosure_sha8": hashlib.sha256(text.encode("utf-8")).hexdigest()[:8],
        })
    return result
