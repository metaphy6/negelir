"""ROADMAP §8.3 binding — `keys.vN.recipients.txt` two-class parser.

Each versioned recipients file under
``cfg.maint_backup_encryption_key_dir`` MUST classify every age
recipient into exactly one of ``{dr, verify}``:

* **DR-class** recipients (``[dr]`` section) — long-term off-cluster
  custodians used only for human-driven disaster recovery
  (``ops.restore --confirm-destructive``). At least
  ``cfg.maint_backup_min_dr_recipients`` (default 2) — single
  recipients are a single point of disaster-recovery failure.
* **Verify-class** recipient (``[verify]`` section) — at most one,
  per-dump ephemeral keypair whose private half lives in a single
  named in-cluster Secret (or an operator-protected 0600 file in
  compose mode). Optional in mock; mandatory in prod when
  ``cfg.maint_backup_verify_mode='full'`` (enforced by the agent
  bootstrap, not by this parser).

The parser is the boundary check the slice prose calls out
("Boundary test rejects a `recipients.txt` that does not classify
each recipient into exactly one of `{dr, verify}`"). It is
deliberately stdlib-only and free of any encryption I/O so it
can be reused by both the agent boot validator and the
``ops.backup-rotate-key`` runbook driver.

File grammar (line-oriented):

* Blank lines and lines starting with ``#`` are ignored.
* Section headers are ``[dr]`` or ``[verify]`` (case-sensitive)
  on a line of their own.
* All other non-empty lines are recipient strings (typically
  ``age1...``); they MUST appear under a section header. A
  recipient line outside any section is a hard error
  (``unclassified_recipient``) — the whole point of the format.
* Unknown section headers (anything other than ``[dr]`` /
  ``[verify]``) are a hard error (``unknown_section``).
* Duplicate recipients within or across sections are a hard
  error (``duplicate_recipient``).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


_VALID_SECTIONS = ("dr", "verify")


class RecipientsClassifyError(ValueError):
    """Raised when a ``keys.vN.recipients.txt`` violates the
    two-class contract. The error message is a single-line
    machine-greppable token followed by ``: <detail>`` so the agent
    boot validator can include it verbatim in
    ``BackupConfigError`` text without losing the surface code.

    Surface tokens (stable): ``unclassified_recipient``,
    ``unknown_section``, ``duplicate_recipient``,
    ``dr_count_below_min``, ``verify_count_above_one``,
    ``empty_classification``.
    """


@dataclass(frozen=True)
class RecipientsClassification:
    """Result of parsing one ``keys.vN.recipients.txt``."""

    dr: tuple[str, ...]
    verify: tuple[str, ...]

    @property
    def all_recipients(self) -> tuple[str, ...]:
        return self.dr + self.verify


def parse_recipients_text(
    text: str,
    *,
    min_dr_recipients: int,
    source: str = "<recipients>",
) -> RecipientsClassification:
    """Parse ``text`` and enforce the two-class contract.

    ``source`` is purely cosmetic — quoted into error messages so
    the operator knows which version file failed.
    """
    if min_dr_recipients < 1:
        # Defensive: refusing to enforce ``min_dr_recipients < 1``
        # is exactly the kind of misconfig the cfg validator catches
        # (bound 1..64), but the parser is also called by ad-hoc
        # operator tooling, so we belt-and-brace here.
        raise RecipientsClassifyError(
            f"min_dr_recipients_invalid: must be >= 1 (got {min_dr_recipients!r})"
        )

    section: str | None = None
    dr: list[str] = []
    verify: list[str] = []
    seen: set[str] = set()

    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            header = line[1:-1].strip()
            if header not in _VALID_SECTIONS:
                raise RecipientsClassifyError(
                    f"unknown_section: {source}:{lineno} "
                    f"section={header!r} (allowed: dr, verify)"
                )
            section = header
            continue
        if section is None:
            raise RecipientsClassifyError(
                f"unclassified_recipient: {source}:{lineno} "
                f"recipient={line!r} appears before any [dr]/[verify] header"
            )
        if line in seen:
            raise RecipientsClassifyError(
                f"duplicate_recipient: {source}:{lineno} recipient={line!r}"
            )
        seen.add(line)
        if section == "dr":
            dr.append(line)
        else:  # section == "verify"
            verify.append(line)

    if not dr and not verify:
        raise RecipientsClassifyError(
            f"empty_classification: {source} has no recipients in any section"
        )
    if len(dr) < min_dr_recipients:
        raise RecipientsClassifyError(
            f"dr_count_below_min: {source} has {len(dr)} DR recipient(s); "
            f"requires >= {min_dr_recipients} (cfg.maint_backup_min_dr_recipients)"
        )
    if len(verify) > 1:
        raise RecipientsClassifyError(
            f"verify_count_above_one: {source} has {len(verify)} verify "
            "recipient(s); exactly 0 or 1 is allowed"
        )

    return RecipientsClassification(dr=tuple(dr), verify=tuple(verify))


def parse_recipients_file(
    path: Path | str,
    *,
    min_dr_recipients: int,
) -> RecipientsClassification:
    """Read ``path`` and delegate to :func:`parse_recipients_text`."""
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    return parse_recipients_text(
        text, min_dr_recipients=min_dr_recipients, source=str(p)
    )


__all__ = (
    "RecipientsClassifyError",
    "RecipientsClassification",
    "parse_recipients_text",
    "parse_recipients_file",
)
