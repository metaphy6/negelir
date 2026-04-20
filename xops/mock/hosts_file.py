"""Cross-platform /etc/hosts writer for the Phase 2 mock stack.

Idempotent. Marker-block based so re-running install/uninstall is safe.
On Windows the canonical path is ``%SystemRoot%\\System32\\drivers\\etc\\hosts``;
elsewhere it's ``/etc/hosts``.

Layout written into the hosts file::

    # >>> negelir-mock-stack >>>
    127.0.0.1   mackolik.local nesine.local tff.local openfootball.local
    # <<< negelir-mock-stack <<<

The block is removed cleanly by ``uninstall``. Editing what's *between*
the markers is allowed and preserved as long as the markers stay intact
— ``install`` only rewrites our managed line.
"""

from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

BEGIN_MARKER = "# >>> negelir-mock-stack >>>"
END_MARKER = "# <<< negelir-mock-stack <<<"

DEFAULT_HOSTS = (
    "mackolik.local",
    "nesine.local",
    "tff.local",
    "openfootball.local",
)


class HostsError(RuntimeError):
    pass


def default_hosts_path() -> Path:
    if platform.system().lower().startswith("win"):
        return Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "drivers" / "etc" / "hosts"
    return Path("/etc/hosts")


def _read(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _strip_block(content: str) -> str:
    """Remove an existing managed block (with markers). Idempotent."""
    lines = content.splitlines()
    out: List[str] = []
    inside = False
    for line in lines:
        if line.strip() == BEGIN_MARKER:
            inside = True
            continue
        if inside and line.strip() == END_MARKER:
            inside = False
            continue
        if inside:
            continue
        out.append(line)
    text = "\n".join(out)
    # Collapse any trailing blank lines we just produced.
    while text.endswith("\n\n"):
        text = text[:-1]
    return text


def _build_block(hosts: Sequence[str], ip: str = "127.0.0.1") -> str:
    line = f"{ip}\t" + " ".join(hosts)
    return f"{BEGIN_MARKER}\n{line}\n{END_MARKER}\n"


# ── Public API ────────────────────────────────────────────────


def render(content: str, hosts: Sequence[str] = DEFAULT_HOSTS, ip: str = "127.0.0.1") -> str:
    """Pure: produce the new hosts-file content with our managed block."""
    stripped = _strip_block(content)
    if stripped and not stripped.endswith("\n"):
        stripped += "\n"
    return stripped + _build_block(hosts, ip=ip)


def render_uninstall(content: str) -> str:
    stripped = _strip_block(content)
    if stripped and not stripped.endswith("\n"):
        stripped += "\n"
    return stripped


def block_present(content: str) -> bool:
    return BEGIN_MARKER in content and END_MARKER in content


def install(
    *,
    path: Optional[Path] = None,
    hosts: Sequence[str] = DEFAULT_HOSTS,
    ip: str = "127.0.0.1",
) -> Tuple[Path, bool]:
    """Write the managed block. Returns (path, changed)."""
    p = path or default_hosts_path()
    current = _read(p)
    new = render(current, hosts=hosts, ip=ip)
    if new == current:
        return p, False
    try:
        p.write_text(new, encoding="utf-8")
    except PermissionError as exc:
        raise HostsError(
            f"cannot write {p}: permission denied. "
            f"On Linux/macOS run with sudo; on Windows use an elevated shell."
        ) from exc
    return p, True


def uninstall(*, path: Optional[Path] = None) -> Tuple[Path, bool]:
    """Remove the managed block. Returns (path, changed)."""
    p = path or default_hosts_path()
    current = _read(p)
    new = render_uninstall(current)
    if new == current:
        return p, False
    try:
        p.write_text(new, encoding="utf-8")
    except PermissionError as exc:
        raise HostsError(
            f"cannot write {p}: permission denied. "
            f"On Linux/macOS run with sudo; on Windows use an elevated shell."
        ) from exc
    return p, True


def status(*, path: Optional[Path] = None) -> dict:
    p = path or default_hosts_path()
    content = _read(p)
    block_hosts: List[str] = []
    if block_present(content):
        # Extract the managed line(s) and pull host tokens.
        in_block = False
        for line in content.splitlines():
            s = line.strip()
            if s == BEGIN_MARKER:
                in_block = True
                continue
            if s == END_MARKER:
                in_block = False
                continue
            if in_block and s and not s.startswith("#"):
                # Format: "<ip>\t<host1> <host2> ..."
                parts = s.split()
                if len(parts) >= 2:
                    block_hosts.extend(parts[1:])
    return {
        "path": str(p),
        "exists": p.exists(),
        "installed": block_present(content),
        "block_present": block_present(content),
        "hosts": block_hosts,
    }
