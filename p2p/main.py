"""
Negelir P2P — Simulation entry point.
"""
import sys
from simulation.runner import P2PSimulation
from node.peer import get_p2p_logger

log = get_p2p_logger("main")


def main():
    log.info("🌐 Negelir P2P Simulation starting...")
    sim = P2PSimulation()
    sim.run()


if __name__ == "__main__":
    main()
