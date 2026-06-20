"""
Negelir — Data proofreader / quality validator.
Per roadmap §5.1 proofreading logic:
1. Range checks
2. Consistency checks
3. Historical plausibility
4. Cross-source validation
5. Temporal consistency
6. Quarantine suspect data

NOTE (Wave A.2, pre-Phase-6): The rule bodies for range/consistency/
plausibility now live in `ai/swarm/agents/proofreader/checks.py` as
pure functions, and this module re-exports them so there is a single
source of truth. The thin OO wrapper (`DataProofreader`,
`ValidationResult`, `_normalise_input_match`) is preserved verbatim
for the legacy callers in `ai/pipeline/runner.py`,
`ai/pipeline/training_pipeline.py`, and `ai/data_showcase.py`. The
full module + its three callers will be retired once Phase 6.3 lands
the swarm-side replacement (see `docs/reports/pre-phase6-roadmap.md`
§3 Wave B + §6.5 locked decision).
"""

from dataclasses import dataclass, field
import json
import os
import sys
from ai.common.logger import get_logger
from ai.swarm.agents.proofreader.checks import (
    RANGES,
    consistency_check,
    plausibility_check,
    range_check,
)

log = get_logger("proofreader")


@dataclass
class ValidationResult:
    is_valid: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    quarantined: list[dict] = field(default_factory=list)


# `RANGES` re-exported above — preserved at module scope so the
# `from proofreader.validator import RANGES` import path used by
# `data_showcase.py` and `tests/test_unit.py` keeps working without
# changes (Wave A.2 contract).


class DataProofreader:
    """Validates match data quality before it reaches the AI model."""

    def validate_match(self, match: dict) -> ValidationResult:
        """Run all validation checks on a single match record."""
        result = ValidationResult(is_valid=True)

        self._range_checks(match, result)
        self._consistency_checks(match, result)
        self._plausibility_checks(match, result)

        if result.errors:
            result.is_valid = False
            log.warning(f"⚠️  Match validation failed: {len(result.errors)} errors")
            for err in result.errors:
                log.warning(f"   ❌ {err}")
        elif result.warnings:
            log.info(f"📋 Match validated ({len(result.warnings)} warnings)")
        else:
            log.debug("✅ Match validated, no issues")

        return result

    def validate_batch(self, matches: list[dict]) -> ValidationResult:
        """Validate a batch of match records."""
        batch_result = ValidationResult(is_valid=True)
        valid_count = 0
        quarantine_count = 0

        for match in matches:
            r = self.validate_match(match)
            if r.is_valid:
                valid_count += 1
            else:
                quarantine_count += 1
                batch_result.quarantined.append(match)
            batch_result.warnings.extend(r.warnings)
            batch_result.errors.extend(r.errors)

        if quarantine_count > 0:
            batch_result.is_valid = (quarantine_count / len(matches)) < 0.3
            log.info(
                f"📊 Batch validation: {valid_count} valid, "
                f"{quarantine_count} quarantined ({len(matches)} total)"
            )
        else:
            log.info(f"✅ Batch validation: {valid_count}/{len(matches)} matches valid")

        return batch_result

    # The three check methods now delegate to the canonical swarm-side
    # pure functions in `ai/swarm/agents/proofreader/checks.py`. The
    # ValidationResult contract (in-place mutation of errors/warnings)
    # is preserved so legacy callers and unit tests behave identically.

    def _range_checks(self, match: dict, result: ValidationResult):
        errors, warnings = range_check(match)
        result.errors.extend(errors)
        result.warnings.extend(warnings)

    def _consistency_checks(self, match: dict, result: ValidationResult):
        errors, warnings = consistency_check(match)
        result.errors.extend(errors)
        result.warnings.extend(warnings)

    def _plausibility_checks(self, match: dict, result: ValidationResult):
        errors, warnings = plausibility_check(match)
        result.errors.extend(errors)
        result.warnings.extend(warnings)


def _normalise_input_match(raw_match: dict) -> dict | None:
    """Normalise a raw match record into validator-compatible fields."""
    if "home_score" in raw_match and "away_score" in raw_match:
        return raw_match

    score = raw_match.get("score", {}) if isinstance(raw_match, dict) else {}
    ft = score.get("ft") if isinstance(score, dict) else None
    ht = score.get("ht") if isinstance(score, dict) else None

    if not isinstance(ft, (list, tuple)) or len(ft) != 2:
        return None

    ht_home = 0
    ht_away = 0
    if isinstance(ht, (list, tuple)) and len(ht) == 2:
        ht_home = ht[0]
        ht_away = ht[1]

    stats = raw_match.get("stats", {}) if isinstance(raw_match, dict) else {}
    if not isinstance(stats, dict):
        stats = {}

    return {
        "home_team": raw_match.get("team1") or raw_match.get("home") or "",
        "away_team": raw_match.get("team2") or raw_match.get("away") or "",
        "home_score": ft[0],
        "away_score": ft[1],
        "ht_home_score": ht_home,
        "ht_away_score": ht_away,
        "stats": stats,
    }


def main() -> int:
    """CLI entry point for validating scraped match datasets."""
    import argparse

    from ai.common.config import cfg

    parser = argparse.ArgumentParser(description="Validate real match dataset JSON")
    parser.add_argument("--input", required=True, help="Path to JSON dataset (expects `matches` array)")
    parser.add_argument(
        "--min-matches",
        type=int,
        default=cfg.training_min_matches,
        help=f"Minimum required match count (default: {cfg.training_min_matches})",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"ERROR: Input file not found: {args.input}", file=sys.stderr)
        return 2

    with open(args.input, "r", encoding="utf-8") as f:
        payload = json.load(f)

    if isinstance(payload, dict):
        raw_matches = payload.get("matches", [])
    elif isinstance(payload, list):
        raw_matches = payload
    else:
        print("ERROR: Unsupported JSON structure (expected dict or list)", file=sys.stderr)
        return 2

    if len(raw_matches) < args.min_matches:
        print(
            f"ERROR: Insufficient matches in {args.input}: "
            f"found={len(raw_matches)}, required>={args.min_matches}",
            file=sys.stderr,
        )
        return 1

    normalised = []
    skipped = 0
    for m in raw_matches:
        nm = _normalise_input_match(m)
        if nm is None:
            skipped += 1
            continue
        normalised.append(nm)

    if len(normalised) < args.min_matches:
        print(
            f"ERROR: Too many malformed records in {args.input}: "
            f"usable={len(normalised)}, skipped={skipped}, required>={args.min_matches}",
            file=sys.stderr,
        )
        return 1

    proofreader = DataProofreader()
    result = proofreader.validate_batch(normalised)
    quarantined = len(result.quarantined)
    total = len(normalised)
    quarantine_rate = (quarantined / total) if total else 0.0

    print(
        "VALIDATION SUMMARY: "
        f"total={total}, quarantined={quarantined}, "
        f"quarantine_rate={quarantine_rate:.1%}, warnings={len(result.warnings)}, errors={len(result.errors)}"
    )

    if not result.is_valid:
        print("ERROR: Validation failed (quarantine/error threshold exceeded)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
