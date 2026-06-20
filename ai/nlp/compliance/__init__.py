from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

from ai.common.config import cfg

_DISCLOSURE_CACHE: dict[Path, tuple[int, list[dict[str, Any]]]] = {}

ALLOWED_DISCLOSURE_IDS = frozenset(
    {
        "kvkk_user_rights_footer_first_per_conversation",
        "gambling_law_disclaimer_band",
        "automated_decision_notice",
        "eighteen_plus_gate",
    }
)


def _disclosure_path(locale: str) -> Path:
    return Path(__file__).resolve().parent / f"disclosures.{locale}.yaml"


def _disclosure_locale_variants(locale: str) -> list[str]:
    locale_text = str(locale).strip()
    variants: list[str] = []
    if locale_text:
        variants.append(locale_text)
    if "-" in locale_text:
        base = locale_text.split("-", 1)[0].strip()
        if base and base not in variants:
            variants.append(base)
    elif locale_text and locale_text not in variants:
        # Support full locale fallback for base-language-only files like
        # `disclosures.tr.yaml` when the configured locale is `tr-TR`.
        variants.append(f"{locale_text}-{locale_text.upper()}")
    return variants


def _load_disclosures_cached(path: Path) -> list[dict[str, Any]]:
    mtime_ns = path.stat().st_mtime_ns
    cached = _DISCLOSURE_CACHE.get(path)
    if cached is not None and cached[0] == mtime_ns:
        return cached[1]
    disclosures = _load_disclosures(path)
    _DISCLOSURE_CACHE[path] = (mtime_ns, disclosures)
    return disclosures


def load_disclosures(locale: str = "tr-TR") -> tuple[list[dict[str, Any]], str]:
    locale_text = str(locale).strip() or "tr-TR"
    candidates: list[str] = [locale_text]
    for fallback in cfg.nlp_disclosure_locale_fallback_chain:
        if fallback not in candidates:
            candidates.append(fallback)
    if "tr-TR" not in candidates:
        candidates.append("tr-TR")

    tried: set[str] = set()
    for candidate in candidates:
        for variant in _disclosure_locale_variants(candidate):
            if variant in tried:
                continue
            tried.add(variant)
            path = _disclosure_path(variant)
            if path.exists():
                return _load_disclosures_cached(path), candidate

    return [], locale_text


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
    seen_ids: set[str] = set()
    for item in disclosures:
        if not isinstance(item, dict):
            continue
        disclosure_id = item.get("disclosure_id")
        version = item.get("version")
        text = item.get("text")
        if (
            not isinstance(disclosure_id, str)
            or disclosure_id == ""
            or disclosure_id not in ALLOWED_DISCLOSURE_IDS
            or not isinstance(version, int)
            or version <= 0
            or not isinstance(text, str)
        ):
            raise ValueError(f"invalid disclosure entry in {path}: {item}")
        if disclosure_id in seen_ids:
            raise ValueError(f"duplicate disclosure_id {disclosure_id!r} in {path}")
        seen_ids.add(disclosure_id)
        result.append({
            "disclosure_id": disclosure_id,
            "version": version,
            "effective_from_utc": str(item.get("effective_from_utc") or ""),
            "text": text,
            "disclosure_sha8": hashlib.sha256(text.encode("utf-8")).hexdigest()[:8],
        })
    return result
