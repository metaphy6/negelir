"""Phase 8 §8.4 — summarizer cost-cap (two-tier ledger) tests.

Target: ai.swarm.source_watcher.summarizer_budget

ROADMAP §8.4 binding contract:
* Per-call ceiling rejects oversized requests up front.
* Per-day ledger blocks calls that would exceed today's budget.
* UTC midnight rolls the day counter (yesterday's tally is dropped).
* File-backed ledger atomic-writes (mode 0600), corrupt files
  degrade to fresh-start with a one-shot warning.
"""
from __future__ import annotations

import json
import os
import stat
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from swarm.source_watcher.summarizer_budget import (
    AdmitResult,
    FileSummarizerLedger,
    InMemorySummarizerLedger,
    SummarizerLedger,
)


def test_admit_under_per_call_under_per_day():
    led = InMemorySummarizerLedger(max_tokens_per_call=4096, max_tokens_per_day=50_000)
    assert led.try_admit(1000) is AdmitResult.ADMIT
    led.record_usage(1000)
    assert led.tokens_today() == 1000


def test_refuses_per_call_oversized_request():
    led = InMemorySummarizerLedger(max_tokens_per_call=4096, max_tokens_per_day=50_000)
    assert led.try_admit(5000) is AdmitResult.REFUSED_PER_CALL
    # No usage recorded — refusal does not leak into the day total.
    assert led.tokens_today() == 0


def test_refuses_per_day_when_running_total_would_overflow():
    led = InMemorySummarizerLedger(max_tokens_per_call=4096, max_tokens_per_day=10_000)
    led.record_usage(8_000)
    # 8000 + 3000 = 11000 > 10000 cap.
    assert led.try_admit(3000) is AdmitResult.REFUSED_PER_DAY
    # 8000 + 2000 = 10000 exactly → admit (cap is inclusive).
    assert led.try_admit(2000) is AdmitResult.ADMIT


def test_per_day_must_be_at_least_per_call():
    with pytest.raises(ValueError, match="max_tokens_per_day"):
        InMemorySummarizerLedger(max_tokens_per_call=4096, max_tokens_per_day=1024)


def test_negative_args_rejected():
    led = InMemorySummarizerLedger()
    with pytest.raises(ValueError):
        led.try_admit(-1)
    with pytest.raises(ValueError):
        led.record_usage(-1)


def test_utc_day_rollover_resets_counter():
    """Inject a frozen-clock subclass to fast-forward past UTC midnight."""

    class FrozenLedger(InMemorySummarizerLedger):
        forced_today: str = ""

        def _roll_day_if_needed(self):
            today = self.forced_today or super().__class__._roll_day_if_needed.__name__
            # Use the real implementation when forced_today empty.
            if not self.forced_today:
                return SummarizerLedger._roll_day_if_needed(self)
            if self.forced_today != self._utc_date:
                self._utc_date = self.forced_today
                self._tokens_today = 0

    led = FrozenLedger(max_tokens_per_call=10_000, max_tokens_per_day=10_000)
    led.forced_today = "2025-01-01"
    led.record_usage(5_000)
    assert led.tokens_today() == 5_000

    # Advance one day — counter drops to zero, prior day tally not
    # persisted alongside.
    led.forced_today = "2025-01-02"
    assert led.tokens_today() == 0
    assert led.try_admit(9_000) is AdmitResult.ADMIT


def test_file_ledger_persists_atomic_and_mode_0600(tmp_path: Path):
    ledger_path = tmp_path / "summarizer_ledger.json"
    led = FileSummarizerLedger(
        max_tokens_per_call=4096,
        max_tokens_per_day=50_000,
        ledger_path=str(ledger_path),
    )
    led.record_usage(1234)
    assert ledger_path.exists()

    # File mode is 0600.
    mode = ledger_path.stat().st_mode & 0o777
    if mode != 0:  # POSIX only — skip on filesystems without mode bits.
        assert mode == 0o600, f"expected 0600, got {oct(mode)}"

    # Persisted JSON shape is {utc_date, tokens_today}.
    data = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert set(data.keys()) == {"utc_date", "tokens_today"}
    assert data["tokens_today"] == 1234


def test_file_ledger_reload_within_same_day(tmp_path: Path):
    ledger_path = tmp_path / "ledger.json"
    led1 = FileSummarizerLedger(
        max_tokens_per_call=2000,
        max_tokens_per_day=10_000,
        ledger_path=str(ledger_path),
    )
    led1.record_usage(7_500)

    # Fresh process / fresh ledger pointing at same file.
    led2 = FileSummarizerLedger(
        max_tokens_per_call=2000,
        max_tokens_per_day=10_000,
        ledger_path=str(ledger_path),
    )
    assert led2.tokens_today() == 7_500
    # 7500 + 3000 = 10500 > 10000 → refused per-day.
    assert led2.try_admit(2_000) is AdmitResult.ADMIT
    led2.record_usage(2_000)
    assert led2.try_admit(1_000) is AdmitResult.REFUSED_PER_DAY


def test_file_ledger_corrupt_file_starts_fresh_with_warning(tmp_path: Path):
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text("{not valid json", encoding="utf-8")
    led = FileSummarizerLedger(
        max_tokens_per_call=4096,
        max_tokens_per_day=50_000,
        ledger_path=str(ledger_path),
    )
    assert led.tokens_today() == 0
    warn = led.load_warning()
    assert warn is not None and "unreadable" in warn
    # Warning is one-shot.
    assert led.load_warning() is None


def test_file_ledger_yesterdays_tally_not_carried_over(tmp_path: Path):
    ledger_path = tmp_path / "ledger.json"
    yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    ledger_path.write_text(
        json.dumps({"utc_date": yesterday, "tokens_today": 9999}),
        encoding="utf-8",
    )
    led = FileSummarizerLedger(
        max_tokens_per_call=4096,
        max_tokens_per_day=50_000,
        ledger_path=str(ledger_path),
    )
    # Stale day → ignored on load.
    assert led.tokens_today() == 0
