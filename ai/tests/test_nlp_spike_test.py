"""Test the new Phase 10 §10.23.10 NLP spike rehearsal target.

This verifies the Make target exists and that the command dispatches the
expected rehearsal sequence without performing real latency work.
"""

from __future__ import annotations

import subprocess
from unittest.mock import patch

from xops.makefile.nlp import cmd_nlp_spike_test


def test_nlp_spike_test_target_exists() -> None:
    result = subprocess.run(
        ["make", "help"],
        cwd=".",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "nlp.spike-test" in result.stdout


def test_nlp_spike_test_invokes_three_rehearsals() -> None:
    calls: list[str] = []

    def fake_bench(argv: list[str]) -> int:
        calls.append("bench")
        return 0

    def fake_entity(argv: list[str]) -> int:
        calls.append("entity")
        return 0

    with patch("xops.makefile.nlp.cmd_nlp_bench", fake_bench), patch(
        "xops.makefile.nlp.cmd_nlp_entity_bench", fake_entity
    ):
        assert cmd_nlp_spike_test([]) == 0

    assert calls == [
        "bench",
        "entity",
        "bench",
        "entity",
        "bench",
        "entity",
    ]
