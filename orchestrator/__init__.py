"""Negelir — Swarm orchestrator and state machine.

Pivot v3 component: orchestrator (moved from ai/orchestrator/ in Phase 22.4).

Coordinates multi-agent workflows, manages state transitions, and implements
the Phase 4+ workflow orchestration contract.

Public API: orchestration, state management, workflow execution.
"""

__all__ = [
    "Orchestrator",
    "StateMachine",
    "WorkflowExecutor",
]
