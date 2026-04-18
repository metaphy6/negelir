"""
Negelir — AI Task Orchestrator state machine.
Per roadmap §5.1: manages scraping → processing → proofreading → analysis → response cycle.
"""

from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime

from common.logger import get_logger, section_banner

log = get_logger("orchestrator")


class OrchestratorState(Enum):
    IDLE = "idle"
    SCRAPING = "scraping"
    PROCESSING = "processing"
    PROOFREADING = "proofreading"
    RESPONDING = "responding"
    VALIDATING = "validating"
    # Phase 3 — full-system training pipeline observation states
    TRAINING = "training"
    P2P_SIMULATION = "p2p_simulation"
    VERIFYING = "verifying"
    REPORTING = "reporting"
    ERROR = "error"


@dataclass
class TaskResult:
    success: bool
    data: dict | None = None
    error: str | None = None
    duration_ms: float = 0.0


@dataclass
class OrchestratorContext:
    """Shared context across orchestrator stages."""
    state: OrchestratorState = OrchestratorState.IDLE
    raw_matches: list[dict] = field(default_factory=list)
    features: dict = field(default_factory=dict)
    proofread_ok: bool = False
    analysis: dict | None = None
    response: str = ""
    errors: list[str] = field(default_factory=list)
    started_at: datetime | None = None


class TaskOrchestrator:
    """
    Autonomous AI task orchestrator.
    Coordinates the full data lifecycle without user intervention.
    """

    def __init__(self):
        self.ctx = OrchestratorContext()
        self._state_handlers = {
            OrchestratorState.IDLE: self._on_idle,
            OrchestratorState.SCRAPING: self._on_scraping,
            OrchestratorState.PROCESSING: self._on_processing,
            OrchestratorState.PROOFREADING: self._on_proofreading,
            OrchestratorState.RESPONDING: self._on_responding,
            OrchestratorState.VALIDATING: self._on_validating,
        }

    def transition(self, new_state: OrchestratorState):
        old = self.ctx.state
        self.ctx.state = new_state
        log.info(f"🔄 State transition: {old.value} → {new_state.value}")

    def run_pipeline(
        self,
        scrape_fn=None,
        process_fn=None,
        proofread_fn=None,
        analyze_fn=None,
        respond_fn=None,
    ) -> OrchestratorContext:
        """
        Execute the full pipeline: scrape → process → proofread → analyze → respond.
        Each step function is injected to allow testing and composition.
        """
        section_banner("AI Orchestrator: Pipeline Starting")
        self.ctx = OrchestratorContext(started_at=datetime.utcnow())

        steps = [
            (OrchestratorState.SCRAPING, scrape_fn, "Data Fetching"),
            (OrchestratorState.PROCESSING, process_fn, "Data Processing"),
            (OrchestratorState.PROOFREADING, proofread_fn, "Data Validation"),
            (OrchestratorState.RESPONDING, analyze_fn, "Analysis & Response"),
        ]

        for state, fn, label in steps:
            self.transition(state)
            if fn:
                try:
                    result = fn(self.ctx)
                    if not result.success:
                        log.error(f"⛔ {label} failed: {result.error}")
                        self.ctx.errors.append(f"{label}: {result.error}")
                        self.transition(OrchestratorState.ERROR)
                        return self.ctx
                    log.info(f"✅ {label} complete ({result.duration_ms:.0f}ms)")
                except Exception as e:
                    log.error(f"⛔ {label} error: {e}")
                    self.ctx.errors.append(f"{label}: {str(e)}")
                    self.transition(OrchestratorState.ERROR)
                    return self.ctx

        self.transition(OrchestratorState.IDLE)
        return self.ctx

    def _on_idle(self):
        log.debug("Idle state")

    def _on_scraping(self):
        log.info("🌐 Data fetching phase")

    def _on_processing(self):
        log.info("⚙️  Data processing phase")

    def _on_proofreading(self):
        log.info("🔍 Data validation phase")

    def _on_responding(self):
        log.info("💬 Response composition phase")

    def _on_validating(self):
        log.info("✔️  Result validation phase")

    # ── Phase 3 — Full-System Training Pipeline observer ──────────

    _STAGE_TO_STATE = {
        "scrape": OrchestratorState.SCRAPING,
        "validate": OrchestratorState.PROOFREADING,
        "split": OrchestratorState.PROCESSING,
        "train": OrchestratorState.TRAINING,
        "p2p_sim": OrchestratorState.P2P_SIMULATION,
        "ensemble": OrchestratorState.P2P_SIMULATION,
        "verify": OrchestratorState.VERIFYING,
        "report": OrchestratorState.REPORTING,
    }

    def run_full_training(
        self,
        *,
        league_id: str | None = None,
        node_count: int | None = None,
        verification_window_weeks: int | None = None,
        force_from: str | None = None,
        skip_p2p: bool = False,
    ):
        """Drive the Phase 3 `TrainingPipeline` and surface stage transitions
        through this orchestrator's state machine.
        """
        from pipeline.training_pipeline import TrainingPipeline

        section_banner("Orchestrator: Full-System Training")

        def _on_start(stage: str, payload: dict):
            target = self._STAGE_TO_STATE.get(stage, OrchestratorState.IDLE)
            self.transition(target)

        def _on_end(stage: str, payload: dict):
            log.info(f"   ↳ {stage}: {payload.get('duration_ms', 0):.0f} ms")

        pipeline = TrainingPipeline(
            league_id=league_id,
            node_count=node_count,
            verification_window_weeks=verification_window_weeks,
            on_stage_start=_on_start,
            on_stage_end=_on_end,
        )
        try:
            report = pipeline.run(force_from=force_from, skip_p2p=skip_p2p)
            self.transition(OrchestratorState.IDLE)
            return report
        except Exception as exc:
            log.error(f"⛔ Full training pipeline failed: {exc}")
            self.transition(OrchestratorState.ERROR)
            raise


