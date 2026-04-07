"""
Negelir — Cross-source data validator.
Phase 4: Compares results from 2+ sources, accepts majority vote,
quarantines conflicts.
"""

from collections import Counter
from dataclasses import dataclass, field

from common.logger import get_logger

log = get_logger("proofreader.cross_validator")


@dataclass
class SourceResult:
    """A match result from a single source."""
    source: str
    match_id: int
    home_id: int
    away_id: int
    ft_home: int
    ft_away: int


@dataclass
class ValidatedResult:
    """A cross-validated match result."""
    match_id: int
    ft_home: int
    ft_away: int
    confidence: float
    sources_agreed: int
    sources_total: int


@dataclass
class CrossValidationReport:
    """Summary of cross-validation run."""
    validated: list[ValidatedResult] = field(default_factory=list)
    quarantined: list[dict] = field(default_factory=list)

    @property
    def validated_count(self) -> int:
        return len(self.validated)

    @property
    def quarantined_count(self) -> int:
        return len(self.quarantined)


class CrossValidator:
    """
    Compare results from 2+ sources. Accept majority vote.
    Quarantine conflicts where no majority exists.
    """

    def validate(self, results_by_source: dict[str, list[SourceResult]]) -> CrossValidationReport:
        """
        Cross-validate results from multiple sources.

        Args:
            results_by_source: {"mackolik": [...], "tff": [...], "openfootball": [...]}

        Returns:
            CrossValidationReport with validated results and quarantined conflicts.
        """
        report = CrossValidationReport()

        # Group results by match_id across sources
        by_match: dict[int, list[SourceResult]] = {}
        for source_results in results_by_source.values():
            for r in source_results:
                by_match.setdefault(r.match_id, []).append(r)

        for match_id, match_results in by_match.items():
            scores = [(r.ft_home, r.ft_away) for r in match_results]
            score_counts = Counter(scores)
            most_common_score, most_common_count = score_counts.most_common(1)[0]

            total = len(match_results)

            if len(set(scores)) == 1:
                # All sources agree
                report.validated.append(ValidatedResult(
                    match_id=match_id,
                    ft_home=most_common_score[0],
                    ft_away=most_common_score[1],
                    confidence=1.0,
                    sources_agreed=total,
                    sources_total=total,
                ))
            elif most_common_count >= 2:
                # Majority vote
                report.validated.append(ValidatedResult(
                    match_id=match_id,
                    ft_home=most_common_score[0],
                    ft_away=most_common_score[1],
                    confidence=most_common_count / total,
                    sources_agreed=most_common_count,
                    sources_total=total,
                ))
            else:
                # No majority — quarantine
                report.quarantined.append({
                    "match_id": match_id,
                    "conflicting_scores": {r.source: (r.ft_home, r.ft_away) for r in match_results},
                    "reason": "no_majority",
                })
                log.warning(f"Quarantined match {match_id}: conflicting scores from {total} sources")

        return report
