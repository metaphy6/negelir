"""Phase 8 §8.4 — two-tier cost cap for the source-watcher summarizer.

Implements the unticked ROADMAP §8.4 bullet:

> **Cost cap (two-tier).** Per-call ceiling
> ``cfg.source_watcher_summarizer_max_tokens_per_call`` (default
> 4096) AND per-day ledger
> ``cfg.source_watcher_summarizer_max_tokens_per_day`` (default
> 50 000). Either overflow → fall back to deterministic
> plan-derived string. Day boundaries are UTC midnight; counter
> persisted at ``data/maint/summarizer_ledger.json`` (mode 0600,
> atomic write via temp+rename) so restarts within a day do not
> reset the budget.

The ledger is a tiny stdlib-only artifact with two responsibilities:

1. Track ``total_tokens_today`` keyed on ``utc_date`` (resets at
   00:00 UTC by *replacing* the day key — never persisting yesterday).
2. Decide whether a prospective call is admissible, given the
   per-call ceiling and the running day total.

Callers that opt-in:

* The summarizer wrapper at :func:`summarize_with_budget` calls
  :meth:`SummarizerLedger.try_admit(plan_max_tokens)` and only
  invokes the LLM when the return is :data:`AdmitResult.ADMIT`.
* Tests can use :class:`InMemorySummarizerLedger` (no disk I/O).

The ledger only decides admission. Callers map
:class:`AdmitResult` to narration fallback and any operator alerting
policy they need.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional


__all__ = [
    "AdmitResult",
    "SummarizerLedger",
    "InMemorySummarizerLedger",
    "FileSummarizerLedger",
]


class AdmitResult(str, Enum):
    """Outcome of :meth:`SummarizerLedger.try_admit`.

    Ordered by the operator-visible severity:

    * :data:`ADMIT` — call may proceed.
    * :data:`REFUSED_PER_CALL` — single call asks for more than the
      per-call ceiling. Caller must fall back to deterministic
      narration AND emit a ``summarizer_cost_capped, scope=per_call``
      sec-alert (deferred per module docstring).
    * :data:`REFUSED_PER_DAY` — admitting this call would push the
      running day total past the per-day cap. Same fallback +
      ``scope=per_day`` alert.
    """

    ADMIT = "admit"
    REFUSED_PER_CALL = "refused_per_call"
    REFUSED_PER_DAY = "refused_per_day"


def _utc_today_iso() -> str:
    """Return today's UTC date as ``YYYY-MM-DD``."""

    return datetime.now(timezone.utc).date().isoformat()


