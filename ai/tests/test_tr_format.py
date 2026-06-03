from __future__ import annotations

import datetime as dt
import pathlib
import sys

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "ai"))

from common.text.tr_format import (
    tr_format_clock,
    tr_format_date,
    tr_format_date_short,
    tr_format_money,
    tr_format_number,
    tr_format_score,
)

import pytest


def test_tr_format_number_thousands_dot_decimal_comma():
    assert tr_format_number("1234.56", decimals=2) == "1.234,56"
    assert tr_format_number(1234567, decimals=0) == "1.234.567"
    assert tr_format_number(1234, decimals=2) == "1.234,00"


def test_tr_format_money_try_suffix():
    assert tr_format_money(1234.56) == "1.234,56 TL"
    assert tr_format_money(1234.56, currency="EUR") == "1.234,56 €"


def test_tr_format_clock_always_24h_no_am_pm():
    utc_dt = dt.datetime.fromisoformat("2026-04-27T18:30:00+00:00")
    assert tr_format_clock(utc_dt, tz="Europe/Istanbul") == "21:30"
    assert tr_format_clock("2026-04-27T18:30:00Z", tz="Europe/Istanbul") == "21:30"


def test_tr_format_clock_rejects_naive_datetime():
    with pytest.raises(ValueError, match="naive datetime"):
        tr_format_clock(dt.datetime(2026, 4, 27, 18, 30), tz="Europe/Istanbul")
    with pytest.raises(ValueError, match="naive datetime"):
        tr_format_clock("2026-04-27T18:30:00", tz="Europe/Istanbul")


def test_tr_format_clock_rejects_leap_second():
    with pytest.raises(ValueError, match="leap second"):
        tr_format_clock("2014-06-30T23:59:60Z", tz="Europe/Istanbul")


def test_tr_format_clock_dst_window_2014_renders_correctly():
    assert tr_format_clock("2014-03-30T01:30:00Z", tz="Europe/Istanbul") == "03:30"
    assert tr_format_clock("2014-03-30T02:30:00Z", tz="Europe/Istanbul") == "04:30"


def test_nlp_clock_renders_istanbul_offset_currently_plus3():
    assert tr_format_clock("2026-04-27T18:30:00Z") == "21:30"


def test_tr_format_date_long_form_uses_tr_month_names():
    assert tr_format_date(dt.date(2026, 4, 27)) == "27 Nisan 2026"


def test_tr_format_date_short():
    assert tr_format_date_short(dt.date(2026, 4, 27)) == "27.04.2026"


def test_tr_format_score_no_space_ascii_hyphen():
    assert tr_format_score(1, 0) == "1-0"


def test_tr_format_negative_zero_renders_zero():
    assert tr_format_number(-0.0, decimals=0) == "0"


def test_tr_format_inf_nan_raises():
    with pytest.raises(ValueError):
        tr_format_number(float("inf"), decimals=0)
    with pytest.raises(ValueError):
        tr_format_number(float("nan"), decimals=0)


def test_tr_format_matches_babel_when_available():
    try:
        import babel.numbers as babel_numbers  # type: ignore[import]
    except ImportError:
        pytest.skip("babel not installed")

    assert tr_format_number(1234.56, decimals=2) == babel_numbers.format_decimal(
        1234.56,
        locale="tr_TR",
    )
