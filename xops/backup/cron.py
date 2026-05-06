"""Phase 8 §8.3 — stdlib-only cron evaluator.

Honors the xops `stdlib-preference` doctrine (no `croniter` dep).
Parses 5-field UTC cron expressions: ``m h dom mon dow``.

Supported syntax (intentionally narrow):

* ``*``         — wildcard
* ``N``         — single number
* ``N-M``       — inclusive range (M >= N)
* ``N,M,...``   — comma list of any of the above primitives
* ``*/S``       — every-S step (S >= 1) over the full range
* ``N-M/S``     — every-S step inside a range

Field bounds:

* minute       0-59
* hour         0-23
* day-of-month 1-31
* month        1-12
* day-of-week  0-6 (0 = Sunday, 7 also accepted and folded to 0)

Any other syntax (named months/days, ``L``/``W``/``#`` extensions,
seconds, year fields) raises :class:`CronSyntaxError` LOUD at boot
so an operator typo cannot silently disable the backup cron.

Day-of-month vs day-of-week semantics follow Vixie-cron's "OR"
rule: when BOTH dom and dow are restricted (neither is ``*``), a
fire occurs if either matches; when one is ``*`` only the other
gates. This matches operator intuition for "every Sunday at 5 AM"
(``0 5 * * 0``) AND "1st of the month at 3 AM" (``0 3 1 * *``).

The evaluator is purely-functional: :func:`next_fire_after` takes
a wall-clock UTC ``datetime`` and returns the next-due UTC
``datetime`` strictly greater than it. The caller (the backup
agent's heartbeat) supplies the "now" — no module-level clock.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Final


class CronSyntaxError(ValueError):
    """Raised when a cron expression cannot be parsed.

    Distinct subclass so callers (config-validation paths) can
    refuse-to-start with a clear surface separate from generic
    ``ValueError`` noise.
    """


# Field-bound tuples: (lo, hi, name).
_FIELD_BOUNDS: Final[tuple[tuple[int, int, str], ...]] = (
    (0, 59, "minute"),
    (0, 23, "hour"),
    (1, 31, "dom"),
    (1, 12, "month"),
    (0, 6,  "dow"),
)

# Hard cap on the search window for next_fire_after — protects
# against impossible-to-satisfy cron expressions (e.g. ``0 0 31 2 *``)
# turning the heartbeat into a forever-loop. 4 years > any leap cycle.
_NEXT_FIRE_MAX_DAYS: Final[int] = 366 * 4


@dataclass(frozen=True)
class CronExpr:
    """Parsed 5-field cron expression."""

    minutes: frozenset[int]
    hours: frozenset[int]
    doms: frozenset[int]
    months: frozenset[int]
    dows: frozenset[int]
    raw: str
    # True when both dom and dow were ``*`` in the source — used to
    # short-circuit the Vixie-cron OR rule below.
    dom_was_star: bool
    dow_was_star: bool

    @property
    def fires_every_minute(self) -> bool:
        """Diagnostic helper — used by boot-validation to refuse
        impossibly-aggressive cron settings (e.g. operator typed
        ``* * * * *`` and meant ``0 3 * * *``)."""
        return (
            len(self.minutes) == 60
            and len(self.hours) == 24
            and len(self.months) == 12
            and self.dom_was_star
            and self.dow_was_star
        )


def _parse_field(token: str, lo: int, hi: int, name: str) -> frozenset[int]:
    """Expand a single cron field into the explicit set of matching
    integers. ``*`` → full range; ``,`` lists; ``-`` ranges; ``/N``
    steps. Day-of-week tolerates ``7`` (Sunday)."""
    if not token:
        raise CronSyntaxError(f"{name}: empty field")
    out: set[int] = set()
    for piece in token.split(","):
        piece = piece.strip()
        if not piece:
            raise CronSyntaxError(f"{name}: empty list element in {token!r}")
        # Step (``X/S``) post-strip.
        step = 1
        if "/" in piece:
            head, _, step_raw = piece.partition("/")
            try:
                step = int(step_raw)
            except ValueError as exc:
                raise CronSyntaxError(
                    f"{name}: step {step_raw!r} not an integer"
                ) from exc
            if step < 1:
                raise CronSyntaxError(
                    f"{name}: step must be >= 1 (got {step})"
                )
            piece = head
        # Range or wildcard.
        if piece == "*":
            start, end = lo, hi
        elif "-" in piece:
            start_raw, _, end_raw = piece.partition("-")
            try:
                start = int(start_raw)
                end = int(end_raw)
            except ValueError as exc:
                raise CronSyntaxError(
                    f"{name}: range bound not integer in {piece!r}"
                ) from exc
            if name == "dow":
                if start == 7:
                    start = 0
                if end == 7:
                    end = 0
            if not (lo <= start <= hi) or not (lo <= end <= hi):
                raise CronSyntaxError(
                    f"{name}: range {piece!r} outside [{lo}, {hi}]"
                )
            if end < start:
                raise CronSyntaxError(
                    f"{name}: range end < start in {piece!r}"
                )
        else:
            try:
                value = int(piece)
            except ValueError as exc:
                raise CronSyntaxError(
                    f"{name}: token {piece!r} not an integer"
                ) from exc
            if name == "dow" and value == 7:
                value = 0
            if not (lo <= value <= hi):
                raise CronSyntaxError(
                    f"{name}: value {value} outside [{lo}, {hi}]"
                )
            start = end = value
        for v in range(start, end + 1, step):
            out.add(v)
    if not out:
        raise CronSyntaxError(f"{name}: empty resolved set from {token!r}")
    return frozenset(out)


def parse_cron(expr: str) -> CronExpr:
    """Parse a 5-field cron expression. Raises :class:`CronSyntaxError`
    on any unsupported syntax (named months/days, ``L``/``W``/``#``,
    7-field forms, seconds, etc.)."""
    if not isinstance(expr, str):
        raise CronSyntaxError(f"cron must be str, got {type(expr).__name__}")
    parts = expr.split()
    if len(parts) != 5:
        raise CronSyntaxError(
            f"cron must have 5 fields (m h dom mon dow); got "
            f"{len(parts)} in {expr!r}"
        )
    minute_tok, hour_tok, dom_tok, month_tok, dow_tok = parts
    # Reject named-day/named-month forms loud — silent-fall-through
    # would let an operator typo (`SUN` instead of `0`) disable the
    # nightly backup forever.
    for tok, name in (
        (minute_tok, "minute"), (hour_tok, "hour"),
        (dom_tok, "dom"), (month_tok, "month"), (dow_tok, "dow"),
    ):
        if any(c.isalpha() for c in tok):
            raise CronSyntaxError(
                f"{name}: alphabetic chars not supported (got {tok!r}); "
                f"use numeric form (0-6 for dow, 1-12 for month)"
            )
        for ch in tok:
            if not (ch.isdigit() or ch in "*,-/"):
                raise CronSyntaxError(
                    f"{name}: unsupported char {ch!r} in {tok!r}"
                )
    minutes = _parse_field(minute_tok, *_FIELD_BOUNDS[0])
    hours = _parse_field(hour_tok, *_FIELD_BOUNDS[1])
    doms = _parse_field(dom_tok, *_FIELD_BOUNDS[2])
    months = _parse_field(month_tok, *_FIELD_BOUNDS[3])
    dows = _parse_field(dow_tok, *_FIELD_BOUNDS[4])
    return CronExpr(
        minutes=minutes,
        hours=hours,
        doms=doms,
        months=months,
        dows=dows,
        raw=expr,
        dom_was_star=(dom_tok == "*"),
        dow_was_star=(dow_tok == "*"),
    )


def matches(expr: CronExpr, when: datetime) -> bool:
    """Return True iff ``when`` (UTC) is a firing moment.

    Vixie-cron OR rule: when both dom AND dow are restricted (neither
    was ``*`` in the source), a fire occurs if either matches.
    """
    if when.tzinfo is None or when.utcoffset() != timedelta(0):
        raise ValueError(
            "cron.matches requires a UTC tz-aware datetime "
            f"(got tzinfo={when.tzinfo!r})"
        )
    if when.minute not in expr.minutes:
        return False
    if when.hour not in expr.hours:
        return False
    if when.month not in expr.months:
        return False
    # Python: Mon=0..Sun=6; cron: Sun=0..Sat=6. Convert.
    cron_dow = (when.weekday() + 1) % 7
    dom_match = when.day in expr.doms
    dow_match = cron_dow in expr.dows
    if expr.dom_was_star and expr.dow_was_star:
        return True  # already gated on m/h/mo
    if expr.dom_was_star:
        return dow_match
    if expr.dow_was_star:
        return dom_match
    return dom_match or dow_match


def next_fire_after(expr: CronExpr, after: datetime) -> datetime:
    """Return the smallest UTC ``datetime`` strictly greater than
    ``after`` that satisfies ``expr``.

    Raises :class:`CronSyntaxError` when no fire occurs inside the
    next :data:`_NEXT_FIRE_MAX_DAYS` (catches impossible expressions
    like ``0 0 31 2 *`` — Feb 31 never exists).
    """
    if after.tzinfo is None or after.utcoffset() != timedelta(0):
        raise ValueError(
            "cron.next_fire_after requires UTC tz-aware datetime "
            f"(got tzinfo={after.tzinfo!r})"
        )
    # Round down to minute, then advance one minute (strictly greater).
    candidate = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    horizon = after + timedelta(days=_NEXT_FIRE_MAX_DAYS)
    while candidate <= horizon:
        if matches(expr, candidate):
            return candidate
        candidate += timedelta(minutes=1)
    raise CronSyntaxError(
        f"cron {expr.raw!r}: no fire in next {_NEXT_FIRE_MAX_DAYS} days "
        f"(impossible expression?)"
    )


def utc_now() -> datetime:
    """Wall-clock UTC; module-private indirection so tests can stub."""
    return datetime.now(timezone.utc)


__all__ = [
    "CronExpr",
    "CronSyntaxError",
    "matches",
    "next_fire_after",
    "parse_cron",
    "utc_now",
]