@dataclass
class SummarizerLedger:
    """In-memory cap implementation. Subclassed for disk-backed flavor.

    Day boundaries are UTC midnight; on the first ``try_admit`` /
    ``record_usage`` of a new UTC day the prior day's counter is
    replaced (never persisted alongside).
    """

    max_tokens_per_call: int = 4096
    max_tokens_per_day: int = 50_000

    # Mutable state.
    _utc_date: str = ""
    _tokens_today: int = 0

    # ── Subclass hooks ────────────────────────────────────────────
    def _load(self) -> None:  # noqa: D401 - hook
        """Subclass hook — load persisted state into ``_utc_date`` /
        ``_tokens_today``. Default no-op (in-memory)."""

    def _persist(self) -> None:
        """Subclass hook — persist current state. Default no-op."""

    # ── Public API ────────────────────────────────────────────────
    def __post_init__(self) -> None:
        if self.max_tokens_per_call < 1:
            raise ValueError(
                f"max_tokens_per_call must be ≥1, got {self.max_tokens_per_call}"
            )
        if self.max_tokens_per_day < self.max_tokens_per_call:
            raise ValueError(
                "max_tokens_per_day must be ≥ max_tokens_per_call "
                f"(got per_day={self.max_tokens_per_day} < "
                f"per_call={self.max_tokens_per_call})"
            )
        self._load()

    def _roll_day_if_needed(self) -> None:
        today = _utc_today_iso()
        if today != self._utc_date:
            self._utc_date = today
            self._tokens_today = 0

    def tokens_today(self) -> int:
        """Return the running day total (after the rollover check)."""

        self._roll_day_if_needed()
        return self._tokens_today

    def try_admit(self, requested_tokens: int) -> AdmitResult:
        """Decide whether a call asking for ``requested_tokens`` may
        proceed. Does NOT increment the ledger — the caller must
        invoke :meth:`record_usage` after the LLM returns with the
        ACTUAL tokens consumed (which may be ≤ requested).
        """

        if requested_tokens < 0:
            raise ValueError(
                f"requested_tokens must be ≥0, got {requested_tokens}"
            )
        if requested_tokens > self.max_tokens_per_call:
            return AdmitResult.REFUSED_PER_CALL
        self._roll_day_if_needed()
        if self._tokens_today + requested_tokens > self.max_tokens_per_day:
            return AdmitResult.REFUSED_PER_DAY
        return AdmitResult.ADMIT

    def record_usage(self, tokens_used: int) -> None:
        """Increment the day counter by the actually-consumed tokens.

        Call AFTER the LLM returns. Idempotency is the caller's
        responsibility (the ledger does not dedup — two record calls
        for one logical request would double-count).
        """

        if tokens_used < 0:
            raise ValueError(f"tokens_used must be ≥0, got {tokens_used}")
        self._roll_day_if_needed()
        self._tokens_today += tokens_used
        self._persist()

    def reset_for_test(self) -> None:
        """Test-only: zero the day counter without touching disk."""

        self._utc_date = _utc_today_iso()
        self._tokens_today = 0


@dataclass
class InMemorySummarizerLedger(SummarizerLedger):
    """Test-friendly subclass — no disk I/O. Same surface."""


@dataclass
class FileSummarizerLedger(SummarizerLedger):
    """Disk-backed flavor.

    Persists ``{utc_date, tokens_today}`` to ``ledger_path`` on every
    successful :meth:`record_usage`. Atomic via temp+rename. File
    mode 0600 (operator-readable, never world-readable). Parent
    directory is created with mode 0700 if missing.

    A corrupt ledger (unreadable JSON, wrong type) is treated as a
    fresh start — the audit trail of the prior day is lost, but the
    cap remains effective for the current day. The caller can
    detect this condition via :meth:`load_warning` (one-shot).
    """

    ledger_path: Optional[str] = None
    _load_warning: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.ledger_path:
            raise ValueError("FileSummarizerLedger requires ledger_path")
        super().__post_init__()

    def load_warning(self) -> Optional[str]:
        """Return the load-time warning (corrupt file etc.) once;
        subsequent calls return None. Lets callers emit a one-shot
        operator log without polluting future ticks."""

        warn = self._load_warning
        self._load_warning = None
        return warn

    def _load(self) -> None:
        path = Path(self.ledger_path)  # type: ignore[arg-type]
        if not path.exists():
            return
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
            day = str(data["utc_date"])
            tokens = int(data["tokens_today"])
            if day == _utc_today_iso() and tokens >= 0:
                self._utc_date = day
                self._tokens_today = tokens
        except (OSError, ValueError, KeyError, TypeError) as exc:
            # Corrupt or unreadable — fresh start, surface once.
            self._load_warning = (
                f"summarizer_ledger {self.ledger_path} unreadable: {exc!r};"
                " starting from zero for today (cap is still in effect)"
            )

    def _persist(self) -> None:
        path = Path(self.ledger_path)  # type: ignore[arg-type]
        parent = path.parent
        if not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(parent, 0o700)
            except OSError:
                pass  # Non-POSIX or permission-denied; not fatal.
        payload = json.dumps(
            {"utc_date": self._utc_date, "tokens_today": self._tokens_today},
            sort_keys=True,
        )
        # Atomic write: temp file in same dir + rename.
        fd, tmp = tempfile.mkstemp(
            prefix=".summarizer_ledger.", suffix=".json.tmp", dir=str(parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, path)
        except OSError:
            # Best-effort cleanup; the in-memory counter is still
            # truthful for this process lifetime.
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