def _cli() -> int:
    """CLI entrypoint:

    python -m orchestrator.state_machine --mode full-training [--league ID]
                                         [--force-from STAGE] [--skip-p2p]
    python -m orchestrator.state_machine --mode model-only --league ID
    python -m orchestrator.state_machine --mode sim-only --league ID --model PATH
    """
    import argparse

    parser = argparse.ArgumentParser(description="Negelir orchestrator CLI")
    parser.add_argument("--mode", required=True,
                        choices=["full-training", "model-only", "sim-only"])
    parser.add_argument("--league", default=None)
    parser.add_argument("--nodes", type=int, default=None)
    parser.add_argument("--window-weeks", type=int, default=None)
    parser.add_argument("--force-from", default=None,
                        help="Stage to force re-run from (scrape/validate/split/train/...)")
    parser.add_argument("--skip-p2p", action="store_true")
    parser.add_argument("--model", default=None, help="Existing model path (sim-only mode)")
    args = parser.parse_args()

    orch = TaskOrchestrator()
    if args.mode == "full-training":
        report = orch.run_full_training(
            league_id=args.league,
            node_count=args.nodes,
            verification_window_weeks=args.window_weeks,
            force_from=args.force_from,
            skip_p2p=args.skip_p2p,
        )
    elif args.mode == "model-only":
        report = orch.run_full_training(
            league_id=args.league,
            node_count=args.nodes,
            verification_window_weeks=args.window_weeks,
            force_from=args.force_from,
            skip_p2p=True,
        )
    else:  # sim-only
        from pipeline.training_pipeline import TrainingPipeline
        from pipeline.training_artifacts import (
            ScrapeArtifact, SplitArtifact, TrainingArtifact,
        )
        if not args.model:
            parser.error("--model is required for sim-only mode")
        # Build a minimal pipeline run that re-uses cached scrape/split artifacts.
        pipe = TrainingPipeline(
            league_id=args.league,
            node_count=args.nodes,
            verification_window_weeks=args.window_weeks,
        )
        report = pipe.run(force_from="p2p_sim", skip_p2p=False)

    print(f"Verdict: {report.verdict}  →  {report.txt_path}")
    return 0 if report.verdict in ("PASS", "PASS_DEGRADED") else 1


if __name__ == "__main__":
    import sys
    sys.exit(_cli())
