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

import datetime
import re
from typing import Callable, NamedTuple

from common.text.turkish import lowercase_tr

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
        One of ``"day"``, ``"week"``, ``"hour_minute"``.
    """

    start_utc: datetime.datetime
    end_utc: datetime.datetime
    granularity: str


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
    "salı": 1,
    "çarşamba": 2,
    "perşembe": 3,
    "cuma": 4,
    "cumartesi": 5,
    "pazar": 6,
}

# ── Compiled regex patterns ───────────────────────────────────────────────

# "saat 21:30" or bare "21:30" — match anywhere in the string
_TIME_RE = re.compile(r"(?:saat\s+)?(\d{1,2}):(\d{2})")

# "27 nisan" or "27 nisan 2026" — Turkish locale, case-insensitive via
# caller-side lowercase_tr so the regex literals use already-lowercased forms.
_DATE_RE = re.compile(
    r"(\d{1,2})\s+(" + "|".join(re.escape(m) for m in _MONTHS_TR) + r")(?:\s+(\d{4}))?",
)

_TWO_HOURS = datetime.timedelta(hours=2)
_ONE_DAY = datetime.timedelta(days=1)
_ONE_WEEK = datetime.timedelta(weeks=1)

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

    def __init__(self, clock_now: Callable[[], datetime.datetime]) -> None:
        self._clock_now = clock_now

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, text: str) -> DateTimeResolution | None:
        """Return a :class:`DateTimeResolution` for *text*, or ``None``.

        *text* should already have passed through the §10.1 normalization
        pipeline (NFC, Turkish lowercase, punctuation normalization).  The
        resolver re-applies :func:`~common.text.turkish.lowercase_tr` as a
        safety net but does NOT run the full normalize pipeline itself.

        Returns ``None`` when no temporal expression is recognized.
        """
        text_lower = lowercase_tr(text.strip())
        now = self._clock_now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # ── 1. Extract optional time component ────────────────────────
        time_delta: datetime.timedelta | None = None
        time_m = _TIME_RE.search(text_lower)
        if time_m:
            h, m_min = int(time_m.group(1)), int(time_m.group(2))
            if 0 <= h < 24 and 0 <= m_min < 60:
                time_delta = datetime.timedelta(hours=h, minutes=m_min)
            # Out-of-range values (e.g. "saat 25:00") → ignore, fall through

        # ── 2. Explicit date: "27 nisan" / "27 nisan 2026" ────────────
        date_m = _DATE_RE.search(text_lower)
        if date_m:
            day = int(date_m.group(1))
            month = _MONTHS_TR[date_m.group(2)]
            year = int(date_m.group(3)) if date_m.group(3) else now.year
            try:
                base_date = datetime.datetime(
                    year, month, day, tzinfo=datetime.timezone.utc
                )
            except ValueError:
                return None
            return self._apply_time(base_date, time_delta)

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
            return DateTimeResolution(start, start + _ONE_WEEK, "week")
        if "geçen hafta" in text_lower:
            start = monday_this_week - _ONE_WEEK
            return DateTimeResolution(start, start + _ONE_WEEK, "week")
        if "bu hafta" in text_lower:
            return DateTimeResolution(
                monday_this_week, monday_this_week + _ONE_WEEK, "week"
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

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_time(
        base_date: datetime.datetime,
        time_delta: datetime.timedelta | None,
    ) -> DateTimeResolution:
        """Combine a date-midnight base with an optional intra-day offset."""
        if time_delta is not None:
            start = base_date + time_delta
            return DateTimeResolution(start, start + _TWO_HOURS, "hour_minute")
        return DateTimeResolution(base_date, base_date + _ONE_DAY, "day")


# ── Internal helpers ──────────────────────────────────────────────────────

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
