"""Phase 8 §8.13.5 — pause/resume idempotency matrix unit tests.

Covers the shared :class:`PauseState` helper used by every
``maint.*`` reactor that subscribes to ``maint_pause`` /
``maint_resume`` so the operator-facing ack matrix is consistent
across the maintenance plane.
"""

from __future__ import annotations

from swarm.agents.maint._pause_state import PauseState


def test_pause_from_running_returns_paused() -> None:
    st = PauseState()
    res = st.apply_pause(ttl_s=300, now_ns=1_000_000_000)
    assert res.accepted is True
    assert res.reason == "paused"
    assert st.paused is True
    assert st.deadline_ns == 1_000_000_000 + 300 * 1_000_000_000


def test_pause_from_paused_is_idempotent() -> None:
    # Existing deadline at 5_000_000_000_000 (5000s after epoch)
    st = PauseState(paused=True, deadline_ns=5_000_000_000_000)
    # Re-pause with ttl=10s from now=1s would land at 11s — much
    # earlier than the existing 5000s deadline; must NOT shrink.
    res = st.apply_pause(ttl_s=10, now_ns=1_000_000_000)
    assert res.accepted is True
    assert res.reason == "already_paused"
    assert st.deadline_ns == 5_000_000_000_000  # NOT shrunk


def test_pause_widens_deadline_on_longer_ttl() -> None:
    # §8.13.5 bullet 3: a longer TTL widens the deadline and returns 'ttl_refreshed'.
    st = PauseState(paused=True, deadline_ns=1_500_000_000)
    res = st.apply_pause(ttl_s=10, now_ns=1_000_000_000)  # would extend
    assert res.reason == "ttl_refreshed"
    assert st.deadline_ns == 1_000_000_000 + 10 * 1_000_000_000


def test_pause_rejected_when_self_isolated() -> None:
    st = PauseState(self_isolated=True)
    res = st.apply_pause(ttl_s=300, now_ns=1_000_000_000)
    assert res.accepted is False
    assert res.reason == "requires_resume_first"
    assert st.paused is False  # state unchanged


def test_resume_from_paused_returns_resumed() -> None:
    st = PauseState(paused=True, deadline_ns=2_000_000_000)
    res = st.apply_resume()
    assert res.accepted is True
    assert res.reason == "resumed"
    assert st.paused is False
    assert st.deadline_ns is None


def test_resume_from_running_is_idempotent() -> None:
    # §8.13.5 matrix: running + maint-resume → already_running (no-op)
    st = PauseState()
    res = st.apply_resume()
    assert res.accepted is True
    assert res.reason == "already_running"


def test_resume_clears_self_isolation() -> None:
    st = PauseState(self_isolated=True)
    res = st.apply_resume()
    assert res.accepted is True
    assert res.reason == "resumed_from_isolation"
    assert st.self_isolated is False


def test_expire_if_due_auto_resumes() -> None:
    st = PauseState(paused=True, deadline_ns=1_000)
    transitioned = st.expire_if_due(now_ns=2_000)
    assert transitioned is True
    assert st.paused is False
    assert st.deadline_ns is None


def test_expire_if_due_no_op_before_deadline() -> None:
    st = PauseState(paused=True, deadline_ns=10_000)
    assert st.expire_if_due(now_ns=5_000) is False
    assert st.paused is True


def test_expire_if_due_does_not_clear_self_isolation() -> None:
    st = PauseState(paused=True, self_isolated=True, deadline_ns=1_000)
    st.expire_if_due(now_ns=2_000)
    # paused TTL expired but self_isolated remains
    assert st.self_isolated is True
