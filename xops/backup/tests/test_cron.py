"""Phase 8 §8.3 — cron evaluator proof tests (stdlib only)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from xops.backup.cron import (
    CronExpr,
    CronSyntaxError,
    matches,
    next_fire_after,
    parse_cron,
)


UTC = timezone.utc


def _t(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


# ── parse_cron — happy path ─────────────────────────────────────────────


@pytest.mark.parametrize("expr", [
    "* * * * *",
    "0 3 * * *",
    "0 3 * * 0",
    "*/5 * * * *",
    "0 0,12 * * *",
    "0 0 1 * *",
    "0 0 1-7 * 1",
    "30 2-4 * * *",
    "0 */6 * * 1-5",
])
def test_parse_cron_accepts_supported_grammar(expr: str) -> None:
    parsed = parse_cron(expr)
    assert isinstance(parsed, CronExpr)
    assert parsed.raw == expr


def test_parse_cron_dow_seven_folds_to_zero() -> None:
    parsed = parse_cron("0 5 * * 7")
    assert 0 in parsed.dows
    assert 7 not in parsed.dows


def test_step_expansion() -> None:
    parsed = parse_cron("*/15 * * * *")
    assert parsed.minutes == frozenset({0, 15, 30, 45})


def test_range_with_step() -> None:
    parsed = parse_cron("10-30/5 * * * *")
    assert parsed.minutes == frozenset({10, 15, 20, 25, 30})


# ── parse_cron — refusal surface ────────────────────────────────────────


@pytest.mark.parametrize("bad", [
    "",
    "0 3 * *",                    # 4 fields
    "0 3 * * * *",                # 6 fields
    "0 3 * * SUN",                # named day
    "0 3 * JAN *",                # named month
    "0 3 * * L",                  # Vixie-cron extension
    "0 3 * * 0#1",                # nth-weekday
    "0 3 32 * *",                 # dom out of range
    "0 24 * * *",                 # hour out of range
    "60 0 * * *",                 # minute out of range
    "0 0 * * 9",                  # dow out of range
    "5-3 * * * *",                # backwards range
    "*/0 * * * *",                # zero step
    "* * * * abc",                # alphabetic
    "*/-1 * * * *",               # negative step
])
def test_parse_cron_rejects_unsupported_syntax(bad: str) -> None:
    with pytest.raises(CronSyntaxError):
        parse_cron(bad)


def test_parse_cron_rejects_non_string() -> None:
    with pytest.raises(CronSyntaxError):
        parse_cron(0)  # type: ignore[arg-type]


# ── matches — Vixie-cron OR rule ────────────────────────────────────────


def test_matches_minute_hour_gating() -> None:
    expr = parse_cron("0 3 * * *")
    assert matches(expr, _t(2025, 1, 1, 3, 0))
    assert not matches(expr, _t(2025, 1, 1, 3, 1))
    assert not matches(expr, _t(2025, 1, 1, 4, 0))


def test_matches_dom_only() -> None:
    expr = parse_cron("0 0 1 * *")
    assert matches(expr, _t(2025, 2, 1))
    assert not matches(expr, _t(2025, 2, 2))


def test_matches_dow_only_sunday() -> None:
    # 2025-01-05 is Sunday.
    expr = parse_cron("0 5 * * 0")
    assert matches(expr, _t(2025, 1, 5, 5, 0))
    assert not matches(expr, _t(2025, 1, 6, 5, 0))


def test_vixie_or_rule_dom_or_dow() -> None:
    """'1st of month OR Sunday at 3 AM' fires on BOTH conditions."""
    expr = parse_cron("0 3 1 * 0")
    # 2025-01-05 is Sunday (not 1st) — matches by dow
    assert matches(expr, _t(2025, 1, 5, 3, 0))
    # 2025-02-01 is Saturday (1st) — matches by dom
    assert matches(expr, _t(2025, 2, 1, 3, 0))
    # 2025-01-06 is Monday and not 1st — must NOT match
    assert not matches(expr, _t(2025, 1, 6, 3, 0))


def test_matches_requires_utc_tz() -> None:
    expr = parse_cron("0 3 * * *")
    naive = datetime(2025, 1, 1, 3, 0)
    with pytest.raises(ValueError):
        matches(expr, naive)
    non_utc = datetime(2025, 1, 1, 3, 0, tzinfo=timezone(timedelta(hours=2)))
    with pytest.raises(ValueError):
        matches(expr, non_utc)


# ── next_fire_after ─────────────────────────────────────────────────────


def test_next_fire_strictly_greater() -> None:
    expr = parse_cron("0 3 * * *")
    nxt = next_fire_after(expr, _t(2025, 1, 1, 3, 0))
    # Strictly greater → not the same minute, must be tomorrow's 3 AM.
    assert nxt == _t(2025, 1, 2, 3, 0)


def test_next_fire_skips_to_next_day() -> None:
    expr = parse_cron("0 3 * * *")
    nxt = next_fire_after(expr, _t(2025, 1, 1, 3, 30))
    assert nxt == _t(2025, 1, 2, 3, 0)


def test_next_fire_every_5_minutes() -> None:
    expr = parse_cron("*/5 * * * *")
    nxt = next_fire_after(expr, _t(2025, 1, 1, 12, 3))
    assert nxt == _t(2025, 1, 1, 12, 5)


def test_next_fire_impossible_expression_raises() -> None:
    # Feb 31 never exists; restricted to month=2 + dom=31 with both
    # specified means the OR rule still requires dom match → no fire.
    expr = parse_cron("0 0 31 2 1")
    # The OR rule WILL match on Mondays in February — so use a strict
    # impossibility: dom=31 in months=2 only and dow=*.
    expr = parse_cron("0 0 31 2 *")
    with pytest.raises(CronSyntaxError):
        next_fire_after(expr, _t(2025, 1, 1))


def test_next_fire_requires_utc_tz() -> None:
    expr = parse_cron("0 3 * * *")
    with pytest.raises(ValueError):
        next_fire_after(expr, datetime(2025, 1, 1))


# ── fires_every_minute heuristic ────────────────────────────────────────


def test_fires_every_minute_diagnostic() -> None:
    assert parse_cron("* * * * *").fires_every_minute is True
    assert parse_cron("0 3 * * *").fires_every_minute is False
