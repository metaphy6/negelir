"""NLP log redaction helpers.

This module provides a structural guard that redacts PII-like substrings from
log messages and exception args before records are emitted.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Iterable

from ai.common.config import cfg
from ai.common.security.patterns import PII_PATTERNS


def _redact_text(text: str) -> str:
    redacted = text
    for kind, pattern in PII_PATTERNS:
        token = f"[REDACTED_{kind.upper()}]"
        redacted = pattern.sub(token, redacted)
    max_unredacted_len = int(cfg.nlp_log_max_unredacted_str_len)
    if redacted == text and len(text) >= max_unredacted_len:
        sha8 = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8].upper()
        return f"[REDACTED:len={len(text)}:sha8={sha8}]"
    return redacted


def _sanitize_arg(value: object) -> object:
    if isinstance(value, str):
        return _redact_text(value)
    return value


class PIIScrubFilter(logging.Filter):
    """Redact PII in log record msg/args and exception args."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _redact_text(record.msg)

        if isinstance(record.args, tuple):
            record.args = tuple(_sanitize_arg(v) for v in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: _sanitize_arg(v) for k, v in record.args.items()}

        exc_info = record.exc_info
        if exc_info and len(exc_info) >= 2 and exc_info[1] is not None:
            exc = exc_info[1]
            if hasattr(exc, "args") and isinstance(exc.args, tuple):
                exc.args = tuple(_sanitize_arg(v) for v in exc.args)

        return True


def add_log_filter(logger: logging.Logger, filters: Iterable[logging.Filter] | None = None) -> None:
    """Attach scrub filters to *logger* once."""
    install_filters = tuple(filters) if filters is not None else (PIIScrubFilter(),)
    existing_types = {type(f) for f in logger.filters}
    for flt in install_filters:
        if type(flt) in existing_types:
            continue
        logger.addFilter(flt)
