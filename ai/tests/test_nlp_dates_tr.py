"""Tests for Phase 10 §10.5 — Turkish date/time resolver (ai/nlp/dates_tr.py).

Covers:
  * "bugün", "yarın", "dün" → day-granularity day ranges
  * Named weekdays ("cuma", "pazartesi", …) → nearest-future day
  * "pazar" does NOT match inside "pazartesi" (word-boundary rule)
  * "önümüzdeki hafta", "bu hafta", "geçen hafta" → week ranges
  * Explicit date: "27 Nisan saat 21:30", "27 Nisan 2026"
  * Time-only: "saat 21:30" → today + time window
  * Combined: "yarın saat 18:00"
  * Out-of-range time ("saat 25:00") → falls through, returns day or None
  * Invalid date ("31 Şubat") → returns None
  * Unrecognized text → returns None
  * Clock injection: all resolution uses the injected clock_now
  * cfg.nlp_clock_now default is callable and returns UTC-aware datetime
  * Granularity invariants: day → 24 h, week → 7 days, hour_minute → 2 h
"""
from __future__ import annotations

import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

import pytest
import yaml

from nlp.dates_tr import DateTimeResolution, DateTimeResolver, _word_in, number_word_to_int

UTC = datetime.timezone.utc
ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")

# ── Shared fixed clock ─────────────────────────────────────────────────────

# Wednesday 2026-04-29 14:35:10 UTC  (weekday() == 2)
_FIXED_NOW = datetime.datetime(2026, 4, 29, 14, 35, 10, tzinfo=UTC)
_FIXED_CLOCK: Callable[[], datetime.datetime] = lambda: _FIXED_NOW
_TODAY_START = _FIXED_NOW.replace(hour=0, minute=0, second=0, microsecond=0)


def _resolver() -> DateTimeResolver:
    return DateTimeResolver(clock_now=_FIXED_CLOCK)


# ── Helper assertions ──────────────────────────────────────────────────────

def _assert_day(res: DateTimeResolution | None, expected_date: datetime.date) -> None:
    assert res is not None
    assert res.granularity == "day"
    expected_start = datetime.datetime(
        expected_date.year,
        expected_date.month,
        expected_date.day,
        tzinfo=ISTANBUL_TZ,
    ).astimezone(UTC)
    assert res.start_utc == expected_start
    assert res.end_utc == expected_start + datetime.timedelta(days=1)


def _assert_hour_minute(
    res: DateTimeResolution | None,
    expected_date: datetime.date,
    h: int,
    m: int,
) -> None:
    assert res is not None
    assert res.granularity == "hour_minute"
    expected_start = datetime.datetime(
        expected_date.year,
        expected_date.month,
        expected_date.day,
        h,
        m,
        tzinfo=ISTANBUL_TZ,
    ).astimezone(UTC)
    assert res.start_utc == expected_start
    assert res.end_utc == expected_start + datetime.timedelta(hours=2)


def test_time_of_day_shorthand_lookup_has_entries() -> None:
    path = Path(__file__).resolve().parents[1] / "nlp" / "lang_tr" / "time_of_day_shorthand.tr.yaml"
    mapping = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    assert isinstance(mapping, dict)
    assert len(mapping) >= 15
    assert mapping["aks"] == "akşam"


# ── Relative day expressions ───────────────────────────────────────────────

def test_bugun_day_granularity() -> None:
    res = _resolver().resolve("bugün")
    _assert_day(res, _TODAY_START.date())


def test_yarin_day_granularity() -> None:
    res = _resolver().resolve("yarın")
    tomorrow = (_TODAY_START + datetime.timedelta(days=1)).date()
    _assert_day(res, tomorrow)


def test_dun_day_granularity() -> None:
    res = _resolver().resolve("dün")
    yesterday = (_TODAY_START - datetime.timedelta(days=1)).date()
    _assert_day(res, yesterday)


def test_bugun_with_time() -> None:
    res = _resolver().resolve("bugün saat 21:30")
    _assert_hour_minute(res, _TODAY_START.date(), 21, 30)


