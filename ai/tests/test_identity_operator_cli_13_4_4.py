"""
Phase 13.4.4 — Operator merge / split CLI.

Per ROADMAP §13.4.4: `make identity.merge` and `make identity.split` are
the ONLY ways a human can override the resolver. Both write a tracker row
and emit identity.merge.v1 audit topic event.

Proof test: (a) merge command validates input and emits audit event,
(b) split command validates input and emits audit event,
(c) both require a reason (no silent ops).
"""

import json
import subprocess
from typing import Any

import pytest


class TestIdentityOperatorCLI:
    """Test operator merge / split CLI (13.4.4)."""

    def _run_make(self, cmd: str, args: dict[str, str]) -> tuple[int, str, str]:
        """Run a make command and return (returncode, stdout, stderr)."""
        arg_list = []
        for key, val in args.items():
            arg_list.append(f'{key}="{val}"')
        
        full_cmd = f'make {cmd} {" ".join(arg_list)}'
        result = subprocess.run(
            full_cmd,
            shell=True,
            cwd="/home/serhatakbak/code/mine/negelir",
            capture_output=True,
            text=True,
        )
        return result.returncode, result.stdout, result.stderr

    def test_identity_merge_succeeds(self) -> None:
        """Merge command succeeds with valid inputs."""
        code, stdout, stderr = self._run_make(
            "identity.merge",
            {
                "STABLE_IDS": "galatasaray_tr,gala_tr",
                "REASON": "duplicate club",
            },
        )
        assert code == 0
        assert "✔ merge" in stdout
        assert "galatasaray_tr" in stdout

    def test_identity_merge_requires_reason(self) -> None:
        """Merge command fails without REASON."""
        code, stdout, stderr = self._run_make(
            "identity.merge",
            {
                "STABLE_IDS": "galatasaray_tr,gala_tr",
                "REASON": "",
            },
        )
        assert code != 0
        assert "reason is required" in stderr or "reason is required" in stdout

    def test_identity_merge_requires_at_least_two_ids(self) -> None:
        """Merge command fails with fewer than 2 stable_ids."""
        code, stdout, stderr = self._run_make(
            "identity.merge",
            {
                "STABLE_IDS": "single_id",
                "REASON": "test",
            },
        )
        assert code != 0
        assert "at least 2" in stderr or "at least 2" in stdout

    def test_identity_merge_emits_audit_event(self) -> None:
        """Merge command emits audit event with all required fields."""
        code, stdout, stderr = self._run_make(
            "identity.merge",
            {
                "STABLE_IDS": "a,b",
                "REASON": "test merge",
            },
        )
        assert code == 0
        assert "event:" in stdout
        
        # Extract event JSON
        event_line = [line for line in stdout.split('\n') if 'event:' in line]
        assert len(event_line) > 0
        
        # Parse event dict from output
        event_str = event_line[0].replace("event: ", "")
        event = eval(event_str)  # Safe here since we control the format
        
        assert event["decision"] == "merge"
        assert event["actor"] == "operator"
        assert event["similarity"] == 1.0
        assert "timestamp" in event
        assert "reason" in event

    def test_identity_split_succeeds(self) -> None:
        """Split command succeeds with valid inputs."""
        code, stdout, stderr = self._run_make(
            "identity.split",
            {
                "STABLE_ID": "merged_id",
                "INTO": "real_madrid_es,real_madrid_uy",
                "REASON": "incorrectly merged",
            },
        )
        assert code == 0
        assert "✔ split" in stdout
        assert "merged_id" in stdout

    def test_identity_split_requires_reason(self) -> None:
        """Split command fails without REASON."""
        code, stdout, stderr = self._run_make(
            "identity.split",
            {
                "STABLE_ID": "merged_id",
                "INTO": "a,b",
                "REASON": "",
            },
        )
        assert code != 0
        assert "reason is required" in stderr or "reason is required" in stdout

    def test_identity_split_requires_at_least_two_new_ids(self) -> None:
        """Split command fails with fewer than 2 new stable_ids."""
        code, stdout, stderr = self._run_make(
            "identity.split",
            {
                "STABLE_ID": "x",
                "INTO": "y",
                "REASON": "test",
            },
        )
        assert code != 0
        assert "at least 2" in stderr or "at least 2" in stdout

    def test_identity_split_emits_audit_event(self) -> None:
        """Split command emits audit event with all required fields."""
        code, stdout, stderr = self._run_make(
            "identity.split",
            {
                "STABLE_ID": "merged",
                "INTO": "a,b",
                "REASON": "test split",
            },
        )
        assert code == 0
        assert "event:" in stdout
        
        # Extract event JSON
        event_line = [line for line in stdout.split('\n') if 'event:' in line]
        assert len(event_line) > 0
        
        # Parse event dict from output
        event_str = event_line[0].replace("event: ", "")
        event = eval(event_str)  # Safe here since we control the format
        
        assert event["decision"] == "split"
        assert event["actor"] == "operator"
        assert event["similarity"] == 0.0
        assert "timestamp" in event
        assert "reason" in event


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
