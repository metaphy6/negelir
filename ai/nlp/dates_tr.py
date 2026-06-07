"""Phase 10 §10.5 — Turkish date/time resolver.

Resolves Turkish temporal expressions to UTC datetime ranges:
  "bugün", "yarın", "dün"          → day-granularity range
  "cuma", "pazartesi", …           → nearest-future weekday day range
  "bu hafta", "önümüzdeki hafta"   → week-granularity range
  "27 Nisan", "27 Nisan 2026"      → explicit-date day range
  "saat 21:30", "21:30"            → today + time → 2 h match window
  "27 Nisan saat 21:30"            → combined explicit date + time

ALL resolution is driven through the ``clock_now`` callable injected at
construction time, never through a bare ``datetime.datetime.now()`` call.
This mirrors §8.16.1 boottime/monotonic clock discipline and makes every
unit test fully deterministic.

Usage::

    from nlp.dates_tr import DateTimeResolver, DateTimeResolution
    resolver = DateTimeResolver(clock_now=cfg.nlp_clock_now)
    result = resolver.resolve("cuma saat 21:30")
    # result.start_utc, result.end_utc, result.granularity
"""
from __future__ import annotations

import calendar
import datetime
import json
import re
from pathlib import Path
from typing import Callable, NamedTuple
from zoneinfo import ZoneInfo

import yaml

from common.text.turkish import lowercase_tr, parse_number_word, int_to_number_word
from nlp.dates.hijri import resolve_hijri_observed_date

# ── Public types ──────────────────────────────────────────────────────────


class DateTimeResolution(NamedTuple):
    """A resolved temporal expression.

    start_utc:
        UTC datetime of the start of the resolved range.
    end_utc:
        UTC datetime of the end of the resolved range (exclusive).
        For ``granularity="day"``   : ``start_utc + 24 h``.
        For ``granularity="week"``  : ``start_utc + 7 days``.
        For ``granularity="hour_minute"``: ``start_utc + 2 h`` (match window).
    granularity:
        One of ``"day"``, ``"week"``, ``"month"``, ``"year"``, ``"hour_minute"``.
    polarity:
        ``"past"``, ``"present"``, or ``"future"`` for relative time semantics.
    """

    start_utc: datetime.datetime
    end_utc: datetime.datetime
    granularity: str
    polarity: str = "present"


# ── Turkish month names (1-indexed) ──────────────────────────────────────

_MONTHS_TR: dict[str, int] = {
    "ocak": 1,
    "şubat": 2,
    "mart": 3,
    "nisan": 4,
    "mayıs": 5,
    "haziran": 6,
    "temmuz": 7,
    "ağustos": 8,
    "eylül": 9,
    "ekim": 10,
    "kasım": 11,
    "aralık": 12,
}

# ── Turkish weekday names (Monday=0, …, Sunday=6, per Python's weekday()) ─

_WEEKDAYS_TR: dict[str, int] = {
    "pazartesi": 0,
    "pzt": 0,
    "salı": 1,
    "sal": 1,
    "çarşamba": 2,
    "çar": 2,
    "perşembe": 3,
    "per": 3,
    "cuma": 4,
    "cum": 4,
    "cumartesi": 5,
    "cmt": 5,
    "pazar": 6,
    "paz": 6,
}

# ── Compiled regex patterns ───────────────────────────────────────────────

# "saat 21:30", "21:30", "21.30", "21,30", "saat 9", "21'de" / "21de"
_TIME_SAAT_RE = re.compile(r"saat\s+(\d{1,2})(?:(?:[:.,](\d{2}))?)")
_TIME_BARE_RE = re.compile(r"\b(\d{1,2})[:.,](\d{2})\b")
_TIME_LOCATIVE_RE = re.compile(r"\b(\d{1,2})'?(de|da)\b")

# "27 nisan" or "27nisan" or "27 nisan 2026" — Turkish locale, case-insensitive via
# caller-side lowercase_tr so the regex literals use already-lowercased forms.
_DATE_RE = re.compile(
    r"(\d{1,2})\s*(" + "|".join(re.escape(m) for m in _MONTHS_TR) + r")(?:\s+(\d{4}))?"
)

