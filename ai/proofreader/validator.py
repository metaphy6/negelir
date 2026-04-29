"""
Negelir — Data proofreader / quality validator.
Per roadmap §5.1 proofreading logic:
1. Range checks
2. Consistency checks
3. Historical plausibility
4. Cross-source validation
5. Temporal consistency
6. Quarantine suspect data
"""

from dataclasses import dataclass, field
import json
import os
import sys
from common.logger import get_logger

log = get_logger("proofreader")


@dataclass
class ValidationResult:
    is_valid: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    quarantined: list[dict] = field(default_factory=list)


# ── Range constraints (per roadmap §5.1) ────────────────
RANGES = {
    "home_score":   (0, 15),
    "away_score":   (0, 15),
    "possession":   (0, 100),
    "shots_on":     (0, 40),
    "shots_off":    (0, 40),
    "corners":      (0, 25),
    "fouls":        (0, 40),
    "yellow_cards": (0, 10),
    "red_cards":    (0, 5),
    # Per-team card & foul ranges (v0.2)
    "home_yellows": (0, 10),
    "away_yellows": (0, 10),
    "home_reds":    (0, 5),
    "away_reds":    (0, 5),
    "home_fouls":   (0, 40),
    "away_fouls":   (0, 40),
    # Half-time scores
    "ht_home_score": (0, 10),
    "ht_away_score": (0, 10),
}


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

    def _range_checks(self, match: dict, result: ValidationResult):
        """Per roadmap: goals 0-15, possession 0-100, cards 0-20, etc."""
        stats = match.get("stats", {})
        all_fields = {**match, **stats}

        for field_name, (lo, hi) in RANGES.items():
            val = all_fields.get(field_name)
            if val is not None:
                try:
                    val = float(val)
                    if val < lo or val > hi:
                        result.errors.append(
                            f"Out of range: {field_name}={val} (expected: {lo}-{hi})"
                        )
                except (ValueError, TypeError):
                    result.warnings.append(f"Invalid value type: {field_name}={val}")

    def _consistency_checks(self, match: dict, result: ValidationResult):
        """Per roadmap: home+away possession ≈ 100, etc."""
        stats = match.get("stats", {})

        # Possession check
        home_poss = stats.get("home_possession")
        away_poss = stats.get("away_possession")
        if home_poss is not None and away_poss is not None:
            total = float(home_poss) + float(away_poss)
            if abs(total - 100) > 5:
                result.warnings.append(
                    f"Possession inconsistent: {home_poss}+{away_poss}={total} (≈100 expected)"
                )

        # Score consistency. Defensive parsing — bad upstream values must
        # turn into a quarantine warning, never a hard exception that
        # aborts the whole batch (see validate_batch contract).
        def _coerce_int(label: str, raw):
            try:
                return int(raw)
            except (TypeError, ValueError):
                result.warnings.append(f"Invalid value type: {label}={raw}")
                return None

        ht_home = match.get("ht_home_score")
        ft_home = match.get("home_score")
        if ht_home is not None and ft_home is not None:
            ht_h = _coerce_int("ht_home_score", ht_home)
            ft_h = _coerce_int("home_score", ft_home)
            if ht_h is not None and ft_h is not None and ht_h > ft_h:
                result.errors.append(
                    f"HT score cannot exceed FT: HT={ht_home} > FT={ft_home}"
                )

        ht_away = match.get("ht_away_score")
        ft_away = match.get("away_score")
        if ht_away is not None and ft_away is not None:
            ht_a = _coerce_int("ht_away_score", ht_away)
            ft_a = _coerce_int("away_score", ft_away)
            if ht_a is not None and ft_a is not None and ht_a > ft_a:
                result.errors.append(
                    f"HT score cannot exceed FT: HT={ht_away} > FT={ft_away}"
                )

        # Card vs foul plausibility: yellows should not exceed fouls
        home_yellows = stats.get("home_yellows")
        home_fouls = stats.get("home_fouls")
        if home_yellows is not None and home_fouls is not None:
            hy = _coerce_int("home_yellows", home_yellows)
            hf = _coerce_int("home_fouls", home_fouls)
            if hy is not None and hf is not None and hy > hf:
                result.warnings.append(
                    f"More yellow cards ({home_yellows}) than fouls ({home_fouls}) for home team"
                )

    def _plausibility_checks(self, match: dict, result: ValidationResult):
        """Per roadmap: >3σ deviation from historical = suspect."""
        home_score = match.get("home_score")
        away_score = match.get("away_score")

        if home_score is not None and away_score is not None:
            try:
                hs = int(home_score)
                as_ = int(away_score)
            except (TypeError, ValueError):
                result.warnings.append(
                    f"Invalid value type: score={home_score}-{away_score}"
                )
                return
            total = hs + as_
            # A match with 10+ total goals is extremely rare
            if total >= 10:
                result.warnings.append(
                    f"Unusually high total goals: {total} (statistically rare)"
                )
            # A single team scoring 8+ is implausible
            if hs >= 8 or as_ >= 8:
                result.errors.append(
                    f"Implausible score: {home_score}-{away_score}"
                )


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

    from common.config import cfg

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
