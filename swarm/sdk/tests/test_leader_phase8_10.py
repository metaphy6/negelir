"""Phase 8 §8.10 — leader-election Protocol surface tests.

Covers the unticked ROADMAP §8.10 bullets that are landable
without the Phase 14 K8s deploy:

* :class:`KubernetesLeader` is a stub that **refuses loud**
  (NotImplementedError) — preventing a misconfigured environment
  from quietly running with an "is_leader = always False" no-op.
* The ``§8.10 leader-required`` set matches the
  ``SINGLE_INSTANCE_AGENTS`` registered maint.* names exactly.
  Orphans on either side fail CI (binding boundary test).
* :class:`SingleProcessLeader` round-trip: shed → not leader,
  reacquire → leader (the test-only path that lets §8.10 (a)
  proof-test scaffolding flip leadership without a K8s lease).
"""
from __future__ import annotations

import pytest

from swarm.bootstrap import SINGLE_INSTANCE_AGENTS
from swarm.sdk.leader import KubernetesLeader, Leader, SingleProcessLeader

# ── §8.10 binding leader-required set ──────────────────────────────
# These five maint.* agents MUST run replicas: 1 with leader-election
# (ROADMAP §8.10): scaler, backup, dlq, schema, sec.
LEADER_REQUIRED_MAINT_AGENTS: frozenset[str] = frozenset({
    "maint.scaler.v1",
    "maint.backup.v1",
    "maint.dlq.v1",
    "maint.schema.v1",
    "maint.sec.v1",
})


def test_leader_required_set_matches_single_instance_maint_names():
    """Boundary: every leader-required name is single-instance, and
    every maint.* single-instance name is leader-required. Orphans
    on either side fail CI."""
    maint_singles = frozenset(
        n for n in SINGLE_INSTANCE_AGENTS if n.startswith("maint.")
    )
    assert maint_singles == LEADER_REQUIRED_MAINT_AGENTS, (
        "drift between SINGLE_INSTANCE_AGENTS (maint.*) and "
        "ROADMAP §8.10 leader-required set\n"
        f"  bootstrap-only: {sorted(maint_singles - LEADER_REQUIRED_MAINT_AGENTS)}\n"
        f"  roadmap-only:   {sorted(LEADER_REQUIRED_MAINT_AGENTS - maint_singles)}"
    )


def test_kubernetes_leader_refuses_loud_until_phase_14():
    """§8.10 binding: a misconfigured `cfg.maint_runtime=k8s` that
    bypassed bootstrap selector MUST refuse — not silently no-op."""
    with pytest.raises(NotImplementedError, match="Phase 14"):
        KubernetesLeader(name="maint.scaler.v1")


def test_single_process_leader_default_is_leader():
    led = SingleProcessLeader(name="maint.backup.v1")
    # Duck-typed Protocol conformance — Leader is not @runtime_checkable.
    assert hasattr(led, "is_leader") and hasattr(led, "shed") and hasattr(led, "name")
    assert led.is_leader() is True


def test_single_process_leader_shed_drops_leadership():
    led = SingleProcessLeader(name="maint.dlq.v1")
    led.shed()
    assert led.is_leader() is False


def test_single_process_leader_reacquire_restores_leadership():
    """Test-only path used by §8.10 (a) proof tests — flip
    leadership without a K8s lease."""
    led = SingleProcessLeader(name="maint.scaler.v1")
    led.shed()
    assert led.is_leader() is False
    led.reacquire()
    assert led.is_leader() is True
