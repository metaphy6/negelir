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

        # Score consistency
        ht_home = match.get("ht_home_score")
        ft_home = match.get("home_score")
        if ht_home is not None and ft_home is not None:
            if int(ht_home) > int(ft_home):
                result.errors.append(
                    f"HT score cannot exceed FT: HT={ht_home} > FT={ft_home}"
                )

    def _plausibility_checks(self, match: dict, result: ValidationResult):
        """Per roadmap: >3σ deviation from historical = suspect."""
        home_score = match.get("home_score")
        away_score = match.get("away_score")

        if home_score is not None and away_score is not None:
            total = int(home_score) + int(away_score)
            # A match with 10+ total goals is extremely rare
            if total >= 10:
                result.warnings.append(
                    f"Unusually high total goals: {total} (statistically rare)"
                )
            # A single team scoring 8+ is implausible
            if int(home_score) >= 8 or int(away_score) >= 8:
                result.errors.append(
                    f"Implausible score: {home_score}-{away_score}"
                )
