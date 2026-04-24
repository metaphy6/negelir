"""JSON Schemas for swarm bus topics.

Per ROADMAP §3.5: every new topic requires (a) a row in the topic catalog,
(b) a JSON Schema in `ai/swarm/sdk/schemas/<topic>.json`, (c) a config-driven
consumer-group prefix.

Phase 3 ships only the echo example schemas. Real topic schemas land with
the agents that produce/consume them (Phase 4+).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_SCHEMA_DIR = Path(__file__).parent


def load(topic: str) -> dict[str, Any]:
    """Load a topic's JSON schema by topic name (e.g. ``"echo.in"``)."""
    path = _SCHEMA_DIR / f"{topic}.json"
    if not path.exists():
        raise FileNotFoundError(f"no schema registered for topic {topic!r}")
    return json.loads(path.read_text(encoding="utf-8"))


def known_topics() -> list[str]:
    """Return the list of topics that ship a schema in this build."""
    return sorted(p.stem for p in _SCHEMA_DIR.glob("*.json"))
