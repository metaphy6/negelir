"""
Negelir P2P — Simulation entry point.
"""
import os
import sys
import time
from simulation.runner import P2PSimulation, run_scaling_test, run_churn_test
from node.peer import get_p2p_logger

log = get_p2p_logger("main")


def main():
    log.info("🌐 Negelir P2P Simulation starting...")

    if "--scale-test" in sys.argv:
        count = 25
        for arg in sys.argv:
            if arg.startswith("--nodes="):
                count = int(arg.split("=")[1])
        run_scaling_test(target_nodes=count)
        return

    if "--churn-test" in sys.argv:
        run_churn_test()
        return

    if "--continuous" in sys.argv:
        interval = int(os.getenv("SIMULATION_INTERVAL", "30"))
        log.info(f"🔄 Continuous mode — interval {interval}s (Ctrl+C to stop)")
        cycle = 0
        while True:
            cycle += 1
            log.info(f"\n{'═' * 60}")
            log.info(f"🔄 P2P Cycle {cycle}")
            log.info(f"{'═' * 60}")
            try:
                sim = P2PSimulation()
                sim.run()
            except Exception as e:
                log.error(f"Cycle {cycle} failed: {e}")
            log.info(f"💤 Sleeping {interval}s before next cycle...")
            time.sleep(interval)
    else:
        sim = P2PSimulation()
        sim.run()


if __name__ == "__main__":
    main()
