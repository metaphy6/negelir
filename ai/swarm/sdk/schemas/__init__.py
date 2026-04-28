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


# ── Lightweight validator (no jsonschema dep) ────────────────────────────
# Intentionally loose: catches the drift modes we care about (renamed
# keys, wrong scalar types, unknown keys when additionalProperties=False,
# enum violations). For deep nested schemas use the per-topic regression
# tests; for runtime hardening upgrade to the `jsonschema` package later.

_PYTHON_TYPE_MAP: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "object": (dict,),
    "array": (list, tuple),
    "null": (type(None),),
}


def _accepts(spec: dict[str, Any], value: Any) -> bool:
    types = spec.get("type")
    if types is None:
        return True
    if isinstance(types, str):
        types = [types]
    if value is None:
        return "null" in types
    for t in types:
        if isinstance(value, _PYTHON_TYPE_MAP.get(t, ())):
            # Reject `bool` matching `integer` (Python quirk).
            if t == "integer" and isinstance(value, bool):
                continue
            return True
    return False


def validate(topic: str, payload: dict[str, Any]) -> list[str]:
    """Return a list of human-readable wire-contract errors for ``payload``.

    Empty list ⇒ payload is consistent with the registered schema.
    Raises ``FileNotFoundError`` if no schema is registered for ``topic``.
    """
    schema = load(topic)
    errors: list[str] = []

    required = list(schema.get("required", []))
    properties = dict(schema.get("properties", {}))
    additional = schema.get("additionalProperties", True)

    for key in required:
        if key not in payload:
            errors.append(f"{topic}: missing required key {key!r}")

    if additional is False:
        for key in payload:
            if key not in properties:
                errors.append(
                    f"{topic}: unknown key {key!r} "
                    f"(additionalProperties=false)"
                )

    for key, value in payload.items():
        spec = properties.get(key)
        if spec is None:
            continue
        # Skip $ref-only properties (validated transitively elsewhere).
        if "$ref" in spec and "type" not in spec:
            continue
        if not _accepts(spec, value):
            errors.append(
                f"{topic}.{key}: value {value!r} does not satisfy "
                f"type={spec.get('type')!r}"
            )
        enum = spec.get("enum")
        if enum is not None and value is not None and value not in enum:
            errors.append(
                f"{topic}.{key}: value {value!r} not in declared enum {enum}"
            )

    return errors
