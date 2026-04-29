"""Contract tests for the `proof.flag` kind registry.

Per pre-Phase 6 audit §B1 / §D2: the JSON-schema enum for
``proof.flag.kind`` and the in-code ``ProofFlagKind`` registry must
agree exactly. The validate() helper enforces enum at live emission;
these tests guard the registry side of that contract and confirm
every Phase 4/5 producer emits a registered kind that survives
schema validation.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from swarm.agents.payloads import ProofFlagKind
from swarm.sdk.schemas import validate


SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "sdk"
    / "schemas"
    / "proof.flag.json"
)


def test_registry_matches_schema_enum() -> None:
    """Registry ↔ schema enum must agree exactly (no drift either direction)."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    schema_enum = set(schema["properties"]["kind"]["enum"])
    registry = ProofFlagKind.all_kinds()
    missing_in_schema = registry - schema_enum
    missing_in_registry = schema_enum - registry
    assert not missing_in_schema, (
        f"ProofFlagKind values not declared in schema enum: {missing_in_schema}"
    )
    assert not missing_in_registry, (
        f"Schema enum values not declared in ProofFlagKind: {missing_in_registry}"
    )


@pytest.mark.parametrize("kind", sorted(ProofFlagKind.all_kinds()))
def test_every_registered_kind_validates(kind: str) -> None:
    """A minimal payload with each registered kind must satisfy the schema."""
    errors = validate("proof.flag", {"kind": kind})
    assert errors == [], f"unexpected validation errors for {kind}: {errors}"


def test_unregistered_kind_is_rejected() -> None:
    """Sanity: enum guard rejects a made-up kind."""
    errors = validate("proof.flag", {"kind": "definitely_not_a_real_kind"})
    assert any("not in declared enum" in e for e in errors), errors


def test_phase5_consensus_kinds_are_registered() -> None:
    """Regression for B1: the three Phase-5 consensus kinds were the
    actual drift the audit caught. Pin them explicitly so a future
    refactor can't drop the symbols silently."""
    assert ProofFlagKind.LATE_VOTE_DROPPED == "late_vote_dropped"
    assert ProofFlagKind.CONSENSUS_NO_VOTES == "consensus_no_votes"
    assert ProofFlagKind.CONSENSUS_OVERFLOW == "consensus_overflow"


def test_phase4_kinds_are_registered() -> None:
    """Regression for B1: don't drop Phase 4 kinds during refactors either."""
    assert ProofFlagKind.UPSTREAM_MISSING == "upstream_missing"
    assert ProofFlagKind.DECODE_FAILED == "decode_failed"
    assert ProofFlagKind.EMPTY_PARSE == "empty_parse"
    assert ProofFlagKind.PARSER_EXCEPTION == "parser_exception"
    assert ProofFlagKind.INVALID_RECORD == "invalid_record"
    assert ProofFlagKind.LOW_CONFIDENCE_CLASSIFICATION == "low_confidence_classification"
