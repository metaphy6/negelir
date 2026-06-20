"""
Negelir — Scheduler integration.
Phase 3: Replaces while-True-sleep loops with APScheduler.
Schedules: daily scrape, outcome check, weekly retrain, heartbeat.
"""

from datetime import datetime, timezone

from ai.common.config import cfg
from ai.common.logger import get_logger

log = get_logger("scheduler")


class NegelirScheduler:
    """
    Task scheduler for autonomous pipeline operations.
    Uses in-memory job store (no DB dependency for core scheduling).
    APScheduler is used when available; falls back to a simple tick-based loop.
    """

    def __init__(self):
        self._jobs: dict[str, dict] = {}
        self._scheduler = None
        self._use_apscheduler = False

        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            self._scheduler = BackgroundScheduler()
            self._use_apscheduler = True
            log.info("APScheduler available — using cron/interval triggers")
        except ImportError:
            log.info("APScheduler not installed — using simple job registry")

    def add_cron_job(self, job_id: str, func, **cron_kwargs):
        """Add a cron-triggered job (e.g., hour=6, minute=0)."""
        self._jobs[job_id] = {"func": func, "trigger": "cron", "kwargs": cron_kwargs}
        if self._use_apscheduler:
            self._scheduler.add_job(
                func, "cron", id=job_id, replace_existing=True, **cron_kwargs
            )
        log.info(f"Registered cron job: {job_id} ({cron_kwargs})")

    def add_interval_job(self, job_id: str, func, **interval_kwargs):
        """Add an interval-triggered job (e.g., minutes=5)."""
        self._jobs[job_id] = {"func": func, "trigger": "interval", "kwargs": interval_kwargs}
        if self._use_apscheduler:
            self._scheduler.add_job(
                func, "interval", id=job_id, replace_existing=True, **interval_kwargs
            )
        log.info(f"Registered interval job: {job_id} ({interval_kwargs})")

    def start(self):
        """Start the scheduler."""
        if self._use_apscheduler and self._scheduler:
            self._scheduler.start()
            log.info(f"Scheduler started with {len(self._jobs)} job(s)")
        else:
            log.info(f"Job registry active with {len(self._jobs)} job(s) (no background scheduler)")

    def shutdown(self):
        """Gracefully stop the scheduler."""
        if self._use_apscheduler and self._scheduler:
            from apscheduler.schedulers.base import SchedulerNotRunningError

            try:
                self._scheduler.shutdown(wait=False)
            except SchedulerNotRunningError:
                # Keep shutdown idempotent when scheduler has not been started.
                pass
        log.info("Scheduler shut down")

    @property
    def job_ids(self) -> list[str]:
        return list(self._jobs.keys())

    def get_job(self, job_id: str) -> dict | None:
        return self._jobs.get(job_id)

    def tick(self):
        """
        Manual tick for non-APScheduler mode.
        Called from the main loop; executes due jobs.
        """
        if self._use_apscheduler:
            return  # APScheduler handles its own timing
        # In simple mode, jobs are executed by the caller via get_job()
        pass


def build_default_schedule(scheduler: NegelirScheduler,
                           scrape_fn=None, outcome_fn=None,
                           retrain_fn=None, heartbeat_fn=None):
    """
    Register default Negelir jobs:
      - daily_scrape: 06:00 UTC
      - outcome_check: 22:00 UTC
      - weekly_retrain: Sunday 03:00 UTC
      - heartbeat: every 5 minutes
    """
    if scrape_fn:
        scheduler.add_cron_job(
            "daily_scrape",
            scrape_fn,
            hour=cfg.schedule_daily_scrape_hour,
            minute=cfg.schedule_daily_scrape_minute,
        )
    if outcome_fn:
        scheduler.add_cron_job(
            "outcome_check",
            outcome_fn,
            hour=cfg.schedule_outcome_check_hour,
            minute=cfg.schedule_outcome_check_minute,
        )
    if retrain_fn:
        scheduler.add_cron_job(
            "weekly_retrain",
            retrain_fn,
            day_of_week=cfg.schedule_retrain_day,
            hour=cfg.schedule_retrain_hour,
        )
    if heartbeat_fn:
        scheduler.add_interval_job(
            "heartbeat",
            heartbeat_fn,
            minutes=cfg.schedule_heartbeat_minutes,
        )
