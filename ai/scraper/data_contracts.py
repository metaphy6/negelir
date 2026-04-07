"""
Negelir — Data contract validation for scraped data.
Phase 7: Invariants that extracted data must satisfy before acceptance.
"""

from dataclasses import dataclass
from typing import Any, Callable

from common.logger import get_logger

log = get_logger("scraper.data_contracts")


@dataclass
class DataContract:
    """An invariant that extracted data must satisfy."""
    field: str
    constraint: Callable[[Any, dict], bool]
    description: str


# ── Standing contracts ──

STANDING_CONTRACTS = [
    DataContract(
        "team_count",
        lambda v, _: 18 <= v <= 21,
        "Süper Lig has 18-21 teams per season",
    ),
    DataContract(
        "points",
        lambda v, _: 0 <= v <= 120,
        "Max points = 3 × 40 matches = 120",
    ),
    DataContract(
        "goals",
        lambda v, _: 0 <= v <= 200,
        "No team scores >200 goals in a season",
    ),
    DataContract(
        "w_d_l_sum",
        lambda v, _: v["w"] + v["d"] + v["l"] == v["played"],
        "W+D+L must equal matches played",
    ),
]

# ── Match stat contracts ──

MATCH_STAT_CONTRACTS = [
    DataContract(
        "possession_sum",
        lambda v, _: abs(v["home"] + v["away"] - 100.0) < 2.0,
        "Possession percentages must sum to ~100%",
    ),
    DataContract(
        "shots_on_target",
        lambda v, _: v["on_target_home"] <= v["total_home"] and v["on_target_away"] <= v["total_away"],
        "Shots on target cannot exceed total shots",
    ),
    DataContract(
        "pass_accuracy",
        lambda v, _: 0 <= v["home"] <= 100 and 0 <= v["away"] <= 100,
        "Pass accuracy must be 0-100%",
    ),
]


class ContractValidator:
    """Validates extracted data against a list of contracts."""

    def validate(self, data: dict, contracts: list[DataContract],
                 context: dict | None = None) -> tuple[bool, list[str]]:
        """
        Returns (all_passed, list_of_violations).
        Data is accepted only if all contracts pass.
        """
        context = context or {}
        violations = []

        for contract in contracts:
            try:
                if contract.field in data:
                    if not contract.constraint(data[contract.field], context):
                        violations.append(
                            f"{contract.field}: {contract.description}"
                        )
            except (KeyError, TypeError, ValueError) as e:
                violations.append(f"{contract.field}: validation error — {e}")

        all_passed = len(violations) == 0
        if not all_passed:
            log.warning(f"Contract violations ({len(violations)}): {violations}")
        return all_passed, violations