def test_yarin_with_time() -> None:
    tomorrow = (_TODAY_START + datetime.timedelta(days=1)).date()
    res = _resolver().resolve("yarın saat 18:00")
    _assert_hour_minute(res, tomorrow, 18, 0)


# ── Named weekdays ─────────────────────────────────────────────────────────

# Fixed clock: Wednesday 2026-04-29 (weekday=2)
# "cuma" = Friday = weekday 4 → 2 days ahead = 2026-05-01
def test_cuma_nearest_future() -> None:
    res = _resolver().resolve("cuma")
    # Nearest Friday from Wednesday: +2 days → 2026-05-01
    _assert_day(res, datetime.date(2026, 5, 1))


def test_pazartesi_nearest_future() -> None:
    # Monday = weekday 0; from Wednesday (2) → (0-2)%7 = 5 days → 2026-05-04
    res = _resolver().resolve("pazartesi")
    _assert_day(res, datetime.date(2026, 5, 4))


def test_carsamba_same_day() -> None:
    # Wednesday = today → days_ahead = 0 → returns today
    res = _resolver().resolve("çarşamba")
    _assert_day(res, _TODAY_START.date())


def test_pazar_nearest_future() -> None:
    # Sunday = weekday 6; from Wednesday (2) → (6-2)%7 = 4 days → 2026-05-03
    res = _resolver().resolve("pazar")
    _assert_day(res, datetime.date(2026, 5, 3))


def test_cuma_with_time() -> None:
    res = _resolver().resolve("cuma saat 21:30")
    _assert_hour_minute(res, datetime.date(2026, 5, 1), 21, 30)


def test_weekday_abbreviation_cmt_resolves_to_saturday() -> None:
    res = _resolver().resolve("cmt")
    _assert_day(res, datetime.date(2026, 5, 2))


def test_pazar_does_not_match_pazartesi() -> None:
    # "pazar" should NOT fire when the token is "pazartesi"
    res = _resolver().resolve("pazartesi")
    # Should be parsed as pazartesi (Monday=+5d), NOT pazar (Sunday=+4d)
    assert res is not None
    assert res.start_utc.astimezone(ISTANBUL_TZ).date() == datetime.date(2026, 5, 4)


# ── Week expressions ───────────────────────────────────────────────────────

def test_bu_hafta() -> None:
    # Monday of current week: 2026-04-27 (Wednesday is day 2 → -2 days)
    res = _resolver().resolve("bu hafta")
    assert res is not None
    assert res.granularity == "week"
    expected_start = datetime.datetime(2026, 4, 27, tzinfo=ISTANBUL_TZ).astimezone(UTC)
    assert res.start_utc == expected_start
    assert res.end_utc == expected_start + datetime.timedelta(weeks=1)


def test_onumüzdeki_hafta() -> None:
    res = _resolver().resolve("önümüzdeki hafta")
    assert res is not None
    assert res.granularity == "week"
    expected_start = datetime.datetime(2026, 5, 4, tzinfo=ISTANBUL_TZ).astimezone(UTC)
    assert res.start_utc == expected_start
    assert res.end_utc == expected_start + datetime.timedelta(weeks=1)


def test_gecen_hafta() -> None:
    res = _resolver().resolve("geçen hafta")
    assert res is not None
    assert res.granularity == "week"
    expected_start = datetime.datetime(2026, 4, 20, tzinfo=ISTANBUL_TZ).astimezone(UTC)
    assert res.start_utc == expected_start
    assert res.end_utc == expected_start + datetime.timedelta(weeks=1)


# ── Explicit date expressions ──────────────────────────────────────────────

def test_explicit_date_day_only() -> None:
    res = _resolver().resolve("27 Nisan")
    # "nisan" = April = month 4; year defaults to clock year = 2026
    _assert_day(res, datetime.date(2026, 4, 27))


def test_explicit_date_with_year() -> None:
    res = _resolver().resolve("27 Nisan 2025")
    _assert_day(res, datetime.date(2025, 4, 27))


def test_explicit_date_with_time() -> None:
    res = _resolver().resolve("27 Nisan saat 21:30")
    _assert_hour_minute(res, datetime.date(2026, 4, 27), 21, 30)


