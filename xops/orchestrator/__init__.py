"""Negelir ROADMAP-phase orchestration toolkit.

Parallel-safe coordinator for delegating ROADMAP phases to context-isolated
subagents. Provides:

- Deterministic ROADMAP parser (`roadmap.py`).
- Include / exclude phase-id filtering (`selector.py`).
- File-locked phase claims for parallel-safe runs (`locks.py`).
- Per-phase JSON state machine (`state.py`).
- CLI used by `make orchestrate.*` targets (`cli.py`).

The chat-side glue (which actually emits `runSubagent(...)` calls) lives in
`.github/prompts/orchestrate.roadmap.prompt.md` and the
`.github/chatmodes/phase-{implementer,reviewer,verifier}.chatmode.md` modes.
This package contains zero git or runSubagent calls — those are the agent's
responsibility, per AGENTS.md Rule 9.
"""

__all__ = ["roadmap", "selector", "locks", "state", "cli"]
