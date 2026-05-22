"""opsctl_audit.csv hash-chain HMAC verifier (Phase 8 §8.15.7).

Public surface:

    :class:`ChainVerifyResult` — result of one verification pass.
    :func:`verify_audit_chain`  — walk the audit CSV (+ rotated files)
        and recompute every row's HMAC to detect tampering.

The verifier understands the rotation scheme produced by
:func:`xops.opsctl._audit._rotate_audit_file`:

    opsctl_audit.csv        (active — newest rows)
    opsctl_audit.csv.1      (last rotation — older rows)
    opsctl_audit.csv.2      (second-to-last — oldest rows)
    …

Files are walked oldest-first (highest N first) so the chain is
verified in chronological order.  A row with an empty ``row_hmac``
is treated as unprotected (written before §8.15.7 key was configured)
and silently skipped — it does NOT break the chain so existing
deployments that upgrade incrementally still verify cleanly.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ._audit import (
    GENESIS_PREV_HMAC,
    _IDX_PREV_HMAC,
    _IDX_ROW_HMAC,
    AUDIT_HEADER,
    compute_row_hmac,
    AuditRow,
)


@dataclass
class ChainVerifyResult:
    """Result of :func:`verify_audit_chain`.

    When ``ok`` is *True* the chain is intact across all inspected
    files.  When *False*, ``first_break_row`` (1-based across all
    walked files) and ``break_reason`` explain the first violation.
    """
    ok: bool
    rows_checked: int
    first_break_row: Optional[int]   # 1-based global row number; None iff ok
    break_reason: Optional[str]      # human-readable; None iff ok
    file_path: str                   # path of the active audit CSV that was verified


def verify_audit_chain(
    audit_path: str,
    key: bytes,
    *,
    include_rotated: bool = True,
) -> ChainVerifyResult:
    """Verify the HMAC hash chain of the opsctl audit CSV.

    Walks the active file and (optionally) all rotated files in
    chronological order.  For each row:

    1. Skip rows with empty ``row_hmac`` (pre-§8.15.7, unprotected).
    2. Assert ``row["prev_hmac"] == running_prev_hmac``.
    3. Recompute ``row_hmac`` from the signed-message formula and assert
       it matches ``row["row_hmac"]``.

    Returns a :class:`ChainVerifyResult` with ``ok=True`` when all
    protected rows pass, or ``ok=False`` with the first failing row.
    """
    active_path = Path(audit_path)

    # Build the ordered list of files to walk: oldest rotated file first.
    files: list[Path] = []
    if include_rotated:
        n = 1
        while True:
            rotated = active_path.parent / f"{active_path.name}.{n}"
            if not rotated.exists():
                break
            files.append(rotated)
            n += 1
        files.reverse()  # now: highest-N (oldest) → lowest-N → active

    files.append(active_path)

    running_prev = GENESIS_PREV_HMAC
    global_row = 0  # 1-based counter across all files (data rows only)

    for file_path in files:
        if not file_path.exists():
            continue
        try:
            with open(file_path, newline="", encoding="utf-8") as fh:
                reader = csv.reader(fh)
                first_line = True
                for csv_row in reader:
                    # Skip the header row (first row of each file).
                    if first_line:
                        first_line = False
                        if csv_row == list(AUDIT_HEADER):
                            continue
                        # If first line is not the header the file is
                        # either corrupt or a very old format — treat
                        # the row as data but flag it.

                    # Guard against truncated rows.
                    if len(csv_row) <= _IDX_ROW_HMAC:
                        global_row += 1
                        return ChainVerifyResult(
                            ok=False,
                            rows_checked=global_row,
                            first_break_row=global_row,
                            break_reason=(
                                f"row has only {len(csv_row)} columns "
                                f"(expected ≥{_IDX_ROW_HMAC + 1})"
                            ),
                            file_path=audit_path,
                        )

                    row_hmac_val  = csv_row[_IDX_ROW_HMAC].strip()
                    prev_hmac_val = csv_row[_IDX_PREV_HMAC].strip()

                    # Unprotected row — skip, do NOT advance running_prev.
                    if not row_hmac_val:
                        global_row += 1
                        continue

                    global_row += 1

                    # Check prev_hmac continuity.
                    if prev_hmac_val != running_prev:
                        return ChainVerifyResult(
                            ok=False,
                            rows_checked=global_row,
                            first_break_row=global_row,
                            break_reason=(
                                f"prev_hmac mismatch: expected "
                                f"{running_prev!r}, got {prev_hmac_val!r}"
                            ),
                            file_path=audit_path,
                        )

                    # Reconstruct the AuditRow for HMAC computation.
                    # We only need the fields in the signed message;
                    # use stable column indices from AUDIT_HEADER.
                    _idx = AUDIT_HEADER.index  # shorthand
                    reconstructed = AuditRow(
                        timestamp_utc=csv_row[_idx("timestamp_utc")] if len(csv_row) > _idx("timestamp_utc") else "",
                        host=csv_row[_idx("host")] if len(csv_row) > _idx("host") else "",
                        user=csv_row[_idx("user")] if len(csv_row) > _idx("user") else "",
                        op=csv_row[_idx("op")] if len(csv_row) > _idx("op") else "",
                        target=csv_row[_idx("target")] if len(csv_row) > _idx("target") else "",
                        request_id=csv_row[_idx("request_id")] if len(csv_row) > _idx("request_id") else "",
                        exit_code=0,
                        expected_acks=0,
                        received_acks=0,
                        note="",
                        prev_hmac=prev_hmac_val,
                        row_hmac=row_hmac_val,
                    )

                    expected_hmac = compute_row_hmac(key, running_prev, reconstructed)
                    if row_hmac_val != expected_hmac:
                        return ChainVerifyResult(
                            ok=False,
                            rows_checked=global_row,
                            first_break_row=global_row,
                            break_reason=(
                                f"row_hmac mismatch: expected "
                                f"{expected_hmac!r}, got {row_hmac_val!r}"
                            ),
                            file_path=audit_path,
                        )

                    running_prev = row_hmac_val

        except (OSError, csv.Error) as exc:
            global_row += 1
            return ChainVerifyResult(
                ok=False,
                rows_checked=global_row,
                first_break_row=global_row,
                break_reason=f"file read error: {exc}",
                file_path=audit_path,
            )

    return ChainVerifyResult(
        ok=True,
        rows_checked=global_row,
        first_break_row=None,
        break_reason=None,
        file_path=audit_path,
    )


__all__ = ["ChainVerifyResult", "verify_audit_chain"]
