"""JSON Schemas for swarm bus topics.

Per ROADMAP §3.5: every new topic requires (a) a row in the topic catalog,
(b) a JSON Schema in `ai/swarm/sdk/schemas/<topic>.json`, (c) a config-driven
consumer-group prefix.

Phase 3 ships only the echo example schemas. Real topic schemas land with
the agents that produce/consume them (Phase 4+).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_SCHEMA_DIR = Path(__file__).parent


def load(topic: str) -> dict[str, Any]:
    """Load a topic's JSON schema by topic name (e.g. ``"echo.in"``).

    The parsed schema is cached (Pre-Phase-6 audit PERF3); callers
    must treat the returned dict as **read-only**. Mutating it
    poisons the cache for every other consumer.
    """
    return _load_cached(topic)


@lru_cache(maxsize=64)
def _load_cached(topic: str) -> dict[str, Any]:
    """Pre-Phase-6 audit PERF3: cache the parsed JSON schema per topic.

    The hot path (``validate()`` on every bus message) was re-reading
    and re-parsing the schema file each time; with N topics × M
    messages this became measurable in steady-state. ``maxsize=64``
    is comfortably above the current topic count.
    """
    path = _SCHEMA_DIR / f"{topic}.json"
    if not path.exists():
        raise FileNotFoundError(f"no schema registered for topic {topic!r}")
    return json.loads(path.read_text(encoding="utf-8"))


def known_topics() -> list[str]:
    """Return the list of topics that ship a schema in this build."""
    return sorted(p.stem for p in _SCHEMA_DIR.glob("*.json"))


# ── Phase 8 §8.0 — per-kind sub-schema discriminator ─────────────────────
#
# Some topics ship a ``oneOf``-on-``kind`` discipline: the legacy flat
# parent schema stays at ``<topic>.json`` (for back-compat with Phase
# 6/7 producers), and per-kind sub-schemas live under
# ``<topic>/<kind>.json``. Phase 8 ops console + reactors use the
# typed ``validate_kind(topic, payload)`` helper below to validate
# against the kind-specific shape; legacy producers continue to use
# ``validate(topic, payload)`` against the flat parent.
#
# Single source of truth for "which topics are kind-discriminated":
# the presence of a ``<topic>/`` directory next to ``<topic>.json``.
# Adding a new kind is two edits in the same diff (sub-schema file
# + producer factory). The boundary tests in
# ``ai/swarm/agents/maint/tests/test_phase8_kind_routing.py``
# enforce symmetry against ``swarm.agents.maint._ack_routing``.


def kind_discriminated_topics() -> list[str]:
    """Return topics that ship per-kind sub-schemas under ``<topic>/``."""
    return sorted(
        p.name for p in _SCHEMA_DIR.iterdir()
        if p.is_dir() and (_SCHEMA_DIR / f"{p.name}.json").exists()
    )


def known_kinds(topic: str) -> list[str]:
    """Return the per-kind sub-schema names for a kind-discriminated
    topic.  Returns ``[]`` for topics that are not kind-discriminated.

    Note: **retired** kinds (those moved to ``<topic>/retired/``) are
    NOT included in this list — they are accessible via
    :func:`retired_kinds` and :func:`known_kinds_all`.
    """
    sub_dir = _SCHEMA_DIR / topic
    if not sub_dir.is_dir():
        return []
    return sorted(p.stem for p in sub_dir.glob("*.json") if not p.parent.name == "retired")


def retired_kinds(topic: str) -> list[str]:
    """Return the per-kind sub-schema names that have been retired for
    ``topic`` (i.e. moved to the ``<topic>/retired/`` subdirectory after
    their deprecation window elapsed).

    Per §8.15.2 deprecation path: a retired kind is removed from
    ``_ack_routing.py`` and its schema is moved to ``retired/``; spool
    entries carrying a retired kind go through the §8.13.3
    retired-kind path.
    """
    sub_dir = _SCHEMA_DIR / topic / "retired"
    if not sub_dir.is_dir():
        return []
    return sorted(p.stem for p in sub_dir.glob("*.json"))


def known_kinds_all(topic: str) -> list[str]:
    """Return all per-kind sub-schema names for ``topic``, including
    retired ones.  Useful for migration tooling and tests."""
    return sorted(known_kinds(topic) + retired_kinds(topic))


@lru_cache(maxsize=128)
def _load_kind_cached(topic: str, kind: str) -> dict[str, Any]:
    path = _SCHEMA_DIR / topic / f"{kind}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"no per-kind sub-schema registered for topic={topic!r} kind={kind!r} "
            f"(expected at {path})"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def load_kind(topic: str, kind: str) -> dict[str, Any]:
    """Load the per-kind sub-schema for a discriminated topic."""
    return _load_kind_cached(topic, kind)


def validate_kind(topic: str, payload: dict[str, Any]) -> list[str]:
    """Validate ``payload`` against ``<topic>/<payload['kind']>.json``.

    Empty list ⇒ payload is consistent with the per-kind sub-schema.
    Returns a single-element error list (and does NOT raise) when
    ``payload`` is missing the ``kind`` discriminator or carries an
    unknown kind — keeps the call shape symmetric with
    :func:`validate` so producer code paths can collect errors
    uniformly.
    """
    if "kind" not in payload:
        return [f"{topic}: payload missing required discriminator key 'kind'"]
    kind = payload["kind"]
    if not isinstance(kind, str) or not kind:
        return [f"{topic}: 'kind' must be a non-empty string, got {kind!r}"]
    try:
        sub_schema = load_kind(topic, kind)
    except FileNotFoundError:
        return [
            f"{topic}: kind {kind!r} has no per-kind sub-schema "
            f"(expected at {topic}/{kind}.json)"
        ]
    return _validate_against_schema(f"{topic}/{kind}", sub_schema, payload)


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
    return _validate_against_schema(topic, schema, payload)


def _validate_against_schema(
    label: str, schema: dict[str, Any], payload: dict[str, Any]
) -> list[str]:
    errors: list[str] = []

    required = list(schema.get("required", []))
    properties = dict(schema.get("properties", {}))
    # Pre-Phase-6 audit SK1: closed-by-default. Every shipped schema
    # already declares `additionalProperties` explicitly, so flipping
    # the validator default does not regress any payload — but it
    # turns "forgot to declare it" into a loud test failure for
    # future schema authors instead of a silent looseness.
    additional = schema.get("additionalProperties", False)

    for key in required:
        if key not in payload:
            errors.append(f"{label}: missing required key {key!r}")

    if additional is False:
        for key in payload:
            if key not in properties:
                errors.append(
                    f"{label}: unknown key {key!r} "
                    f"(additionalProperties=false)"
                )

    for key, value in payload.items():
        spec = properties.get(key)
        if spec is None:
            continue
        # Skip $ref-only properties (validated transitively elsewhere).
        if "$ref" in spec and "type" not in spec:
            continue
        # Honor `const` (per-kind sub-schemas use it to pin `kind`).
        if "const" in spec and value != spec["const"]:
            errors.append(
                f"{label}.{key}: value {value!r} does not equal "
                f"const {spec['const']!r}"
            )
            continue
        if not _accepts(spec, value):
            errors.append(
                f"{label}.{key}: value {value!r} does not satisfy "
                f"type={spec.get('type')!r}"
            )
        enum = spec.get("enum")
        if enum is not None and value is not None and value not in enum:
            errors.append(
                f"{label}.{key}: value {value!r} not in declared enum {enum}"
            )
        min_length = spec.get("minLength")
        if min_length is not None and isinstance(value, str) and len(value) < min_length:
            errors.append(
                f"{label}.{key}: string length {len(value)} below "
                f"minLength={min_length}"
            )

    return errors
