from __future__ import annotations

import pathlib

from ai.common.config import cfg
from nlp.eval._sample import (
    WEEKLY_EVAL_STRATA_KEYS,
    WeeklyEvalStratumKey,
    sanitize_weekly_eval_text,
    sample_weekly_eval_rows,
)


def test_weekly_eval_strata_keys_are_closed_enum() -> None:
    assert WEEKLY_EVAL_STRATA_KEYS == tuple(item.value for item in WeeklyEvalStratumKey)
    assert WEEKLY_EVAL_STRATA_KEYS == (
        "intent_class",
        "has_entity",
        "has_dialect",
        "has_code_switch",
        "hour_of_day_bucket",
    )


def test_weekly_eval_sample_rows_stratifies_by_closed_keys() -> None:
    rows: list[dict[str, object]] = []
    for i in range(6):
        rows.append(
            {
                "intent_class": "predict.match_outcome",
                "has_entity": True,
                "has_dialect": False,
                "has_code_switch": False,
                "hour_of_day_bucket": "morning",
                "row_id": f"A{i}",
            }
        )
    for i in range(3):
        rows.append(
            {
                "intent_class": "predict.score_grid",
                "has_entity": False,
                "has_dialect": True,
                "has_code_switch": False,
                "hour_of_day_bucket": "evening",
                "row_id": f"B{i}",
            }
        )

    sample = sample_weekly_eval_rows(rows, 4)

    assert len(sample) == 4
    assert sum(1 for row in sample if row["intent_class"] == "predict.match_outcome") == 3
    assert sum(1 for row in sample if row["intent_class"] == "predict.score_grid") == 1


def test_weekly_eval_text_sanitizes_pii_and_unknown_tokens() -> None:
    allowlist = {"merhaba", "nasilsin", "<UNK>"}
    sample = sanitize_weekly_eval_text(
        "merhaba 05321234567@test.com yeni_token",
        allowlist=allowlist,
        max_chars=200,
    )

    assert "05321234567@test.com" not in sample
    assert "yeni_token" not in sample
    assert sample.split() == ["merhaba", "<UNK>", "<UNK>"]


def test_weekly_eval_text_truncates_after_sanitization() -> None:
    allowlist = {"a", "b", "<UNK>"}
    sample = sanitize_weekly_eval_text(
        "a b c d e f g h i j",
        allowlist=allowlist,
        max_chars=7,
    )

    assert sample == "a b"


def test_config_has_nlp_weekly_eval_sample_max_chars() -> None:
    assert cfg.nlp_weekly_eval_sample_max_chars == 200


def test_nlp_weekly_eval_sample_max_chars_in_env_example() -> None:
    env_example = pathlib.Path("xops/env/.env.example").read_text()
    assert "NEGELIR_NLP_WEEKLY_EVAL_SAMPLE_MAX_CHARS" in env_example
