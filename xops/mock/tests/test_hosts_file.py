"""Tests for the cross-platform /etc/hosts writer."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from xops.mock import hosts_file as hf


# ── Pure render functions ─────────────────────────────────────


def test_render_appends_block_on_empty_input() -> None:
    out = hf.render("", hosts=("a.local", "b.local"), ip="127.0.0.1")
    assert hf.BEGIN_MARKER in out
    assert hf.END_MARKER in out
    assert "127.0.0.1\ta.local b.local" in out


def test_render_idempotent() -> None:
    once = hf.render("", hosts=hf.DEFAULT_HOSTS)
    twice = hf.render(once, hosts=hf.DEFAULT_HOSTS)
    assert once == twice
    assert once.count(hf.BEGIN_MARKER) == 1


def test_render_replaces_old_block_with_new_hosts() -> None:
    one = hf.render("", hosts=("x.local",))
    two = hf.render(one, hosts=("y.local",))
    assert "x.local" not in two
    assert "y.local" in two
    assert two.count(hf.BEGIN_MARKER) == 1


def test_render_preserves_unrelated_content() -> None:
    pre = "127.0.0.1 localhost\n# user comment\n"
    out = hf.render(pre, hosts=("z.local",))
    assert pre in out
    assert "z.local" in out


def test_render_uninstall_removes_block_only() -> None:
    pre = "127.0.0.1 localhost\n"
    with_block = hf.render(pre, hosts=("foo.local",))
    cleaned = hf.render_uninstall(with_block)
    assert hf.BEGIN_MARKER not in cleaned
    assert "foo.local" not in cleaned
    assert "127.0.0.1 localhost" in cleaned


def test_render_uninstall_noop_when_no_block() -> None:
    src = "127.0.0.1 localhost\n"
    assert hf.render_uninstall(src) == src


def test_block_present_detection() -> None:
    assert not hf.block_present("foo")
    assert hf.block_present(hf.render("", hosts=("a.local",)))


# ── File I/O ──────────────────────────────────────────────────


@pytest.fixture
def tmp_hosts(tmp_path: Path) -> Path:
    p = tmp_path / "hosts"
    p.write_text("127.0.0.1 localhost\n", encoding="utf-8")
    return p


def test_install_writes_block(tmp_hosts: Path) -> None:
    path, changed = hf.install(path=tmp_hosts, hosts=("a.local",))
    assert path == tmp_hosts
    assert changed is True
    assert "a.local" in tmp_hosts.read_text()


def test_install_idempotent(tmp_hosts: Path) -> None:
    hf.install(path=tmp_hosts, hosts=("a.local",))
    _, changed = hf.install(path=tmp_hosts, hosts=("a.local",))
    assert changed is False


def test_install_then_uninstall_round_trip(tmp_hosts: Path) -> None:
    original = tmp_hosts.read_text()
    hf.install(path=tmp_hosts, hosts=("a.local", "b.local"))
    hf.uninstall(path=tmp_hosts)
    assert tmp_hosts.read_text() == original


def test_uninstall_idempotent(tmp_hosts: Path) -> None:
    _, changed_first = hf.uninstall(path=tmp_hosts)
    _, changed_second = hf.uninstall(path=tmp_hosts)
    assert changed_first is False  # nothing to remove
    assert changed_second is False


def test_status_reflects_install_state(tmp_hosts: Path) -> None:
    s_before = hf.status(path=tmp_hosts)
    assert s_before["installed"] is False
    hf.install(path=tmp_hosts, hosts=("x.local",))
    s_after = hf.status(path=tmp_hosts)
    assert s_after["installed"] is True
    assert "x.local" in s_after["hosts"]


def test_custom_ip_used(tmp_hosts: Path) -> None:
    hf.install(path=tmp_hosts, hosts=("z.local",), ip="10.0.0.1")
    assert "10.0.0.1\tz.local" in tmp_hosts.read_text()


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX-only chmod test")
@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root bypasses POSIX read-only file mode; chmod 0o400 won't trigger PermissionError",
)
def test_install_wraps_permission_error(tmp_hosts: Path) -> None:
    tmp_hosts.chmod(0o400)  # read-only
    try:
        with pytest.raises(hf.HostsError) as exc:
            hf.install(path=tmp_hosts, hosts=("a.local",))
        assert "sudo" in str(exc.value).lower() or "admin" in str(exc.value).lower()
    finally:
        tmp_hosts.chmod(0o600)


def test_default_hosts_path_is_platform_appropriate() -> None:
    p = hf.default_hosts_path()
    if sys.platform.startswith("win"):
        assert "drivers" in str(p).lower()
    else:
        assert str(p) == "/etc/hosts"
