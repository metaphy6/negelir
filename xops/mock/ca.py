"""Real CA + leaf certificate generation for the Phase 2 mock stack.

Wraps ``openssl`` (assumed present in the agent images and on dev hosts).
All paths are relative to ``infra/mock/``. Idempotent: re-running on an
existing CA does **nothing**; re-running with ``--force`` regenerates.

Stdlib only — we shell out to openssl rather than depending on
``cryptography``.

Layout produced::

    infra/mock/ca/
        root.key                  (CA private key, mode 0600)
        root.crt                  (CA cert, 10 years)
        serial                    (next leaf serial number)
    infra/mock/certs/<host>/
        leaf.key                  (mode 0600)
        leaf.crt                  (signed by root, 825 days, SAN=<host>)
        chain.pem                 (leaf || root, for nginx ssl_certificate)
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Iterable, List, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
MOCK_ROOT = REPO_ROOT / "infra" / "mock"
CA_DIR = MOCK_ROOT / "ca"
CERTS_DIR = MOCK_ROOT / "certs"

CA_KEY = CA_DIR / "root.key"
CA_CRT = CA_DIR / "root.crt"
CA_SERIAL = CA_DIR / "serial"

CA_DAYS = 3650
LEAF_DAYS = 825
KEY_BITS = 2048
CA_SUBJ = "/C=TR/ST=Dev/L=Local/O=Negelir/OU=Mock/CN=Negelir Mock Root CA"


class CAError(RuntimeError):
    pass


# ── shell helpers ─────────────────────────────────────────────


def _which_openssl() -> str:
    binary = shutil.which("openssl")
    if not binary:
        raise CAError(
            "openssl not found on PATH. Install it (apt: openssl, brew: openssl@3, "
            "Windows: choco install openssl) and retry."
        )
    return binary


def _run(cmd: Sequence[str], *, cwd: Path) -> None:
    proc = subprocess.run(
        list(cmd),
        cwd=str(cwd),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        raise CAError(
            f"openssl failed (exit {proc.returncode}): {' '.join(cmd)}\n"
            f"stderr:\n{proc.stderr}"
        )


def _chmod_private(path: Path) -> None:
    """Tighten perms on a private key. No-op on Windows."""
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except (OSError, NotImplementedError):
        pass


# ── CA ────────────────────────────────────────────────────────


def ca_exists() -> bool:
    return CA_KEY.exists() and CA_CRT.exists()


def init_ca(*, force: bool = False, root: Path = MOCK_ROOT) -> None:
    """Create the root CA. Idempotent unless force=True."""
    openssl = _which_openssl()
    ca_dir = root / "ca"
    ca_dir.mkdir(parents=True, exist_ok=True)
    key = ca_dir / "root.key"
    crt = ca_dir / "root.crt"
    serial = ca_dir / "serial"

    if key.exists() and crt.exists() and not force:
        return  # idempotent

    if force:
        for p in (key, crt, serial):
            if p.exists():
                p.unlink()

    _run([openssl, "genrsa", "-out", str(key), str(KEY_BITS)], cwd=ca_dir)
    _chmod_private(key)
    _run(
        [
            openssl, "req", "-x509", "-new", "-nodes",
            "-key", str(key),
            "-sha256", "-days", str(CA_DAYS),
            "-subj", CA_SUBJ,
            "-out", str(crt),
        ],
        cwd=ca_dir,
    )
    serial.write_text("1000\n", encoding="utf-8")


def _next_serial(root: Path) -> str:
    serial_file = root / "ca" / "serial"
    current = int(serial_file.read_text(encoding="utf-8").strip())
    serial_file.write_text(f"{current + 1}\n", encoding="utf-8")
    return f"{current:08X}"


# ── Leaf certs ────────────────────────────────────────────────


def issue_leaf(host: str, *, force: bool = False, root: Path = MOCK_ROOT) -> Path:
    """Generate a leaf cert for ``host`` signed by the root CA.

    Returns the cert directory. Idempotent unless force=True.
    """
    if not host or any(c.isspace() for c in host):
        raise CAError(f"invalid host: {host!r}")

    openssl = _which_openssl()
    ca_dir = root / "ca"
    if not (ca_dir / "root.key").exists():
        raise CAError("root CA missing — run init_ca() first")

    leaf_dir = root / "certs" / host
    leaf_dir.mkdir(parents=True, exist_ok=True)
    key = leaf_dir / "leaf.key"
    csr = leaf_dir / "leaf.csr"
    crt = leaf_dir / "leaf.crt"
    chain = leaf_dir / "chain.pem"
    extfile = leaf_dir / "leaf.ext"

    if crt.exists() and key.exists() and chain.exists() and not force:
        return leaf_dir

    extfile.write_text(
        "authorityKeyIdentifier=keyid,issuer\n"
        "basicConstraints=CA:FALSE\n"
        "keyUsage = digitalSignature, keyEncipherment\n"
        "extendedKeyUsage = serverAuth\n"
        f"subjectAltName = DNS:{host}\n",
        encoding="utf-8",
    )

    _run([openssl, "genrsa", "-out", str(key), str(KEY_BITS)], cwd=leaf_dir)
    _chmod_private(key)
    _run(
        [
            openssl, "req", "-new", "-key", str(key),
            "-subj", f"/C=TR/ST=Dev/L=Local/O=Negelir/OU=Mock/CN={host}",
            "-out", str(csr),
        ],
        cwd=leaf_dir,
    )
    serial_hex = _next_serial(root)
    _run(
        [
            openssl, "x509", "-req",
            "-in", str(csr),
            "-CA", str(ca_dir / "root.crt"),
            "-CAkey", str(ca_dir / "root.key"),
            "-set_serial", f"0x{serial_hex}",
            "-days", str(LEAF_DAYS),
            "-sha256",
            "-extfile", str(extfile),
            "-out", str(crt),
        ],
        cwd=leaf_dir,
    )
    chain.write_text(
        crt.read_text(encoding="utf-8") + (ca_dir / "root.crt").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    csr.unlink(missing_ok=True)
    extfile.unlink(missing_ok=True)
    return leaf_dir


def issue_all(hosts: Iterable[str], *, force: bool = False, root: Path = MOCK_ROOT) -> List[Path]:
    return [issue_leaf(h, force=force, root=root) for h in hosts]


# ── Verification (used by tests) ──────────────────────────────


def verify_leaf(host: str, *, root: Path = MOCK_ROOT) -> bool:
    """Return True iff the leaf for ``host`` chains to the root CA."""
    openssl = _which_openssl()
    ca_dir = root / "ca"
    leaf = root / "certs" / host / "leaf.crt"
    proc = subprocess.run(
        [openssl, "verify", "-CAfile", str(ca_dir / "root.crt"), str(leaf)],
        cwd=str(leaf.parent),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return proc.returncode == 0
