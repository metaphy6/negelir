"""
Negelir AI Engine — Entry Point
Runs the full pipeline: scrape → process → train → analyze → respond
Phase 3: Uses NegelirScheduler instead of while-True-sleep loops.
"""

import os
import signal
import sys
import time
from pipeline.runner import PipelineRunner
from scheduler import NegelirScheduler, build_default_schedule
from common.logger import get_logger

log = get_logger("main")

_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    _shutdown = True
    log.info("Shutdown signal received")


def main():
    global _shutdown
    log.info("⚽ Negelir AI Engine starting...")
    runner = PipelineRunner()

    if "--continuous" in sys.argv:
        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)

        scheduler = NegelirScheduler()
        interval = int(os.getenv("SIMULATION_INTERVAL", "30"))

        def run_cycle():
            try:
                if "--demo" in sys.argv:
                    runner.run_demo()
                else:
                    runner.run_full_pipeline()
            except Exception as e:
                log.error(f"Pipeline cycle failed: {e}")

        build_default_schedule(scheduler, scrape_fn=run_cycle)
        scheduler.start()
        log.info(f"🔄 Scheduler started — jobs: {scheduler.job_ids}")

        # Keep main thread alive
        while not _shutdown:
            time.sleep(interval)

        scheduler.shutdown()
        log.info("Scheduler stopped")
    elif "--demo" in sys.argv:
        runner.run_demo()
    elif "--train" in sys.argv:
        runner.run_training_only()
    else:
        runner.run_full_pipeline()


if __name__ == "__main__":
    main()