def test_explicit_date_with_bare_time() -> None:
    res = _resolver().resolve("27 Nisan 21:30")
    _assert_hour_minute(res, datetime.date(2026, 4, 27), 21, 30)


def test_explicit_other_month() -> None:
    res = _resolver().resolve("15 Eylül")
    _assert_day(res, datetime.date(2026, 9, 15))


def test_number_word_to_int_parses_long_prefixes() -> None:
    assert number_word_to_int(["iki", "bin", "yirmi", "dört"]) == (2024, 4)
    assert number_word_to_int(["yirmi", "bir", "kasım"]) == (21, 2)
    assert number_word_to_int(["sıfır", "yıl"]) == (0, 1)


def test_parse_ordinal_phrase_handles_closed_forms() -> None:
    resolver = _resolver()
    assert resolver.parse_ordinal_phrase(["birinci"]) == (1, "forward", 1)
    assert resolver.parse_ordinal_phrase(["üçüncü"]) == (3, "forward", 1)
    assert resolver.parse_ordinal_phrase(["3'üncü"]) == (3, "forward", 1)
    assert resolver.parse_ordinal_phrase(["3."]) == (3, "forward", 1)
    assert resolver.parse_ordinal_phrase(["sonuncu"]) == (-1, "reverse", 1)


def test_gecen_ay_resolves_to_previous_month() -> None:
    res = _resolver().resolve("geçen ay")
    assert res is not None
    assert res.granularity == "month"
    assert res.polarity == "past"
    assert res.start_utc == datetime.datetime(2026, 2, 28, 21, 0, tzinfo=UTC)
    assert res.end_utc == datetime.datetime(2026, 3, 31, 21, 0, tzinfo=UTC)


def test_gecen_yil_resolves_to_previous_year() -> None:
    res = _resolver().resolve("geçen yıl")
    assert res is not None
    assert res.granularity == "year"
    assert res.polarity == "past"
    assert res.start_utc == datetime.datetime(2024, 12, 31, 21, 0, tzinfo=UTC)
    assert res.end_utc == datetime.datetime(2025, 12, 31, 21, 0, tzinfo=UTC)


def test_dunden_once_resolves_to_two_days_ago() -> None:
    res = _resolver().resolve("dünden önce")
    assert res is not None
    assert res.granularity == "day"
    assert res.polarity == "past"
    assert res.start_utc == datetime.datetime(2026, 4, 26, 21, 0, tzinfo=UTC)
    assert res.end_utc == datetime.datetime(2026, 4, 28, 21, 0, tzinfo=UTC)


def test_iki_gun_sonra_resolves_future_day() -> None:
    res = _resolver().resolve("iki gün sonra")
    assert res is not None
    assert res.granularity == "day"
    assert res.polarity == "future"
    assert res.start_utc == datetime.datetime(2026, 4, 30, 21, 0, tzinfo=UTC)
    assert res.end_utc == datetime.datetime(2026, 5, 1, 21, 0, tzinfo=UTC)


def test_hafta_sonu_resolves_to_upcoming_weekend() -> None:
    res = _resolver().resolve("hafta sonu")
    assert res is not None
    assert res.granularity == "week"
    assert res.polarity == "future"
    assert res.start_utc == datetime.datetime(2026, 5, 1, 21, 0, tzinfo=UTC)
    assert res.end_utc == datetime.datetime(2026, 5, 3, 21, 0, tzinfo=UTC)


def test_fractional_time_yarim_saat_sonra_is_future_hour_minute() -> None:
    res = _resolver().resolve("yarım saat sonra")
    assert res is not None
    assert res.granularity == "hour_minute"
    assert res.polarity == "future"
    assert res.start_utc == _FIXED_NOW + datetime.timedelta(minutes=30)
    assert res.end_utc == _FIXED_NOW + datetime.timedelta(hours=2, minutes=30)


def test_fractional_time_iki_bucuk_saat_sonra_is_future_hour_minute() -> None:
    res = _resolver().resolve("iki buçuk saat sonra")
    assert res is not None
    assert res.granularity == "hour_minute"
    assert res.polarity == "future"
    assert res.start_utc == _FIXED_NOW + datetime.timedelta(hours=2, minutes=30)
    assert res.end_utc == _FIXED_NOW + datetime.timedelta(hours=4, minutes=30)


