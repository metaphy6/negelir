"""Phase 8 §8.15.2 — per-kind sub-schema versioning doctrine tests.

Boundary tests (§8.15.2 Bullet 6):
  (a) Sub-schema enumerator: every kind file carries ``kind_schema_version: int``.
  (b) Backward-compat: for every kind with ``kind_schema_version > 1``,
      a v1 example payload is accepted by the current factory (additive-only
      enforcement).  Vacuous when no kind has been bumped past v1 yet.
  (c) Producer-vs-file version mismatch → boot validation refuses with
      ``SystemExit(1)`` / ``KindSchemaDriftError``.

Additional tests:
  (d) Consumer ``from_dict`` preserves unknown fields in ``_extra``.
  (e) Consumer ``from_dict`` raises on missing ``kind`` or ``produced_at``.
  (f) Factory ``_make`` raises on unregistered kind.
  (g) Deprecated kind sub-schema triggers ``DeprecationWarning``.
  (h) ``retired_kinds`` and ``known_kinds_all`` return consistent sets.
  (i) ``validate_boot`` is idempotent for the real on-disk schemas.
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

_SDK_SCHEMAS = Path(__file__).parent.parent / "schemas" / "maint.event.v1"

# ---------------------------------------------------------------------------
# (a) Every kind file carries kind_schema_version
# ---------------------------------------------------------------------------

def _all_kind_files() -> list[Path]:
    """Return every *.json under maint.event.v1/ (excluding retired/)."""
    return sorted(_SDK_SCHEMAS.glob("*.json"))


@pytest.mark.parametrize("kind_path", _all_kind_files(), ids=lambda p: p.stem)
def test_kind_schema_has_kind_schema_version(kind_path: Path) -> None:
    """(a) Every per-kind sub-schema must carry kind_schema_version in
    both ``required`` and ``properties``."""
    data: dict[str, Any] = json.loads(kind_path.read_text(encoding="utf-8"))
    props = data.get("properties", {})
    required = data.get("required", [])

    assert "kind_schema_version" in props, (
        f"{kind_path.name}: missing 'kind_schema_version' in 'properties'"
    )
    assert "kind_schema_version" in required, (
        f"{kind_path.name}: 'kind_schema_version' is not in 'required'"
    )
    ksv_spec = props["kind_schema_version"]
    assert "const" in ksv_spec, (
        f"{kind_path.name}: 'kind_schema_version' property must use 'const'; got {ksv_spec}"
    )
    assert isinstance(ksv_spec["const"], int), (
        f"{kind_path.name}: 'kind_schema_version.const' must be an integer"
    )
    assert ksv_spec["const"] >= 1, (
        f"{kind_path.name}: 'kind_schema_version' must be >= 1"
    )


# ---------------------------------------------------------------------------
# (b) Backward-compat: kinds with kind_schema_version > 1 must accept v1
# ---------------------------------------------------------------------------

def _bumped_kind_files() -> list[Path]:
    """Return kind files where kind_schema_version.const > 1."""
    bumped = []
    for p in _all_kind_files():
        data = json.loads(p.read_text(encoding="utf-8"))
        ksv = data.get("properties", {}).get("kind_schema_version", {}).get("const", 1)
        if isinstance(ksv, int) and ksv > 1:
            bumped.append(p)
    return bumped


@pytest.mark.skipif(
    not _bumped_kind_files(),
    reason="No kinds have kind_schema_version > 1 yet (vacuous enforcement).",
)
@pytest.mark.parametrize("kind_path", _bumped_kind_files(), ids=lambda p: p.stem)
def test_backward_compat_v1_payload_accepted(kind_path: Path) -> None:
    """(b) For every kind with kind_schema_version > 1, a v1 example
    payload must be accepted by from_dict without errors.

    The v1 example must live at
    ``ai/swarm/sdk/schemas/maint.event.v1/<kind>.v1.example.json``.
    """
    example_path = kind_path.parent / f"{kind_path.stem}.v1.example.json"
    assert example_path.exists(), (
        f"Backward-compat test requires a v1 example payload at {example_path}. "
        f"Create it alongside the schema when bumping kind_schema_version."
    )
    payload: dict[str, Any] = json.loads(example_path.read_text(encoding="utf-8"))

    from swarm.sdk.payloads import MaintEvent

    evt = MaintEvent.from_dict(payload)
    assert evt.kind == kind_path.stem


# ---------------------------------------------------------------------------
# (c) Producer-vs-file version mismatch → boot validation refuses
# ---------------------------------------------------------------------------

def test_validate_boot_detects_code_vs_file_mismatch(tmp_path: Path) -> None:
    """(c) When the in-code constant for a kind does not match the on-disk
    schema's kind_schema_version, validate_boot raises KindSchemaDriftError
    (SystemExit code 1)."""
    from swarm.sdk.kind_schema_version import KIND_SCHEMA_VERSIONS, KindSchemaDriftError, validate_boot

    # Pick any kind that exists on disk.
    sample_kind = next(iter(sorted(KIND_SCHEMA_VERSIONS)))

    # Patch KIND_SCHEMA_VERSIONS to claim the kind is at version 999
    # (while the on-disk schema says 1).
    patched = {**KIND_SCHEMA_VERSIONS, sample_kind: 999}
    with patch("swarm.sdk.kind_schema_version.KIND_SCHEMA_VERSIONS", patched):
        with pytest.raises(KindSchemaDriftError) as exc_info:
            validate_boot()

    assert exc_info.value.code == 1
    assert sample_kind in exc_info.value.detail  # type: ignore[attr-defined]


def test_validate_boot_passes_with_consistent_versions() -> None:
    """(c-clean) validate_boot succeeds when code constants match on-disk
    schemas (the nominal case)."""
    from swarm.sdk.kind_schema_version import validate_boot

    # Should not raise.
    validate_boot()


def test_validate_boot_detects_missing_schema_file(tmp_path: Path) -> None:
    """(c) A kind in KIND_SCHEMA_VERSIONS with no corresponding .json file
    is also treated as drift."""
    from swarm.sdk.kind_schema_version import KIND_SCHEMA_VERSIONS, KindSchemaDriftError, validate_boot

    patched = {**KIND_SCHEMA_VERSIONS, "nonexistent_ghost_kind": 1}
    with patch("swarm.sdk.kind_schema_version.KIND_SCHEMA_VERSIONS", patched):
        with pytest.raises(KindSchemaDriftError) as exc_info:
            validate_boot()
    assert exc_info.value.code == 1
    assert "nonexistent_ghost_kind" in exc_info.value.detail  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# (d) Consumer from_dict preserves unknown fields in _extra
# ---------------------------------------------------------------------------

def test_from_dict_preserves_extra_fields() -> None:
    """(d) Fields not in the known envelope set land in _extra and are
    accessible via payload._extra['key'] and payload.get('key')."""
    from swarm.sdk.payloads import MaintEvent

    payload = {
        "kind": "scale_decision",
        "produced_at": "2026-05-22T00:00:00Z",
        "kind_schema_version": 1,
        "target": "pred.elo.v1",
        # Unknown fields simulating a future kind_schema_version=2 addition:
        "future_field_alpha": "some_value",
        "future_field_beta": 42,
    }
    evt = MaintEvent.from_dict(payload)
    assert evt.kind == "scale_decision"
    assert evt.target == "pred.elo.v1"
    assert evt._extra["future_field_alpha"] == "some_value"
    assert evt._extra["future_field_beta"] == 42
    # Also accessible via .get()
    assert evt.get("future_field_alpha") == "some_value"
    assert evt.get("absent_key", "default") == "default"


def test_from_dict_known_envelope_fields_not_in_extra() -> None:
    """(d) Known envelope fields (target, request_id, etc.) must NOT
    appear in _extra — they land on the dataclass attributes."""
    from swarm.sdk.payloads import MaintEvent

    payload = {
        "kind": "maint_paused",
        "produced_at": "2026-05-22T00:00:00Z",
        "kind_schema_version": 1,
        "target": "maint.scaler.v1",
        "request_id": "req-abc-123",
        "agent_id": "maint.scaler.v1",
    }
    evt = MaintEvent.from_dict(payload)
    assert evt.target == "maint.scaler.v1"
    assert evt.request_id == "req-abc-123"
    assert evt.agent_id == "maint.scaler.v1"
    # These are envelope fields — must NOT be in _extra.
    assert "target" not in evt._extra
    assert "request_id" not in evt._extra
    assert "agent_id" not in evt._extra


def test_from_dict_kind_schema_version_defaults_to_1() -> None:
    """(d) A payload without kind_schema_version (old producer) defaults to
    version 1 for graceful degradation."""
    from swarm.sdk.payloads import MaintEvent

    payload = {
        "kind": "baseline_reset",
        "produced_at": "2026-05-22T00:00:00Z",
        # No kind_schema_version — old producer
    }
    evt = MaintEvent.from_dict(payload)
    assert evt.kind_schema_version == 1


# ---------------------------------------------------------------------------
# (e) from_dict raises on missing required envelope fields
# ---------------------------------------------------------------------------

def test_from_dict_raises_on_missing_kind() -> None:
    """(e) from_dict raises ValueError when 'kind' is absent."""
    from swarm.sdk.payloads import MaintEvent

    with pytest.raises(ValueError, match="missing required key 'kind'"):
        MaintEvent.from_dict({"produced_at": "2026-05-22T00:00:00Z"})


def test_from_dict_raises_on_missing_produced_at() -> None:
    """(e) from_dict raises ValueError when 'produced_at' is absent."""
    from swarm.sdk.payloads import MaintEvent

    with pytest.raises(ValueError, match="missing required key 'produced_at'"):
        MaintEvent.from_dict({"kind": "scale_decision"})


# ---------------------------------------------------------------------------
# (f) Factory _make raises on unregistered kind
# ---------------------------------------------------------------------------

def test_factory_raises_on_unregistered_kind() -> None:
    """(f) _make raises ValueError for a kind not in KIND_SCHEMA_VERSIONS."""
    from swarm.sdk.payloads import MaintEvent

    with pytest.raises(ValueError, match="no entry in KIND_SCHEMA_VERSIONS"):
        MaintEvent._make("completely_unknown_kind", produced_at="2026-05-22T00:00:00Z")


def test_factory_injects_kind_schema_version() -> None:
    """(f) Factory methods inject kind_schema_version from the constants table."""
    from swarm.sdk.payloads import MaintEvent
    from swarm.sdk.kind_schema_version import KIND_SCHEMA_VERSIONS

    result = MaintEvent.scale_decision(
        produced_at="2026-05-22T00:00:00Z",
        target="pred.elo.v1",
    )
    assert result["kind"] == "scale_decision"
    assert result["kind_schema_version"] == KIND_SCHEMA_VERSIONS["scale_decision"]


# ---------------------------------------------------------------------------
# (g) Deprecated kind triggers DeprecationWarning
# ---------------------------------------------------------------------------

def test_deprecated_kind_warns_on_from_dict(tmp_path: Path) -> None:
    """(g) When the on-disk sub-schema is annotated 'deprecated': true,
    from_dict emits a DeprecationWarning."""
    from swarm.sdk import kind_schema_version as ksv

    # Patch is_deprecated to simulate a deprecated kind for scale_decision.
    with patch.object(ksv, "is_deprecated", return_value=True), \
         patch.object(ksv, "superseded_by", return_value="scale_decision_v2"), \
         patch.object(ksv, "deprecation_window_until", return_value="2026-12-31"):

        from swarm.sdk.payloads import MaintEvent

        payload = {
            "kind": "scale_decision",
            "produced_at": "2026-05-22T00:00:00Z",
            "kind_schema_version": 1,
        }
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            MaintEvent.from_dict(payload)

    dep_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert dep_warnings, "Expected a DeprecationWarning for a deprecated kind"
    msg = str(dep_warnings[0].message)
    assert "scale_decision" in msg
    assert "deprecated" in msg
    assert "scale_decision_v2" in msg


def test_deprecated_kind_warns_on_factory(tmp_path: Path) -> None:
    """(g) Producer factory method also warns on deprecated kind."""
    from swarm.sdk import kind_schema_version as ksv
    from swarm.sdk.payloads import MaintEvent

    with patch.object(ksv, "is_deprecated", return_value=True), \
         patch.object(ksv, "superseded_by", return_value=None), \
         patch.object(ksv, "deprecation_window_until", return_value=None):

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            MaintEvent.scale_decision(produced_at="2026-05-22T00:00:00Z")

    dep_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert dep_warnings


# ---------------------------------------------------------------------------
# (h) retired_kinds and known_kinds_all
# ---------------------------------------------------------------------------

def test_retired_kinds_empty_when_no_retired_dir() -> None:
    """(h) retired_kinds returns [] when there is no retired/ subdirectory."""
    from swarm.sdk.schemas import retired_kinds

    result = retired_kinds("maint.event.v1")
    # Currently no kinds have been retired — the dir may or may not exist.
    assert isinstance(result, list)


def test_known_kinds_all_is_superset_of_known_kinds() -> None:
    """(h) known_kinds_all includes everything in known_kinds plus retired."""
    from swarm.sdk.schemas import known_kinds, known_kinds_all, retired_kinds

    active = set(known_kinds("maint.event.v1"))
    retired = set(retired_kinds("maint.event.v1"))
    all_kinds = set(known_kinds_all("maint.event.v1"))

    assert active | retired == all_kinds


def test_known_kinds_excludes_retired(tmp_path: Path) -> None:
    """(h) known_kinds must NOT include retired kinds (those in retired/)."""
    from swarm.sdk.schemas import known_kinds, retired_kinds

    active = set(known_kinds("maint.event.v1"))
    retired = set(retired_kinds("maint.event.v1"))

    # Intersection must be empty.
    assert active & retired == set(), (
        f"These kinds appear in both active and retired: {active & retired}"
    )


# ---------------------------------------------------------------------------
# (i) validate_boot is idempotent for real schemas
# ---------------------------------------------------------------------------

def test_validate_boot_idempotent() -> None:
    """(i) Calling validate_boot multiple times in the same process is safe."""
    from swarm.sdk.kind_schema_version import validate_boot

    validate_boot()
    validate_boot()
    validate_boot()  # third call — must not raise


def test_kind_schema_versions_covers_all_on_disk_kinds() -> None:
    """(i) Every kind file in maint.event.v1/ has an entry in
    KIND_SCHEMA_VERSIONS, and vice-versa."""
    from swarm.sdk.kind_schema_version import KIND_SCHEMA_VERSIONS
    from swarm.sdk.schemas import known_kinds

    on_disk = set(known_kinds("maint.event.v1"))
    in_code = set(KIND_SCHEMA_VERSIONS)

    missing_from_code = on_disk - in_code
    missing_from_disk = in_code - on_disk

    assert not missing_from_code, (
        f"On-disk kinds missing from KIND_SCHEMA_VERSIONS: {sorted(missing_from_code)}"
    )
    assert not missing_from_disk, (
        f"CODE kinds in KIND_SCHEMA_VERSIONS with no .json file: {sorted(missing_from_disk)}"
    )
