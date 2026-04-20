#!/usr/bin/env python3
"""`make hosts.*` — manage /etc/hosts entries for the Phase 2 mock stack.

Scaffolded today. Real install/uninstall lands in Phase 2.3 and must be
idempotent + cross-platform (Windows = ``%SystemRoot%\\System32\\drivers\\etc\\hosts``).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from xops.makefile._common import dispatch, info, ok, sudo_run, warn  # noqa: E402

MOCK_HOSTS = (
    "mackolik.local",
    "nesine.local",
    "tff.local",
    "openfootball.local",
)


def cmd_install(_argv: List[str]) -> int:
    from xops.mock import hosts_file

    try:
        path, changed = hosts_file.install(hosts=MOCK_HOSTS)
    except hosts_file.HostsError:
        # Permission denied — re-render the file and pipe through `sudo tee`.
        path = hosts_file.default_hosts_path()
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        new = hosts_file.render(current, hosts=MOCK_HOSTS)
        if new == current:
            info(f"{path} already up to date")
            return 0
        try:
            sudo_run(
                ["tee", str(path)],
                reason=f"writing {path}",
                stdin=new,
            )
        except (RuntimeError, FileNotFoundError) as exc:
            warn(f"could not elevate to write {path}: {exc}")
            return 1
        ok(f"updated {path} (via sudo)")
        return 0
    if changed:
        ok(f"updated {path}")
    else:
        info(f"{path} already up to date")
    return 0


def cmd_uninstall(_argv: List[str]) -> int:
    from xops.mock import hosts_file

    try:
        path, changed = hosts_file.uninstall()
    except hosts_file.HostsError:
        path = hosts_file.default_hosts_path()
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        new = hosts_file.render_uninstall(current)
        if new == current:
            info(f"{path} had nothing to remove")
            return 0
        try:
            sudo_run(
                ["tee", str(path)],
                reason=f"writing {path}",
                stdin=new,
            )
        except (RuntimeError, FileNotFoundError) as exc:
            warn(f"could not elevate to write {path}: {exc}")
            return 1
        ok(f"cleaned {path} (via sudo)")
        return 0
    info(f"{path} {'cleaned' if changed else 'had nothing to remove'}")
    return 0


def cmd_status(_argv: List[str]) -> int:
    from xops.mock import hosts_file

    s = hosts_file.status()
    info(f"hosts file: {s['path']} (exists={s['exists']}, installed={s['installed']})")
    if s["hosts"]:
        for h in s["hosts"]:
            print(f"  - {h}")
    return 0


def cmd_show(_argv: List[str]) -> int:
    info("Mock hostnames managed by this stack:")
    for host in MOCK_HOSTS:
        print(f"  127.0.0.1  {host}")
    return 0


COMMANDS = {
    "install": cmd_install,
    "uninstall": cmd_uninstall,
    "status": cmd_status,
    "show": cmd_show,
}


def main(argv: List[str]) -> int:
    return dispatch(argv, COMMANDS, script_name="hosts.py")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