# "27/04", "27.04", "27.04.2026" — numeric day/month forms accepted in Turkish input.
_DATE_NUMERIC_RE = re.compile(r"\b(\d{1,2})[/.](\d{1,2})(?:[/.](\d{4}))?\b")

_TIME_OF_DAY_PHRASE_RE = re.compile(
    r"\b(gece yarısı|öğleden önce|öğleden sonra|akşam|sabah|gece)\b"
)
_TIME_OF_DAY_NUMERIC_RE = re.compile(
    r"\b(akşam|sabah|öğleden önce|öğleden sonra|gece)\s+(?:saat\s+)?(\d{1,2})(?:(?:[:.,](\d{2}))?)?\b"
)
_TIME_OF_DAY_SHORTHAND_PATH = Path(__file__).resolve().parent / "lang_tr" / "time_of_day_shorthand.tr.yaml"
_TIME_OF_DAY_SHORTHAND_LOOKUP: dict[str, str] | None = None

_DEFAULT_HOLIDAY_LOOKUP_HORIZON_DAYS = 540


def _normalize_apostrophes(text: str) -> str:
    return text.replace("’", "").replace("'", "").replace("`", "")


def _load_time_of_day_shorthand_lookup() -> dict[str, str]:
    global _TIME_OF_DAY_SHORTHAND_LOOKUP
    if _TIME_OF_DAY_SHORTHAND_LOOKUP is None:
        try:
            raw = yaml.safe_load(_TIME_OF_DAY_SHORTHAND_PATH.read_text(encoding="utf-8")) or {}
        except FileNotFoundError:
            raw = {}
        if not isinstance(raw, dict):
            raise ValueError("time_of_day_shorthand.tr.yaml must contain a mapping")
        lookup: dict[str, str] = {}
        for shorthand, expanded in raw.items():
            if not isinstance(shorthand, str) or not isinstance(expanded, str):
                raise ValueError("time_of_day_shorthand.tr.yaml entries must map strings to strings")
            lookup[shorthand.strip().lower()] = expanded.strip().lower()
        _TIME_OF_DAY_SHORTHAND_LOOKUP = lookup
    assert _TIME_OF_DAY_SHORTHAND_LOOKUP is not None
    return _TIME_OF_DAY_SHORTHAND_LOOKUP


def _expand_time_of_day_shorthand(text: str) -> str:
    lookup = _load_time_of_day_shorthand_lookup()
    if not lookup:
        return text
    for shorthand, expanded in lookup.items():
        text = re.sub(rf"\b{re.escape(shorthand)}\b", expanded, text)
    return text


def _disambiguate_numeric_date(text: str) -> list[str] | None:
    date_m = _DATE_NUMERIC_RE.search(text)
    if not date_m:
        return None
    day = int(date_m.group(1))
    month = int(date_m.group(2))
    if day <= 12 and month <= 12 and day != month and text[date_m.start() + len(date_m.group(1))] == "/":
        return [f"{day} {_MONTHS_TR[month]} {date_m.group(3) or datetime.datetime.now().year}", f"{month} {_MONTHS_TR[day]} {date_m.group(3) or datetime.datetime.now().year}"]
    return None


def _to_local_now(now: datetime.datetime, client_tz: str | datetime.tzinfo | None) -> datetime.datetime:
    if client_tz is None:
        return now.astimezone(_ISTANBUL_TZ)
    tzinfo = client_tz if isinstance(client_tz, datetime.tzinfo) else ZoneInfo(str(client_tz))
    return now.astimezone(tzinfo)

_HOLIDAY_CONFIG_PATH = Path(__file__).resolve().parent / "dates" / "holidays_tr.yaml"
_DIYANET_OVERRIDE_PATH = Path(__file__).resolve().parent / "dates" / "_diyanet_overrides.tr.yaml"
_FIFA_WINDOW_CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "nlp" / "fifa_windows"

class _HolidayDefinition(NamedTuple):
    key: str
    aliases: tuple[str, ...]
    date_kind: str
    fixed_month: int | None
    fixed_day: int | None
    lookup_key: str | None

_TWO_HOURS = datetime.timedelta(hours=2)
_ONE_DAY = datetime.timedelta(days=1)
_ONE_WEEK = datetime.timedelta(weeks=1)

_DEFAULT_DATE_WINDOW_DAYS = 180
_DEFAULT_TIME_DEFAULT_PERIOD = "am"

_ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")
_ORDINAL_SUFFIXES = ("inci", "ıncı", "uncu", "üncü")

_FRACTIONAL_HOUR_RE = re.compile(r"\b(\d+|[a-zığüşöç]+)\s+buçuk\s+saat\s+sonra\b")
_HALF_HOUR_RE = re.compile(r"\b(yarım|çeyrek)\s+saat\s+sonra\b")
_BUCUKTA_RE = re.compile(r"\b(\d{1,2})\s+buçukta\b")
_RELATIVE_DAY_RE = re.compile(r"\b(\d+|[a-zığüşöç]+)\s+gün\s+(önce|sonra)\b")
_RELATIVE_WEEK_RE = re.compile(r"\b(\d+|[a-zığüşöç]+)\s+hafta\s+sonra\b")
_LAST_MONTH_RE = re.compile(r"\bgeçen ay\b")
_LAST_YEAR_RE = re.compile(r"\bgeçen yıl\b")
_PREVIOUS_WEEK_RE = re.compile(r"\bönceki hafta\b")
_YESTERDAY_BEFORE_RE = re.compile(r"\bdünden önce\b")
_WEEKEND_RE = re.compile(r"\bhafta sonu\b")

# ── Resolver ─────────────────────────────────────────────────────────────


class DateTimeResolver:
    """Resolves a normalized Turkish temporal string to a UTC range.

    Parameters
    ----------
    clock_now:
        Zero-argument callable that returns the current UTC
        :class:`datetime.datetime`.  Must return a timezone-aware value
        (``tzinfo=datetime.timezone.utc``).  Injected so tests can pin
        the clock without monkey-patching globals.
    """

    def __init__(
        self,
        clock_now: Callable[[], datetime.datetime],
        date_default_window_days: int = _DEFAULT_DATE_WINDOW_DAYS,
        time_default_period: str = _DEFAULT_TIME_DEFAULT_PERIOD,
        holiday_lookup_horizon_days: int = _DEFAULT_HOLIDAY_LOOKUP_HORIZON_DAYS,
    ) -> None:
        if time_default_period not in {"am", "pm"}:
            raise ValueError("time_default_period must be 'am' or 'pm'")

        self._clock_now = clock_now
        self._date_default_window = datetime.timedelta(days=date_default_window_days)
        self._time_default_period = time_default_period
        self._holiday_lookup_horizon = datetime.timedelta(days=holiday_lookup_horizon_days)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, text: str, client_tz: str | datetime.tzinfo | None = None) -> DateTimeResolution | None:
        """Return a :class:`DateTimeResolution` for *text*, or ``None``.

        *text* should already have passed through the §10.1 normalization
        pipeline (NFC, Turkish lowercase, punctuation normalization).  The
        resolver re-applies :func:`~common.text.turkish.lowercase_tr` as a
        safety net but does NOT run the full normalize pipeline itself.

        Returns ``None`` when no temporal expression is recognized.
        """
        text_lower = lowercase_tr(text.strip())
        text_lower = _normalize_apostrophes(text_lower)
        text_lower = _expand_time_of_day_shorthand(text_lower)
        now = self._clock_now()
        local_now = _to_local_now(now, client_tz)
        today_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)

        # ── 1. Extract optional time component ────────────────────────
        time_delta: datetime.timedelta | None = None
        time_m = _TIME_SAAT_RE.search(text_lower)
        if time_m:
            h = int(time_m.group(1))
            m_min = int(time_m.group(2) or 0)
            if 0 <= h < 24 and 0 <= m_min < 60:
                time_delta = datetime.timedelta(hours=h, minutes=m_min)

        if time_delta is None:
            time_m = _TIME_BARE_RE.search(text_lower)
            if time_m:
                h, m_min = int(time_m.group(1)), int(time_m.group(2))
                if 0 <= h < 24 and 0 <= m_min < 60:
                    time_delta = datetime.timedelta(hours=h, minutes=m_min)

        if time_delta is None:
            time_m = _TIME_OF_DAY_NUMERIC_RE.search(text_lower)
            if time_m:
                period = time_m.group(1)
                h = int(time_m.group(2))
                m_min = int(time_m.group(3) or 0)
                if 0 <= h < 24 and 0 <= m_min < 60:
                    time_delta = self._resolve_time(h, m_min, period)

        if time_delta is None:
            time_m = _TIME_LOCATIVE_RE.search(text_lower)
            if time_m:
                h = int(time_m.group(1))
                if 0 <= h < 24:
                    time_delta = datetime.timedelta(hours=h, minutes=0)

        if time_delta is None and "gece yarısı" in text_lower:
            time_delta = datetime.timedelta(hours=0)

        # ── 2. Explicit date: "27 nisan" / "27nisan" / "27 nisan 2026" ─
        date_m = _DATE_RE.search(text_lower)
        if date_m:
            day = int(date_m.group(1))
            month = _MONTHS_TR[date_m.group(2)]
            year = int(date_m.group(3)) if date_m.group(3) else local_now.year
            try:
                base_date = datetime.datetime(
                    year, month, day, tzinfo=local_now.tzinfo
                )
            except ValueError:
                return None
            if date_m.group(3) is None:
                base_date = self._apply_year_omission_window(base_date, local_now)
            return self._apply_time(base_date, time_delta)

        date_m = _DATE_NUMERIC_RE.search(text_lower)
        if date_m:
            day = int(date_m.group(1))
            month = int(date_m.group(2))
            year = int(date_m.group(3)) if date_m.group(3) else local_now.year
            separator = text_lower[date_m.start() + len(date_m.group(1))]
            if separator == "/" and day <= 12 and month <= 12 and day != month:
                return None
            try:
                base_date = datetime.datetime(
                    year, month, day, tzinfo=local_now.tzinfo
                )
            except ValueError:
                if time_delta is None:
                    return None
            else:
                if date_m.group(3) is None:
                    base_date = self._apply_year_omission_window(base_date, local_now)
                return self._apply_time(base_date, time_delta)

        holiday_resolution = self._resolve_holiday(text_lower, now)
        if holiday_resolution is not None:
            if holiday_resolution.granularity == "day":
                return self._apply_time(holiday_resolution.start_utc, time_delta)
            return holiday_resolution

        relative_resolution = self._resolve_relative_phrase(text_lower, now)
        if relative_resolution is not None:
            if relative_resolution.granularity == "hour_minute":
                return relative_resolution
            if time_delta is None:
                return relative_resolution
            return self._apply_time(relative_resolution.start_utc, time_delta, relative_resolution.polarity)

        # ── 3. Relative day keywords ───────────────────────────────────
        if "bugün" in text_lower:
            return self._apply_time(today_start, time_delta)
        if "yarın" in text_lower:
            return self._apply_time(today_start + _ONE_DAY, time_delta)
        if "dün" in text_lower:
            return self._apply_time(today_start - _ONE_DAY, time_delta)

        # ── 4. Week expressions ────────────────────────────────────────
        # Monday of the current week
        monday_this_week = today_start - datetime.timedelta(
            days=today_start.weekday()
        )
        if "önümüzdeki hafta" in text_lower:
            start = monday_this_week + _ONE_WEEK
            return self._make_resolution(
                start.astimezone(datetime.timezone.utc),
                (start + _ONE_WEEK).astimezone(datetime.timezone.utc),
                "week",
            )
        if "geçen hafta" in text_lower:
            start = monday_this_week - _ONE_WEEK
            return self._make_resolution(
                start.astimezone(datetime.timezone.utc),
                (start + _ONE_WEEK).astimezone(datetime.timezone.utc),
                "week",
            )
        if "bu hafta" in text_lower:
            return self._make_resolution(
                monday_this_week.astimezone(datetime.timezone.utc),
                (monday_this_week + _ONE_WEEK).astimezone(datetime.timezone.utc),
                "week",
            )

        # ── 5. Named weekdays — nearest future (or today) occurrence ──
        # Ordered from longest to shortest to avoid "pazar" matching inside
        # "pazartesi" (handled by word-boundary check below).
        for name, target_dow in sorted(
            _WEEKDAYS_TR.items(), key=lambda kv: -len(kv[0])
        ):
            if _word_in(name, text_lower):
                current_dow = today_start.weekday()
                days_ahead = (target_dow - current_dow) % 7
                # days_ahead == 0 means "today" — honour that convention.
                base_date = today_start + datetime.timedelta(days=days_ahead)
                return self._apply_time(base_date, time_delta)

        # ── 6. Time only (no date anchor) → resolve against today ─────
        if time_delta is not None:
            start = today_start + time_delta
            end = start + _TWO_HOURS
            return DateTimeResolution(start, end, "hour_minute")

        return None

    def _resolve_time(
        self,
        hour: int,
        minute: int,
        period: str | None,
    ) -> datetime.timedelta:
        if period == "midnight":
            hour = 0
        elif period in ("sabah", "öğleden önce"):  # explicit morning anchors
            if hour == 12:
                hour = 0
        elif period in ("akşam", "öğleden sonra", "gece"):  # evening anchors
            if hour < 12:
                hour += 12
        elif period == "am":
            if hour == 12:
                hour = 0
        elif period == "pm":
            if hour < 12:
                hour += 12
        elif self._time_default_period == "pm" and 1 <= hour <= 11:
            hour += 12
        return datetime.timedelta(hours=hour, minutes=minute)

    def _apply_year_omission_window(
        self,
        base_date: datetime.datetime,
        now: datetime.datetime,
    ) -> datetime.datetime:
        if base_date >= now:
            return base_date
        next_year = base_date.replace(year=base_date.year + 1)
        if next_year <= now + self._date_default_window:
            return next_year
        return base_date

    def _resolve_holiday(self, text_lower: str, now: datetime.datetime) -> DateTimeResolution | None:
        for holiday in _HOLIDAY_DEFINITIONS:
            for alias in holiday.aliases:
                if _word_in(alias, text_lower):
                    return self._resolve_holiday_date(holiday, now)

        if "bayramda" in text_lower or "bayramında" in text_lower:
            return self._resolve_next_bayram(now)

        return None

    def _resolve_next_bayram(
        self,
        now: datetime.datetime,
    ) -> DateTimeResolution | None:
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        candidates: list[DateTimeResolution] = []
        for holiday in _HOLIDAY_DEFINITIONS:
            if "bayram" not in holiday.key and not any(
                "bayram" in alias for alias in holiday.aliases
            ):
                continue
            holiday_resolution = self._resolve_holiday_date(holiday, now)
            if holiday_resolution is None:
                continue
            if holiday_resolution.start_utc < today_start:
                continue
            candidates.append(holiday_resolution)

        if not candidates:
            return None
        return min(candidates, key=lambda res: res.start_utc)

    def _resolve_holiday_date(
        self,
        holiday: _HolidayDefinition,
        now: datetime.datetime,
    ) -> DateTimeResolution | None:
        if holiday.date_kind == "fixed_gregorian":
            return self._resolve_fixed_gregorian_holiday(holiday, now)
        if holiday.date_kind == "fixed_hijri_observed":
            return self._resolve_hijri_observed_holiday(holiday, now)
        if holiday.date_kind == "fifa_window":
            return self._resolve_fifa_window_holiday(holiday, now)
        return None

    def _resolve_fixed_gregorian_holiday(
        self,
        holiday: _HolidayDefinition,
        now: datetime.datetime,
    ) -> DateTimeResolution | None:
        if holiday.fixed_month is None or holiday.fixed_day is None:
            return None

        today_start = self._local_midnight(now)
        candidate = datetime.datetime(
            today_start.year,
            holiday.fixed_month,
            holiday.fixed_day,
            tzinfo=today_start.tzinfo,
        )
        if candidate < today_start:
            candidate = candidate.replace(year=candidate.year + 1)

        if candidate - today_start > self._holiday_lookup_horizon:
            return None
        return self._make_resolution(
            candidate.astimezone(datetime.timezone.utc),
            (candidate + _ONE_DAY).astimezone(datetime.timezone.utc),
            "day",
        )

    def _resolve_hijri_observed_holiday(
        self,
        holiday: _HolidayDefinition,
        now: datetime.datetime,
    ) -> DateTimeResolution | None:
        today_start = self._local_midnight(now)
        for year in (today_start.year, today_start.year + 1):
            override = _DIYANET_OVERRIDES.get((year, holiday.key))
            if override is not None:
                month, day = override
            else:
                month_day = resolve_hijri_observed_date(holiday.lookup_key or holiday.key, year)
                if month_day is None:
                    continue
                month, day = month_day

            try:
                candidate = datetime.datetime(year, month, day, tzinfo=today_start.tzinfo)
            except ValueError:
                continue

            if candidate < today_start:
                continue
            if candidate - today_start > self._holiday_lookup_horizon:
                continue
            return self._make_resolution(
                candidate.astimezone(datetime.timezone.utc),
                (candidate + _ONE_DAY).astimezone(datetime.timezone.utc),
                "day",
            )
        return None

    def _resolve_fifa_window_holiday(
        self,
        holiday: _HolidayDefinition,
        now: datetime.datetime,
    ) -> DateTimeResolution | None:
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        for year in (today_start.year, today_start.year + 1):
            window = self._load_fifa_window(holiday.lookup_key or holiday.key, year)
            if window is None:
                continue
            start, end = window
            if end <= today_start:
                continue
            if start - today_start > self._holiday_lookup_horizon:
                continue
            granularity = "week" if end - start == _ONE_WEEK else "day"
            return DateTimeResolution(start, end, granularity)
        return None

    def _load_fifa_window(
        self,
        lookup_key: str,
        year: int,
    ) -> tuple[datetime.datetime, datetime.datetime] | None:
        path = _FIFA_WINDOW_CACHE_DIR / f"{year}.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None

        entry = raw.get(lookup_key)
        if not isinstance(entry, dict):
            return None

        try:
            start = datetime.datetime.fromisoformat(entry["start_date"]).replace(tzinfo=datetime.timezone.utc)
            end = datetime.datetime.fromisoformat(entry["end_date"]).replace(tzinfo=datetime.timezone.utc)
        except (KeyError, TypeError, ValueError):
            return None
        return (start, end)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_time(
        base_date: datetime.datetime,
        time_delta: datetime.timedelta | None,
        polarity: str = "present",
    ) -> DateTimeResolution:
        """Combine a date-midnight base with an optional intra-day offset."""
        if time_delta is not None:
            start = base_date + time_delta
            start_utc = start.astimezone(datetime.timezone.utc)
            return DateTimeResolution(
                start_utc,
                (start + _TWO_HOURS).astimezone(datetime.timezone.utc),
                "hour_minute",
                polarity,
            )
        base_utc = base_date.astimezone(datetime.timezone.utc)
        return DateTimeResolution(base_utc, (base_date + _ONE_DAY).astimezone(datetime.timezone.utc), "day", polarity)

    @staticmethod
    def _make_resolution(
        start: datetime.datetime,
        end: datetime.datetime,
        granularity: str,
        polarity: str = "present",
    ) -> DateTimeResolution:
        return DateTimeResolution(start, end, granularity, polarity)

    def _resolve_relative_phrase(
        self,
        text_lower: str,
        now: datetime.datetime,
    ) -> DateTimeResolution | None:
        if _BUCUKTA_RE.search(text_lower) and self._has_no_explicit_hour(text_lower):
            return None

        fractional = self._resolve_fractional_time(text_lower, now)
        if fractional is not None:
            return fractional

        if _PREVIOUS_WEEK_RE.search(text_lower):
            return self._resolve_week(now, -1, "past")
        if _YESTERDAY_BEFORE_RE.search(text_lower):
            start = self._local_midnight(now) - _ONE_DAY * 2
            end = self._local_midnight(now)
            return self._make_resolution(
                start.astimezone(datetime.timezone.utc),
                end.astimezone(datetime.timezone.utc),
                "day",
                "past",
            )
        relative_day = _RELATIVE_DAY_RE.search(text_lower)
        if relative_day:
            quantity_text, direction = relative_day.groups()
            if quantity_text.isdigit():
                quantity_days = int(quantity_text)
            else:
                quantity = parse_number_word(quantity_text)
                if quantity is None:
                    quantity_days = 0
                else:
                    quantity_days = quantity
            if direction == "önce":
                start = self._local_midnight(now) - datetime.timedelta(days=quantity_days)
                end = self._local_midnight(now)
                return self._make_resolution(
                    start.astimezone(datetime.timezone.utc),
                    end.astimezone(datetime.timezone.utc),
                    "day",
                    "past",
                )
            start = self._local_midnight(now) + datetime.timedelta(days=quantity_days)
            end = self._local_midnight(now) + datetime.timedelta(days=quantity_days + 1)
            return self._make_resolution(
                start.astimezone(datetime.timezone.utc),
                end.astimezone(datetime.timezone.utc),
                "day",
                "future",
            )
        relative_week = _RELATIVE_WEEK_RE.search(text_lower)
        if relative_week:
            quantity_text = relative_week.group(1)
            if quantity_text.isdigit():
                quantity = int(quantity_text)
            else:
                quantity = parse_number_word(quantity_text) or 0
            return self._resolve_week(now, quantity, "future")
        if _LAST_MONTH_RE.search(text_lower):
            return self._resolve_previous_month(now)
        if _LAST_YEAR_RE.search(text_lower):
            return self._resolve_previous_year(now)
        if _WEEKEND_RE.search(text_lower):
            return self._resolve_weekend(now)
        return None

    @staticmethod
    def _has_no_explicit_hour(text_lower: str) -> bool:
        return not (_TIME_SAAT_RE.search(text_lower) or _TIME_BARE_RE.search(text_lower) or _TIME_LOCATIVE_RE.search(text_lower))

    @staticmethod
    def _local_midnight(now: datetime.datetime) -> datetime.datetime:
        local = now.astimezone(_ISTANBUL_TZ)
        return local.replace(hour=0, minute=0, second=0, microsecond=0)

    @staticmethod
    def _resolve_week(now: datetime.datetime, week_offset: int, polarity: str) -> DateTimeResolution:
        local_midnight = DateTimeResolver._local_midnight(now)
        monday_this_week = local_midnight - datetime.timedelta(days=local_midnight.weekday())
        start = monday_this_week + _ONE_WEEK * week_offset
        end = start + _ONE_WEEK
        return DateTimeResolver._make_resolution(
            start.astimezone(datetime.timezone.utc),
            end.astimezone(datetime.timezone.utc),
            "week",
            polarity,
        )

    @staticmethod
    def _resolve_previous_month(now: datetime.datetime) -> DateTimeResolution:
        local_midnight = DateTimeResolver._local_midnight(now)
        first_this_month = local_midnight.replace(day=1)
        previous_month_end = first_this_month
        previous_month_start = (first_this_month - datetime.timedelta(days=1)).replace(day=1)
        return DateTimeResolver._make_resolution(
            previous_month_start.astimezone(datetime.timezone.utc),
            previous_month_end.astimezone(datetime.timezone.utc),
            "month",
            "past",
        )

    @staticmethod
    def _resolve_previous_year(now: datetime.datetime) -> DateTimeResolution:
        local_midnight = DateTimeResolver._local_midnight(now)
        first_this_year = local_midnight.replace(month=1, day=1)
        previous_year_start = first_this_year.replace(year=first_this_year.year - 1)
        return DateTimeResolver._make_resolution(
            previous_year_start.astimezone(datetime.timezone.utc),
            first_this_year.astimezone(datetime.timezone.utc),
            "year",
            "past",
        )

    @staticmethod
    def _resolve_weekend(now: datetime.datetime) -> DateTimeResolution:
        local_midnight = DateTimeResolver._local_midnight(now)
        weekday = local_midnight.weekday()
        saturday = local_midnight + datetime.timedelta(days=(5 - weekday) % 7)
        start = saturday.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + datetime.timedelta(days=2)
        return DateTimeResolver._make_resolution(
            start.astimezone(datetime.timezone.utc),
            end.astimezone(datetime.timezone.utc),
            "week",
            "future",
        )

    @staticmethod
    def _resolve_fractional_time(text_lower: str, now: datetime.datetime) -> DateTimeResolution | None:
        fractional_match = _FRACTIONAL_HOUR_RE.search(text_lower)
        if fractional_match:
            quantity_text = fractional_match.group(1)
            if quantity_text.isdigit():
                hours = int(quantity_text)
            else:
                hours = parse_number_word(quantity_text) or 0
            delta = datetime.timedelta(hours=hours, minutes=30)
            start = now + delta
            return DateTimeResolution(start, start + _TWO_HOURS, "hour_minute", "future")
        half_match = _HALF_HOUR_RE.search(text_lower)
        if half_match:
            amount = half_match.group(1)
            minutes = 30 if amount == "yarım" else 15
            start = now + datetime.timedelta(minutes=minutes)
            return DateTimeResolution(start, start + _TWO_HOURS, "hour_minute", "future")
        return None

    @staticmethod
    def parse_ordinal_phrase(tokens: list[str]) -> tuple[int, str, int] | None:
        if not tokens:
            return None

        token = tokens[0]
        if token == "sonuncu":
            return (-1, "reverse", 1)

        digit_match = re.match(r"^(\d+)(?:'inci|'ıncı|'uncu|'üncü|\.)$", token)
        if digit_match:
            return (int(digit_match.group(1)), "forward", 1)

        for suffix in _ORDINAL_SUFFIXES:
            if token.endswith(suffix):
                base = token[: -len(suffix)]
                parsed = parse_number_word(base)
                if parsed is not None:
                    return (parsed, "forward", 1)
        return None

    class PartialNumberEntity(NamedTuple):
        accumulator: int
        unit_pending: bool

    @staticmethod
    def detect_partial_number(tokens: list[str]) -> "DateTimeResolver.PartialNumberEntity" | None:
        if not tokens:
            return None
        result = number_word_to_int(tokens)
        if result is None:
            return None
        value, span = result
        if span == len(tokens):
            return DateTimeResolver.PartialNumberEntity(accumulator=value, unit_pending=True)
        return None


