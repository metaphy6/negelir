"""Phase 8.9 DoD — Decision window post-restart proof.

Bullet (binding):
  Restart `maint.scaler.v1` mid-window; assert the post-restart
  `pod_instance_id` differs from the pre-restart one and the
  post-restart `scale_decision` events do not collide with pre-restart
  ledger entries on `(agent, decision_window_id)`.

The mechanism:
  `_window_id()` = `"<pod_instance_id>:<window_anchor_ns>"`.
  A new `MaintScaler()` generates a fresh `pod_instance_id` via
  `secrets.token_hex(4)` at __init__ time, so even when the monotonic
  window anchor happens to be the same (both instances are mid-window),
  the resulting `decision_window_id` string is different, guaranteeing
  no ledger collision on `(agent, decision_window_id)`.
"""
from __future__ import annotations

from swarm.agents.maint.scaler import MaintScaler
from swarm.sdk.leader import SingleProcessLeader


def _high_signal(target: str) -> dict[str, dict[str, float]]:
    return {target: {"queue_depth": 999.0, "in_flight": 0.0, "head_age_s": 0.0}}


def _frozen_clock(ns: int):
    """Return a clock callable that always returns `ns` (mid-window freeze)."""
    def clock() -> int:
        return ns
    return clock


def test_post_restart_pod_instance_id_differs() -> None:
    """Two distinct MaintScaler instances always carry different _pod_instance_id.

    Adversarial: even if a restart loop is tight (boot-crash-boot within
    the same second), `secrets.token_hex(4)` produces a fresh 4-byte prefix
    so collision probability is < 1/2^32 per restart pair.
    """
    a1 = MaintScaler(leader=SingleProcessLeader(name="maint.scaler.v1"))
    a2 = MaintScaler(leader=SingleProcessLeader(name="maint.scaler.v1"))
    assert a1._pod_instance_id != a2._pod_instance_id


def test_post_restart_decision_window_ids_do_not_collide() -> None:
    """Post-restart scale_decision events carry decision_window_ids that
    do not appear in the pre-restart set, even when both instances tick
    inside the same clock window.

    Setup: pin both instances to the same nanosecond via a frozen clock so
    the window_anchor_ns computation returns an identical value.  This is the
    worst-case restart scenario — the new process starts within the same
    decision window as the old one.

    Expected: `_window_id()` = "<pod_instance_id>:<window_anchor_ns>".
    Same anchor, different prefix → disjoint decision_window_id sets.
    The Postgres audit ledger dedup key `(agent, decision_window_id)` then
    has no chance of a collision between pre- and post-restart rows.
    """
    fixed_ns = 1_000_000_000_000  # 1000 s monotonic — stable mid-window point
    clock = _frozen_clock(fixed_ns)
    target = "predictor.elo"

    # ── Pre-restart instance ──────────────────────────────────────
    agent_pre = MaintScaler(
        leader=SingleProcessLeader(name="maint.scaler.v1"),
        clock_ns=clock,
    )
    pre_msgs = agent_pre.tick(_high_signal(target))
    pre_decisions = [m for m in pre_msgs if m.payload.get("kind") == "scale_decision"]
    assert pre_decisions, "pre-restart agent must emit at least one scale_decision"
    pre_window_ids = {m.payload["decision_window_id"] for m in pre_decisions}

    # ── Post-restart instance: new object, identical clock window ─
    agent_post = MaintScaler(
        leader=SingleProcessLeader(name="maint.scaler.v1"),
        clock_ns=clock,
    )
    post_msgs = agent_post.tick(_high_signal(target))
    post_decisions = [m for m in post_msgs if m.payload.get("kind") == "scale_decision"]
    assert post_decisions, "post-restart agent must emit at least one scale_decision"
    post_window_ids = {m.payload["decision_window_id"] for m in post_decisions}

    # Core assertion: new instance carries a different pod_instance_id.
    assert agent_pre._pod_instance_id != agent_post._pod_instance_id, (
        "pod_instance_id must differ between pre- and post-restart instances"
    )

    # Derived assertion: decision_window_id sets are disjoint so the audit
    # ledger unique constraint on (agent, decision_window_id) is never
    # triggered by a restart race.
    collision = pre_window_ids & post_window_ids
    assert not collision, (
        f"decision_window_id collision detected between pre- and post-restart "
        f"agents: {collision}"
    )
