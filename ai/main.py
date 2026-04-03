"""
Negelir AI Engine — Entry Point
Runs the full pipeline: scrape → process → train → analyze → respond
"""

import os
import sys
import time
from pipeline.runner import PipelineRunner
from common.logger import get_logger

log = get_logger("main")


def main():
    log.info("⚽ Negelir AI Engine starting...")
    runner = PipelineRunner()

    if "--continuous" in sys.argv:
        interval = int(os.getenv("SIMULATION_INTERVAL", "30"))
        log.info(f"🔄 Continuous mode — interval {interval}s (Ctrl+C to stop)")
        cycle = 0
        while True:
            cycle += 1
            log.info(f"\n{'═' * 60}")
            log.info(f"🔄 Cycle {cycle}")
            log.info(f"{'═' * 60}")
            try:
                if "--demo" in sys.argv:
                    runner.run_demo()
                else:
                    runner.run_full_pipeline()
            except Exception as e:
                log.error(f"Cycle {cycle} failed: {e}")
            log.info(f"💤 Sleeping {interval}s before next cycle...")
            time.sleep(interval)
    elif "--demo" in sys.argv:
        runner.run_demo()
    elif "--train" in sys.argv:
        runner.run_training_only()
    else:
        runner.run_full_pipeline()


if __name__ == "__main__":
    main()