# ── Internal helpers ──────────────────────────────────────────────────────

def _load_holiday_definitions() -> tuple["_HolidayDefinition", ...]:
    try:
        raw = yaml.safe_load(_HOLIDAY_CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ()

    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError("holiday definitions must be a YAML list")

    definitions: list[_HolidayDefinition] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("holiday definition entries must be mapping objects")
        key = str(item["key"])
        date_kind = str(item["date_kind"])
        aliases = tuple(
            lowercase_tr(str(alias))
            for alias in item.get("name_aliases", [])
            if alias is not None
        )
        fixed_month = None
        fixed_day = None
        lookup_key = None
        if date_kind == "fixed_gregorian":
            fixed_md = str(item["fixed_md"])
            month_str, day_str = fixed_md.split("-")
            fixed_month = int(month_str)
            fixed_day = int(day_str)
        elif date_kind == "fixed_hijri_observed":
            lookup_key = str(item.get("hijri_year_lookup", key))
        elif date_kind == "fifa_window":
            lookup_key = str(item.get("fifa_window_lookup", key))

        definitions.append(
            _HolidayDefinition(
                key=key,
                aliases=aliases,
                date_kind=date_kind,
                fixed_month=fixed_month,
                fixed_day=fixed_day,
                lookup_key=lookup_key,
            )
        )
    return tuple(definitions)

_HOLIDAY_DEFINITIONS = _load_holiday_definitions()


def _load_diyanet_overrides() -> dict[tuple[int, str], tuple[int, int]]:
    try:
        raw = yaml.safe_load(_DIYANET_OVERRIDE_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}

    if raw is None:
        return {}
    if not isinstance(raw, list):
        raise ValueError("diyanet override table must be a YAML list")

    overrides: dict[tuple[int, str], tuple[int, int]] = {}
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("diyanet override entries must be mapping objects")
        year = int(item["year"])
        holiday_key = str(item["holiday_key"])
        date_str = str(item["date"])
        date = datetime.date.fromisoformat(date_str)
        overrides[(year, holiday_key)] = (date.month, date.day)
    return overrides


_DIYANET_OVERRIDES = _load_diyanet_overrides()


def _word_in(word: str, text: str) -> bool:
    """Return True when *word* appears as a whole token in *text*.

    Uses a lightweight boundary check (preceding/following character is
    not a letter) so that "pazar" does not match inside "pazartesi".
    """
    idx = text.find(word)
    if idx == -1:
        return False
    before_ok = idx == 0 or not text[idx - 1].isalpha()
    after_ok = idx + len(word) == len(text) or not text[idx + len(word)].isalpha()
    return before_ok and after_ok


def number_word_to_int(tokens: list[str]) -> tuple[int, int] | None:
    """Parse a prefix of Turkish number-word tokens into an integer and span."""
    for end in range(len(tokens), 0, -1):
        phrase = " ".join(tokens[:end])
        value = parse_number_word(phrase)
        if value is not None:
            return value, end
    return None


def number_word_to_ordinal_phrase(value: int) -> str:
    """Convert an integer to a Turkish ordinal phrase using the shared helper."""
    return int_to_number_word(value, register="ordinal")
