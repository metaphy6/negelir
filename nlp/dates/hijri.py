"""Vendored deterministic Hijri lookup for Turkish holiday resolution.

This module is intentionally small and deterministic: a hard-coded table
for the next few years, with a pinned SHA constant for compatibility checks.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

_HIJRI_OBSERVED_TABLE: dict[int, dict[str, tuple[int, int]]] = {
    2026: {
        "ramazan_bayrami": (4, 11),
        "kurban_bayrami": (6, 17),
    },
    2027: {
        "ramazan_bayrami": (3, 31),
        "kurban_bayrami": (6, 6),
    },
}

VENDORED_HIJRI_TABLE_SHA = "dbe4e62d680c7db57610feea1e735f24028f105caf83df06431a01df02cfa5b1"


def resolve_hijri_observed_date(
    holiday_key: str,
    year: int,
) -> tuple[int, int] | None:
    return _HIJRI_OBSERVED_TABLE.get(year, {}).get(holiday_key)


def compute_table_sha() -> str:
    payload = json.dumps(_HIJRI_OBSERVED_TABLE, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    print(compute_table_sha())
