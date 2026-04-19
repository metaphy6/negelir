"""
Negelir — Phase 3 stage artifacts.

Each pipeline stage produces a typed dataclass that is the *only* thing
the next stage receives. Artifacts round-trip through JSON sidecars on disk
so that pipeline runs are inspectable and resumable.

See docs/planning/ROADMAP.md §3.1–3.2.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class StageArtifact:
    """Base class — every concrete artifact subclasses this."""

    stage: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["stage"] = self.stage or self.__class__.__name__
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StageArtifact":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class ScrapeArtifact(StageArtifact):
    stage: str = "scrape"
    league_id: str = ""
    matches: list[dict] = field(default_factory=list)
    source_breakdown: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    cache_path: str = ""


@dataclass
class ValidationArtifact(StageArtifact):
    stage: str = "validate"
    kept: int = 0
    quarantined: int = 0
    quarantine_rate: float = 0.0
    cross_source_agreement: float = 1.0
    warnings: int = 0
    errors: int = 0


@dataclass
class SplitArtifact(StageArtifact):
    stage: str = "split"
    train_match_count: int = 0
    holdout_match_count: int = 0
    holdout_window_weeks: int = 0
    holdout_matches: list[dict] = field(default_factory=list)


@dataclass
class TrainingArtifact(StageArtifact):
    stage: str = "train"
    model_path: str = ""
    model_size_mb: float = 0.0
    test_acc: float = 0.0
    log_loss: float = 0.0
    n_features: int = 0
    top_features: list[tuple[str, float]] = field(default_factory=list)


@dataclass
class VerifyArtifact(StageArtifact):
    stage: str = "verify"
    overall_acc: float = 0.0
    coverage: float = 0.0
    per_market_acc: dict[str, float] = field(default_factory=dict)
    brier_score: float = 0.0
    calibration_bins: list[dict] = field(default_factory=list)


@dataclass
class ReportArtifact(StageArtifact):
    stage: str = "report"
    schema_version: int = 1
    run_id: str = ""
    league_id: str = ""
    verdict: str = "FAIL"  # PASS | PASS_DEGRADED | FAIL
    failed_stage: str = ""
    txt_path: str = ""
    json_path: str = ""


# Stage execution order — used by the coordinator for `--force-from` semantics
STAGE_ORDER = (
    "scrape",
    "validate",
    "split",
    "train",
    "verify",
    "report",
)
