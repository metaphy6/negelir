from __future__ import annotations

import datetime as _dt
import math
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any

_LEAP_SECOND_RE = re.compile(r":60(?:[.,]\d+)?(?:Z|[+\-]|$)")

_MONTH_NAMES_TR: list[str] = [
    "", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
]

_CURRENCY_SUFFIX: dict[str, str] = {
    "TRY": " TL",
    "EUR": " €",
}


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError("bool is not a valid numeric value")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        if math.isinf(value) or math.isnan(value):
            raise ValueError("inf/nan is not a valid numeric value")
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value)
        except InvalidOperation as exc:
            raise ValueError(f"invalid numeric string: {value!r}") from exc
    raise TypeError(f"unsupported numeric type: {type(value).__name__}")


def _format_int_with_thousands(integer: str) -> str:
    if integer == "":
        return "0"
    sign = ""
    if integer.startswith("-"):
        sign = "-"
        integer = integer[1:]
    parts: list[str] = []
    while integer:
        parts.insert(0, integer[-3:])
        integer = integer[:-3]
    return sign + ".".join(parts)


def tr_format_number(value: Any, decimals: int = 0) -> str:
    """Format a number for Turkish presentation.

    Uses '.' as thousands separator and ',' as decimal separator.
    Rounds with bankers rounding by default.
    """
    if decimals < 0:
        raise ValueError("decimals must be non-negative")
    dec = _to_decimal(value)
    if dec.is_nan() or dec.is_infinite():
        raise ValueError("inf/nan is not a valid numeric value")

    quant = Decimal(1).scaleb(-decimals)
    rounded = dec.quantize(quant, rounding=ROUND_HALF_EVEN)
    if rounded == 0:
        rounded = abs(rounded)

    text = format(rounded, "f")
    if "." in text:
        integer, fraction = text.split(".")
    else:
        integer, fraction = text, ""
    integer = _format_int_with_thousands(integer)
    if decimals == 0:
        return integer
    fraction = fraction.ljust(decimals, "0")
    return f"{integer},{fraction}"


def tr_format_money(value: Any, currency: str = "TRY") -> str:
    formatted = tr_format_number(value, decimals=2)
    suffix = _CURRENCY_SUFFIX.get(currency.upper(), f" {currency}")
    return f"{formatted}{suffix}"


def _load_zoneinfo(tz: str) -> ZoneInfo:
    from ai.common.config import cfg

    if cfg.nlp_zoneinfo_dir:
        zonefile = Path(cfg.nlp_zoneinfo_dir) / tz
        if zonefile.exists():
            with zonefile.open("rb") as fh:
                return ZoneInfo.from_file(fh)
        raise ValueError(
            f"nlp_zoneinfo_dir={cfg.nlp_zoneinfo_dir!r} does not contain zoneinfo file {tz!r}"
        )
    return ZoneInfo(tz)


def tr_format_clock(dt: "str | _dt.datetime | None", tz: str | None = None) -> str:
    if tz is None:
        from ai.common.config import cfg

        tz = cfg.nlp_render_timezone
    if dt is None:
        return "Bilinmiyor"
    if isinstance(dt, str):
        try:
            dt = _dt.datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError as exc:
            if _LEAP_SECOND_RE.search(dt):
                raise ValueError("leap second timestamps are not supported") from exc
            return dt
    if isinstance(dt, _dt.date) and not isinstance(dt, _dt.datetime):
        return dt.strftime("%H:%M")
    if not isinstance(dt, _dt.datetime):
        return str(dt)
    if dt.tzinfo is None:
        raise ValueError("naive datetime is not allowed; datetime must include timezone information")
    target = dt.astimezone(_load_zoneinfo(tz))
    return f"{target.hour:02d}:{target.minute:02d}"


def tr_format_date(d: "str | _dt.date | _dt.datetime | None") -> str:
    if d is None:
        return ""
    if isinstance(d, str):
        try:
            d = _dt.date.fromisoformat(d)
        except ValueError:
            try:
                d = _dt.datetime.fromisoformat(d.replace("Z", "+00:00")).date()
            except ValueError:
                return d
    if isinstance(d, _dt.datetime):
        d = d.date()
    if not isinstance(d, _dt.date):
        return str(d)
    month_name = _MONTH_NAMES_TR[d.month]
    return f"{d.day} {month_name} {d.year}"


def tr_format_date_short(d: "str | _dt.date | _dt.datetime | None") -> str:
    if d is None:
        return ""
    if isinstance(d, str):
        try:
            d = _dt.date.fromisoformat(d)
        except ValueError:
            try:
                d = _dt.datetime.fromisoformat(d.replace("Z", "+00:00")).date()
            except ValueError:
                return d
    if isinstance(d, _dt.datetime):
        d = d.date()
    if not isinstance(d, _dt.date):
        return str(d)
    return f"{d.day:02d}.{d.month:02d}.{d.year}"


def tr_format_score(home: Any, away: Any) -> str:
    return f"{int(home)}-{int(away)}"