def test_bucukta_without_hour_returns_none() -> None:
    assert _resolver().resolve("iki buçukta") is None


def test_gecen_yil_dst_crossing_2015_uses_istanbul_tz() -> None:
    clock = lambda: datetime.datetime(2016, 3, 1, 12, 0, tzinfo=UTC)
    resolver = DateTimeResolver(clock_now=clock)
    res = resolver.resolve("geçen yıl")
    assert res is not None
    assert res.polarity == "past"
    assert res.start_utc == datetime.datetime(2014, 12, 31, 22, 0, tzinfo=UTC)
    assert res.end_utc == datetime.datetime(2015, 12, 31, 22, 0, tzinfo=UTC)


def test_number_word_to_int_parses_long_prefixes() -> None:
    assert number_word_to_int(["iki", "bin", "yirmi", "dört"]) == (2024, 4)
    assert number_word_to_int(["yirmi", "bir", "kasım"]) == (21, 2)
    assert number_word_to_int(["sıfır", "yıl"]) == (0, 1)


def test_fixed_holiday_name_resolves_to_cumhuriyet_bayrami() -> None:
    res = _resolver().resolve("Cumhuriyet Bayramı")
    _assert_day(res, datetime.date(2026, 10, 29))


def test_fixed_holiday_name_with_time_resolves() -> None:
    res = _resolver().resolve("Cumhuriyet Bayramı saat 20:00")
    _assert_hour_minute(res, datetime.date(2026, 10, 29), 20, 0)


def test_resolves_ramazan_bayrami_2026_from_hijri_table() -> None:
    clock = lambda: datetime.datetime(2026, 1, 1, tzinfo=UTC)
    resolver = DateTimeResolver(clock_now=clock)
    res = resolver.resolve("Ramazan Bayramı")
    _assert_day(res, datetime.date(2026, 4, 11))


def test_resolves_kurban_bayrami_2027_from_hijri_table() -> None:
    clock = lambda: datetime.datetime(2027, 1, 1, tzinfo=UTC)
    resolver = DateTimeResolver(clock_now=clock)
    res = resolver.resolve("Kurban Bayramı")
    _assert_day(res, datetime.date(2027, 6, 6))


def test_holiday_apostrophe_alias_resolves_cumhuriyet_bayrami() -> None:
    res = _resolver().resolve("Cumhuriyet Bayramı'nda kim oynar")
    _assert_day(res, datetime.date(2026, 10, 29))


def test_generic_bayramda_resolves_next_bayram() -> None:
    clock = lambda: datetime.datetime(2026, 4, 29, tzinfo=UTC)
    resolver = DateTimeResolver(clock_now=clock)
    res = resolver.resolve("bayramda maç var mı")
    _assert_day(res, datetime.date(2026, 5, 19))


def test_generic_bayramda_after_gencler_bayrami_resolves_kurban_bayrami() -> None:
    clock = lambda: datetime.datetime(2026, 5, 20, tzinfo=UTC)
    resolver = DateTimeResolver(clock_now=clock)
    res = resolver.resolve("bayramda maç var mı")
    _assert_day(res, datetime.date(2026, 6, 18))


def test_hijri_table_sha_pinned_in_chart() -> None:
    from nlp.dates.hijri import VENDORED_HIJRI_TABLE_SHA, compute_table_sha

    assert compute_table_sha() == VENDORED_HIJRI_TABLE_SHA


def test_resolves_fifa_window_from_openfootball_cache() -> None:
    clock = lambda: datetime.datetime(2026, 3, 1, tzinfo=UTC)
    resolver = DateTimeResolver(clock_now=clock)
    res = resolver.resolve("milli maç haftası")
    assert res is not None
    assert res.granularity == "week"
    assert res.start_utc == datetime.datetime(2026, 3, 16, tzinfo=UTC)
    assert res.end_utc == datetime.datetime(2026, 3, 23, tzinfo=UTC)


def test_diyanet_override_table_respected() -> None:
    # The vendored Hijri table says 2026 Kurban Bayramı is 2026-06-17,
    # but the Diyanet override table should update the next observed date.
    res = _resolver().resolve("Kurban Bayramı")
    _assert_day(res, datetime.date(2026, 6, 18))


