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
