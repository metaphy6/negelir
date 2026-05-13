"""Boundary tests for ``xops.backup.recipients`` (ROADMAP §8.3
two-class DR/verify recipient classification)."""

from __future__ import annotations

import pytest

from xops.backup.recipients import (
    RecipientsClassification,
    RecipientsClassifyError,
    parse_recipients_file,
    parse_recipients_text,
)


# ── happy paths ─────────────────────────────────────────────────────


def test_two_dr_one_verify_parses_with_default_min() -> None:
    text = (
        "# keys.v3.recipients.txt — Q2 rotation\n"
        "[dr]\n"
        "age1dr_alice\n"
        "age1dr_bob\n"
        "\n"
        "[verify]\n"
        "age1verify_per_dump\n"
    )
    result = parse_recipients_text(text, min_dr_recipients=2)
    assert isinstance(result, RecipientsClassification)
    assert result.dr == ("age1dr_alice", "age1dr_bob")
    assert result.verify == ("age1verify_per_dump",)
    assert result.all_recipients == (
        "age1dr_alice", "age1dr_bob", "age1verify_per_dump",
    )


def test_dr_only_is_valid_when_verify_optional() -> None:
    """Mock / compose stacks may run without a verify-class
    recipient; the parser allows it (the agent boot validator
    enforces prod's ``verify_mode=full`` requirement, not us)."""
    text = "[dr]\nage1a\nage1b\n"
    result = parse_recipients_text(text, min_dr_recipients=2)
    assert result.dr == ("age1a", "age1b")
    assert result.verify == ()


def test_min_dr_one_allows_single_dr_recipient() -> None:
    """Mock override (``min_dr_recipients=1``) lets developers
    test the encryption surface end-to-end with a single key."""
    result = parse_recipients_text("[dr]\nage1solo\n", min_dr_recipients=1)
    assert result.dr == ("age1solo",)


def test_blank_lines_and_comments_are_ignored() -> None:
    text = (
        "\n"
        "# leading comment\n"
        "[dr]\n"
        "    \n"
        "  # indented comment within section\n"
        "age1a\n"
        "age1b\n"
    )
    result = parse_recipients_text(text, min_dr_recipients=2)
    assert result.dr == ("age1a", "age1b")


# ── boundary refusals (the binding rejection table) ─────────────────


def test_recipient_before_any_section_is_unclassified() -> None:
    """Bare recipient line without a [dr]/[verify] header — the
    whole point of the format is that EVERY recipient is named
    into exactly one class."""
    with pytest.raises(RecipientsClassifyError, match="unclassified_recipient"):
        parse_recipients_text(
            "age1stray\n[dr]\nage1a\nage1b\n",
            min_dr_recipients=2,
        )


def test_unknown_section_header_refused() -> None:
    with pytest.raises(RecipientsClassifyError, match="unknown_section"):
        parse_recipients_text(
            "[backup]\nage1a\n",
            min_dr_recipients=1,
        )


def test_duplicate_recipient_within_section_refused() -> None:
    with pytest.raises(RecipientsClassifyError, match="duplicate_recipient"):
        parse_recipients_text(
            "[dr]\nage1a\nage1a\n",
            min_dr_recipients=1,
        )


def test_duplicate_recipient_across_sections_refused() -> None:
    """A key that appears in BOTH classes is ambiguous —
    refusing prevents accidental verify-key promotion to DR."""
    with pytest.raises(RecipientsClassifyError, match="duplicate_recipient"):
        parse_recipients_text(
            "[dr]\nage1a\nage1b\n[verify]\nage1a\n",
            min_dr_recipients=2,
        )


def test_dr_count_below_min_refused() -> None:
    """Single DR recipient with default ``min_dr_recipients=2``
    is exactly the single-point-of-failure the binding forbids."""
    with pytest.raises(RecipientsClassifyError, match="dr_count_below_min"):
        parse_recipients_text(
            "[dr]\nage1solo\n[verify]\nage1v\n",
            min_dr_recipients=2,
        )


def test_no_dr_recipients_refused_even_with_verify() -> None:
    """Verify-class without DR-class is meaningless — no DR path
    means no recovery."""
    with pytest.raises(RecipientsClassifyError, match="dr_count_below_min"):
        parse_recipients_text("[verify]\nage1v\n", min_dr_recipients=1)


def test_verify_count_above_one_refused() -> None:
    """Per the binding, the verify class has EXACTLY one recipient
    (per-dump ephemeral key); >1 is a misconfig."""
    with pytest.raises(RecipientsClassifyError, match="verify_count_above_one"):
        parse_recipients_text(
            "[dr]\nage1a\nage1b\n[verify]\nage1v1\nage1v2\n",
            min_dr_recipients=2,
        )


def test_completely_empty_file_refused() -> None:
    with pytest.raises(RecipientsClassifyError, match="empty_classification"):
        parse_recipients_text("# only comments\n\n", min_dr_recipients=1)


def test_min_dr_recipients_must_be_at_least_one() -> None:
    with pytest.raises(RecipientsClassifyError, match="min_dr_recipients_invalid"):
        parse_recipients_text("[dr]\nage1a\n", min_dr_recipients=0)


# ── file-path surface ───────────────────────────────────────────────


def test_parse_recipients_file_round_trip(tmp_path) -> None:
    p = tmp_path / "keys.v1.recipients.txt"
    p.write_text("[dr]\nage1a\nage1b\n[verify]\nage1v\n", encoding="utf-8")
    result = parse_recipients_file(p, min_dr_recipients=2)
    assert result.dr == ("age1a", "age1b")
    assert result.verify == ("age1v",)


def test_parse_recipients_file_quotes_path_in_error(tmp_path) -> None:
    """Error messages MUST name the offending file so the operator
    can grep their key directory."""
    p = tmp_path / "keys.v9.recipients.txt"
    p.write_text("[dr]\nage1a\n", encoding="utf-8")
    with pytest.raises(RecipientsClassifyError) as excinfo:
        parse_recipients_file(p, min_dr_recipients=2)
    assert str(p) in str(excinfo.value)
