from __future__ import annotations

import math
from collections import defaultdict
from enum import Enum
from typing import Any

from common.security.patterns import PII_PATTERNS

WEEKLY_EVAL_STRATA_KEYS = (
    "intent_class",
    "has_entity",
    "has_dialect",
    "has_code_switch",
    "hour_of_day_bucket",
)


class WeeklyEvalStratumKey(str, Enum):
    intent_class = "intent_class"
    has_entity = "has_entity"
    has_dialect = "has_dialect"
    has_code_switch = "has_code_switch"
    hour_of_day_bucket = "hour_of_day_bucket"

    @classmethod
    def values(cls) -> tuple[str, ...]:
        return tuple(item.value for item in cls)


assert WEEKLY_EVAL_STRATA_KEYS == WeeklyEvalStratumKey.values(), (
    "WEEKLY_EVAL_STRATA_KEYS must match WeeklyEvalStratumKey values"
)
assert len(WEEKLY_EVAL_STRATA_KEYS) == 5


def _scrub_pii(text: str) -> str:
    for _, pattern in PII_PATTERNS:
        text = pattern.sub("<UNK>", text)
    return text


def sanitize_weekly_eval_text(text: str, allowlist: set[str], max_chars: int) -> str:
    if max_chars <= 0:
        return ""

    text = _scrub_pii(text)
    tokens = text.split()
    sanitized_tokens = [token if token in allowlist else "<UNK>" for token in tokens]

    result_tokens: list[str] = []
    current_length = 0
    for token in sanitized_tokens:
        if not result_tokens:
            if len(token) > max_chars:
                return token[:max_chars]
            result_tokens.append(token)
            current_length = len(token)
            continue

        candidate_length = current_length + 1 + len(token)
        if candidate_length > max_chars:
            break

        result_tokens.append(token)
        current_length = candidate_length

    return " ".join(result_tokens)


def make_weekly_eval_stratum(row: dict[str, Any]) -> tuple[str, bool, bool, bool, str]:
    return (
        row[WeeklyEvalStratumKey.intent_class.value],
        bool(row[WeeklyEvalStratumKey.has_entity.value]),
        bool(row[WeeklyEvalStratumKey.has_dialect.value]),
        bool(row[WeeklyEvalStratumKey.has_code_switch.value]),
        row[WeeklyEvalStratumKey.hour_of_day_bucket.value],
    )


def _select_stratum_counts(
    counts: dict[tuple[str, bool, bool, bool, str], int], sample_size: int
) -> dict[tuple[str, bool, bool, bool, str], int]:
    total = sum(counts.values())
    if total == 0 or sample_size <= 0:
        return {stratum: 0 for stratum in counts}

    quotas = {stratum: count * sample_size / total for stratum, count in counts.items()}
    assigned = {stratum: int(math.floor(quota)) for stratum, quota in quotas.items()}
    remaining = sample_size - sum(assigned.values())

    if remaining > 0:
        extras = sorted(
            counts,
            key=lambda stratum: (quotas[stratum] - assigned[stratum], counts[stratum]),
            reverse=True,
        )
        for stratum in extras:
            if remaining <= 0:
                break
            assigned[stratum] += 1
            remaining -= 1

    return {stratum: min(count, counts[stratum]) for stratum, count in assigned.items()}


def sample_weekly_eval_rows(rows: list[dict[str, Any]], sample_size: int) -> list[dict[str, Any]]:
    if sample_size <= 0:
        return []
    if len(rows) <= sample_size:
        return rows[:]

    strata: dict[tuple[str, bool, bool, bool, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        strata[make_weekly_eval_stratum(row)].append(row)

    desired_counts = _select_stratum_counts(
        {stratum: len(items) for stratum, items in strata.items()}, sample_size
    )

    result: list[dict[str, Any]] = []
    for stratum, count in desired_counts.items():
        result.extend(strata[stratum][:count])

    if len(result) < sample_size:
        leftovers: list[dict[str, Any]] = []
        for stratum, items in strata.items():
            leftovers.extend(items[desired_counts.get(stratum, 0) :])
        result.extend(leftovers[: sample_size - len(result)])

    return result[:sample_size]