def test_holiday_beyond_horizon_returns_none() -> None:
    clock = lambda: datetime.datetime(2027, 12, 1, tzinfo=UTC)
    resolver = DateTimeResolver(
        clock_now=clock,
        date_default_window_days=180,
        time_default_period="am",
        holiday_lookup_horizon_days=30,
    )
    assert resolver.resolve("Cumhuriyet Bayramı") is None


def test_explicit_date_without_year_uses_next_occurrence_within_window() -> None:
    clock = lambda: datetime.datetime(2026, 12, 20, tzinfo=UTC)
    resolver = DateTimeResolver(
        clock_now=clock,
        date_default_window_days=180,
        time_default_period="am",
    )
    res = resolver.resolve("1 Ocak")
    _assert_day(res, datetime.date(2027, 1, 1))


def test_numeric_date_dot_format_resolves_to_2704() -> None:
    res = _resolver().resolve("27.04")
    _assert_day(res, datetime.date(2026, 4, 27))


def test_numeric_date_slash_format_resolves_to_2704() -> None:
    res = _resolver().resolve("27/04")
    _assert_day(res, datetime.date(2026, 4, 27))


def test_numeric_date_dot_year_resolves_to_2704_2026() -> None:
    res = _resolver().resolve("27.04.2026")
    _assert_day(res, datetime.date(2026, 4, 27))


# ── Time-only ─────────────────────────────────────────────────────────────

def test_time_only_saat() -> None:
    res = _resolver().resolve("saat 21:30")
    _assert_hour_minute(res, _TODAY_START.date(), 21, 30)


def test_time_only_bare() -> None:
    res = _resolver().resolve("21:30")
    _assert_hour_minute(res, _TODAY_START.date(), 21, 30)


def test_time_only_dot_separator_resolves_2130() -> None:
    res = _resolver().resolve("21.30")
    _assert_hour_minute(res, _TODAY_START.date(), 21, 30)


def test_time_only_comma_separator_resolves_2130() -> None:
    res = _resolver().resolve("21,30")
    _assert_hour_minute(res, _TODAY_START.date(), 21, 30)


def test_time_locative_21de_resolves_to_2100() -> None:
    res = _resolver().resolve("21'de")
    _assert_hour_minute(res, _TODAY_START.date(), 21, 0)


def test_time_saat_9_resolves_to_0900() -> None:
    res = _resolver().resolve("saat 9")
    _assert_hour_minute(res, _TODAY_START.date(), 9, 0)


def test_aksam_9_resolves_to_2100() -> None:
    res = _resolver().resolve("akşam 9")
    _assert_hour_minute(res, _TODAY_START.date(), 21, 0)


def test_ogleden_once_10_resolves_to_1000() -> None:
    res = _resolver().resolve("öğleden önce 10")
    _assert_hour_minute(res, _TODAY_START.date(), 10, 0)


def test_ogleden_sonra_3_resolves_to_1500() -> None:
    res = _resolver().resolve("öğleden sonra 3")
    _assert_hour_minute(res, _TODAY_START.date(), 15, 0)


def test_gece_yarisi_resolves_to_midnight() -> None:
    res = _resolver().resolve("gece yarısı")
    _assert_hour_minute(res, _TODAY_START.date(), 0, 0)


def test_time_shorthand_expanded() -> None:
    res = _resolver().resolve("aks 9")
    _assert_hour_minute(res, _TODAY_START.date(), 21, 0)


def test_numeric_date_ambiguous_slash_returns_none() -> None:
    assert _resolver().resolve("3/4/2025") is None


def test_numeric_date_dotted_form_unambiguous() -> None:
    res = _resolver().resolve("3.4.2025")
    _assert_day(res, datetime.date(2025, 4, 3))


def test_relative_date_resolves_against_client_tz() -> None:
    clock = lambda: datetime.datetime(2026, 1, 1, 23, 30, tzinfo=UTC)
    resolver = DateTimeResolver(clock_now=clock)
    res = resolver.resolve("bugün", client_tz="Europe/Berlin")
    assert res is not None
    assert res.start_utc == datetime.datetime(2026, 1, 1, 23, 0, tzinfo=UTC)


