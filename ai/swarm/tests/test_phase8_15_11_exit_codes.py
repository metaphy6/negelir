"""Phase 8 §8.15.11 — exit-code boundary test.

Verifies:
  (a) ExitCode constants 5..9 are present and form a continuous range.
  (b) exit_code_to_label() in _classify.py returns non-None for each.
  (c) The code 9 label is "opsctl_key_revoked" per §8.15.4 doctrine.
"""
from __future__ import annotations

import pytest

from xops.opsctl._exit_codes import ExitCode
from xops.opsctl._classify import exit_code_to_label


# ── Helpers ────────────────────────────────────────────────────────────────

def _exit_code_int_set() -> set[int]:
    """All integer values defined in ExitCode."""
    return {member.value for member in ExitCode}


# ── Tests ──────────────────────────────────────────────────────────────────

def test_exit_codes_5_through_9_all_present() -> None:
    """Codes 5..9 must all be defined in ExitCode (continuous range)."""
    defined = _exit_code_int_set()
    missing = [c for c in range(5, 10) if c not in defined]
    assert not missing, (
        f"ExitCode is missing operator-recoverable codes: {missing}. "
        "Each new §8.15+ failure mode must register a distinct code."
    )


def test_exit_codes_5_through_9_continuous() -> None:
    """No gaps in the 5..9 range."""
    defined = _exit_code_int_set()
    assert set(range(5, 10)).issubset(defined), (
        "ExitCode range 5..9 is not contiguous. "
        "Runbooks assume a continuous range for easy enumeration."
    )


@pytest.mark.parametrize("code", list(range(5, 10)))
def test_exit_code_to_label_non_none(code: int) -> None:
    """exit_code_to_label() must return a non-None string for codes 5..9."""
    label = exit_code_to_label(code)
    assert label is not None, (
        f"exit_code_to_label({code}) returned None. "
        "_classify.py must map every code in 5..9 to a stable label string."
    )


@pytest.mark.parametrize("code", list(range(5, 10)))
def test_exit_code_label_is_string(code: int) -> None:
    """exit_code_to_label() must return a non-empty string."""
    label = exit_code_to_label(code)
    assert isinstance(label, str) and label, (
        f"exit_code_to_label({code}) returned {label!r}; expected a non-empty str."
    )


def test_exit_code_9_label_is_opsctl_key_revoked() -> None:
    """Code 9 must map to 'opsctl_key_revoked' per §8.15.4 doctrine."""
    assert exit_code_to_label(9) == "opsctl_key_revoked", (
        "ExitCode 9 must be labelled 'opsctl_key_revoked' — runbooks and "
        "the dead-man's-switch alerter key on this stable string."
    )


def test_exit_code_9_constant_value() -> None:
    """ExitCode.OPSCTL_KEY_REVOKED must equal 9."""
    assert ExitCode.OPSCTL_KEY_REVOKED == 9


def test_exit_code_to_label_returns_none_for_out_of_range() -> None:
    """exit_code_to_label() must return None for codes outside 5..9."""
    assert exit_code_to_label(0) is None
    assert exit_code_to_label(1) is None
    assert exit_code_to_label(10) is None
    assert exit_code_to_label(99) is None
