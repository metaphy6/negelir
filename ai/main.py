"""
Negelir AI Engine — Entry Point
Runs the full pipeline: scrape → process → train → analyze → respond
"""

import sys
from pipeline.runner import PipelineRunner
from common.logger import get_logger

log = get_logger("main")


def main():
    log.info("⚽ Negelir AI Engine starting...")
    runner = PipelineRunner()

    if "--demo" in sys.argv:
        runner.run_demo()
    elif "--train" in sys.argv:
        runner.run_training_only()
    else:
        runner.run_full_pipeline()


if __name__ == "__main__":
    main()
