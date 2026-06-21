"""Phase 8.9 surface-coverage proof for the first DoD bullet.

This test pins the minimal contract claimed by the first checklist row:

* all Phase 8 maint reactors are implemented and expose the expected
  stable v1 agent ids,
* the source watcher runs on the shared Swarm SDK ``Agent`` base
  class,
* ops console path exists at ``xops/opsctl``.
"""
from __future__ import annotations

from pathlib import Path

from swarm.agents.maint.backup import MaintBackupAgent
from swarm.agents.maint.dlq import MaintDlqSupervisor
from swarm.agents.maint.scaler import MaintScaler
from swarm.agents.maint.schema import MaintSchemaSentinel
from swarm.agents.maint.sec import MaintSecAgent
from swarm.sdk.agent import Agent
from swarm.source_watcher.agent import SourceWatcherAgent


def test_phase8_9_agent_surface_coverage_is_present() -> None:
    assert MaintScaler.name == "maint.scaler.v1"
    assert MaintBackupAgent.name == "maint.backup.v1"
    assert MaintDlqSupervisor.name == "maint.dlq.v1"
    assert MaintSchemaSentinel.name == "maint.schema.v1"
    assert MaintSecAgent.name == "maint.sec.v1"
    assert SourceWatcherAgent.name == "source.watcher.v1"


def test_phase8_9_source_watcher_uses_swarm_sdk_agent_base() -> None:
    assert Agent in SourceWatcherAgent.__mro__[1:]


def test_phase8_9_ops_console_path_exists() -> None:
    repo_root = Path(__file__).resolve().parents[5]
    assert (repo_root / "xops" / "opsctl").is_dir()
