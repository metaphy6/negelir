"""Phase 8 §8.15 — maintenance-plane shared helpers (xops side).

The ``ai/swarm/agents/maint/`` package owns the agents themselves;
this package owns cross-process coordination primitives that need
to live outside the agent module (advisory-lock registry, future
runtime controllers, etc.).
"""