def test_time_zero_hour() -> None:
    res = _resolver().resolve("saat 00:00")
    _assert_hour_minute(res, _TODAY_START.date(), 0, 0)


# ── Adversarial: out-of-range time ────────────────────────────────────────

def test_out_of_range_hour_ignored() -> None:
    # "saat 25:00" — invalid hour, time component ignored
    # text has no other temporal content → should return None
    res = _resolver().resolve("saat 25:00")
    assert res is None


def test_out_of_range_minute_ignored() -> None:
    res = _resolver().resolve("saat 10:61")
    assert res is None


def test_out_of_range_date_returns_none() -> None:
    # February 31 is invalid
    res = _resolver().resolve("31 Şubat")
    assert res is None


# ── Unrecognized text ─────────────────────────────────────────────────────

def test_unrecognized_text_returns_none() -> None:
    assert _resolver().resolve("galatasaray maçı tahmini") is None


def test_empty_string_returns_none() -> None:
    assert _resolver().resolve("") is None


# ── Clock injection invariant ─────────────────────────────────────────────

def test_clock_injection_different_now() -> None:
    """Result changes when a different clock is injected — proves no global state."""
    clock_a = lambda: datetime.datetime(2026, 1, 5, tzinfo=UTC)  # Monday
    clock_b = lambda: datetime.datetime(2026, 1, 9, tzinfo=UTC)  # Friday

    res_a = DateTimeResolver(clock_now=clock_a).resolve("bugün")
    res_b = DateTimeResolver(clock_now=clock_b).resolve("bugün")

    assert res_a is not None and res_b is not None
    assert res_a.start_utc != res_b.start_utc


def test_clock_never_called_for_none() -> None:
    """Clock should still be called even for unrecognized input (no crash)."""
    called = []
    def clock() -> datetime.datetime:
        called.append(True)
        return _FIXED_NOW

    DateTimeResolver(clock_now=clock).resolve("anlamsız metin")
    assert called, "clock_now should have been called during resolve"


# ── Config integration ────────────────────────────────────────────────────

def test_cfg_nlp_clock_now_is_callable() -> None:
    """cfg.nlp_clock_now must be a callable returning a UTC-aware datetime."""
    from common.config import Config
    cfg = Config()
    result = cfg.nlp_clock_now()
    assert isinstance(result, datetime.datetime)
    assert result.tzinfo is not None
    assert result.utcoffset() == datetime.timedelta(0)


def test_cfg_nlp_clock_now_replaceable() -> None:
    """cfg.nlp_clock_now can be replaced per-instance for tests."""
    from common.config import Config
    cfg = Config()
    fixed = datetime.datetime(2026, 4, 27, 12, 0, tzinfo=UTC)
    cfg.nlp_clock_now = lambda: fixed  # type: ignore[assignment]
    assert cfg.nlp_clock_now() == fixed


# ── Granularity invariants ────────────────────────────────────────────────

def test_day_granularity_is_24h() -> None:
    res = _resolver().resolve("bugün")
    assert res is not None
    assert res.end_utc - res.start_utc == datetime.timedelta(days=1)


def test_week_granularity_is_7_days() -> None:
    res = _resolver().resolve("bu hafta")
    assert res is not None
    assert res.end_utc - res.start_utc == datetime.timedelta(weeks=1)


def test_hour_minute_granularity_is_2h() -> None:
    res = _resolver().resolve("saat 20:00")
    assert res is not None
    assert res.end_utc - res.start_utc == datetime.timedelta(hours=2)


# ── _word_in unit tests ───────────────────────────────────────────────────

def test_word_in_exact_match() -> None:
    assert _word_in("pazar", "pazar günü") is True


def test_word_in_not_partial_match() -> None:
    assert _word_in("pazar", "pazartesi günü") is False


def test_word_in_at_start() -> None:
    assert _word_in("cuma", "cuma maçı") is True


def test_word_in_at_end() -> None:
    assert _word_in("cuma", "bu cuma") is True


def test_word_in_missing() -> None:
    assert _word_in("perşembe", "cuma günü") is False
