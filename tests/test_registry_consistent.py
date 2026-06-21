"""
Test: test_registry_consistent.py
Phase 16.1 contract validation — registry structure and completeness.

Validates:
1. Registry contains all required base planes (reference, schedule, score, lineup, editorial, market)
2. Registry contains all cross-phase planes (feature_vectors, sec_quarantine, match_outcomes,
   calibration, competition, predict_invalidated)
3. Each plane has at least one version
4. All active versions have valid from/to timestamps
5. Registry is loadable and parseable as valid JSON

Fulfills ledger #19 requirement: Registry is frozen at stream-open time.
"""

import json
import os
from datetime import datetime, timezone
import pytest


@pytest.fixture
def registry():
    """Load the feeds registry."""
    registry_path = os.path.join(
        os.path.dirname(__file__),
        "../common/schemas/feeds/registry.json"
    )
    with open(registry_path) as f:
        return json.load(f)


class TestRegistryStructure:
    """Validate registry structure and content."""

    def test_registry_contains_all_base_planes(self, registry):
        """Registry must contain all six base record types."""
        base_planes = {"reference", "schedule", "score", "lineup", "editorial", "market"}
        assert base_planes.issubset(registry.keys()), \
            f"Registry missing base planes. Expected {base_planes}, got {set(registry.keys())}"

    def test_registry_contains_all_cross_phase_planes(self, registry):
        """Registry must contain all cross-phase planes."""
        cross_phase_planes = {
            "feature_vectors",
            "sec_quarantine",
            "match_outcomes",
            "calibration",
            "competition",
            "predict_invalidated"
        }
        assert cross_phase_planes.issubset(registry.keys()), \
            f"Registry missing cross-phase planes. Expected {cross_phase_planes}, " \
            f"got {set(registry.keys())}"

    def test_each_plane_has_versions(self, registry):
        """Each plane must have at least one version entry."""
        for plane, versions in registry.items():
            assert isinstance(versions, list), \
                f"Plane {plane} versions must be a list, got {type(versions)}"
            assert len(versions) > 0, \
                f"Plane {plane} must have at least one version entry"

    def test_all_versions_have_required_fields(self, registry):
        """Each version entry must have version, status, from, and to fields."""
        required_fields = {"version", "status", "from", "to"}
        for plane, versions in registry.items():
            for idx, version_entry in enumerate(versions):
                assert isinstance(version_entry, dict), \
                    f"Plane {plane} version {idx} must be a dict"
                missing = required_fields - set(version_entry.keys())
                assert not missing, \
                    f"Plane {plane} version {idx} missing fields: {missing}"

    def test_version_numbers_are_positive_integers(self, registry):
        """Version numbers must be positive integers."""
        for plane, versions in registry.items():
            for idx, version_entry in enumerate(versions):
                version = version_entry.get("version")
                assert isinstance(version, int) and version > 0, \
                    f"Plane {plane} version {idx}: version must be a positive integer, " \
                    f"got {version}"

    def test_version_status_is_valid(self, registry):
        """Status must be one of: active, deprecated, eol."""
        valid_statuses = {"active", "deprecated", "eol"}
        for plane, versions in registry.items():
            for idx, version_entry in enumerate(versions):
                status = version_entry.get("status")
                assert status in valid_statuses, \
                    f"Plane {plane} version {idx}: invalid status {status}, " \
                    f"must be one of {valid_statuses}"

    def test_version_timestamps_are_rfc3339(self, registry):
        """from/to timestamps must be RFC 3339 format or null."""
        for plane, versions in registry.items():
            for idx, version_entry in enumerate(versions):
                from_ts = version_entry.get("from")
                to_ts = version_entry.get("to")

                # from must always be a valid timestamp
                assert from_ts is not None, \
                    f"Plane {plane} version {idx}: 'from' must not be null"
                assert isinstance(from_ts, str), \
                    f"Plane {plane} version {idx}: 'from' must be a string, got {type(from_ts)}"

                # Parse to ensure valid RFC 3339
                try:
                    datetime.fromisoformat(from_ts.replace('Z', '+00:00'))
                except ValueError as e:
                    pytest.fail(f"Plane {plane} version {idx}: 'from' is not valid RFC 3339: {e}")

                # to can be null (active forever) or a valid timestamp
                if to_ts is not None:
                    assert isinstance(to_ts, str), \
                        f"Plane {plane} version {idx}: 'to' must be a string or null, " \
                        f"got {type(to_ts)}"
                    try:
                        datetime.fromisoformat(to_ts.replace('Z', '+00:00'))
                    except ValueError as e:
                        pytest.fail(f"Plane {plane} version {idx}: 'to' is not valid RFC 3339: {e}")

    def test_active_versions_not_eol(self, registry):
        """Active versions must not have an eol timestamp (to must be null)."""
        for plane, versions in registry.items():
            for idx, version_entry in enumerate(versions):
                if version_entry.get("status") == "active":
                    to_ts = version_entry.get("to")
                    assert to_ts is None, \
                        f"Plane {plane} version {idx}: active version must have to=null, " \
                        f"got {to_ts}"

    def test_version_ordering_chronological(self, registry):
        """Versions must be ordered chronologically by 'from' timestamp."""
        for plane, versions in registry.items():
            from_timestamps = []
            for version_entry in versions:
                from_ts_str = version_entry.get("from")
                from_ts = datetime.fromisoformat(from_ts_str.replace('Z', '+00:00'))
                from_timestamps.append(from_ts)

            # Check timestamps are in ascending order
            for i in range(len(from_timestamps) - 1):
                assert from_timestamps[i] <= from_timestamps[i + 1], \
                    f"Plane {plane}: versions not in chronological order"

    def test_registry_is_complete_json(self, registry):
        """Registry must be a well-formed JSON object."""
        assert isinstance(registry, dict), "Registry must be a JSON object"
        assert len(registry) > 0, "Registry must not be empty"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
