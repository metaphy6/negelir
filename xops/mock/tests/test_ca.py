"""Strict tests for the openssl-backed CA + leaf cert generator."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from xops.mock import ca

OPENSSL_AVAILABLE = shutil.which("openssl") is not None
needs_openssl = pytest.mark.skipif(not OPENSSL_AVAILABLE, reason="openssl not on PATH")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "mock-root"


@needs_openssl
def test_init_ca_creates_root_files(root: Path) -> None:
    ca.init_ca(root=root)
    assert (root / "ca" / "root.key").exists()
    assert (root / "ca" / "root.crt").exists()
    assert (root / "ca" / "serial").read_text().strip() == "1000"


@needs_openssl
def test_init_ca_is_idempotent(root: Path) -> None:
    ca.init_ca(root=root)
    crt_first = (root / "ca" / "root.crt").read_bytes()
    ca.init_ca(root=root)  # no force → no rewrite
    crt_second = (root / "ca" / "root.crt").read_bytes()
    assert crt_first == crt_second, "CA cert should not be regenerated"


@needs_openssl
def test_init_ca_force_regenerates(root: Path) -> None:
    ca.init_ca(root=root)
    crt_first = (root / "ca" / "root.crt").read_bytes()
    ca.init_ca(root=root, force=True)
    crt_second = (root / "ca" / "root.crt").read_bytes()
    assert crt_first != crt_second


@needs_openssl
def test_issue_leaf_produces_three_files(root: Path) -> None:
    ca.init_ca(root=root)
    ca.issue_leaf("mackolik.local", root=root)
    leaf_dir = root / "certs" / "mackolik.local"
    assert (leaf_dir / "leaf.key").exists()
    assert (leaf_dir / "leaf.crt").exists()
    assert (leaf_dir / "chain.pem").exists()


@needs_openssl
def test_issue_leaf_chain_is_leaf_then_root(root: Path) -> None:
    ca.init_ca(root=root)
    ca.issue_leaf("nesine.local", root=root)
    leaf = (root / "certs" / "nesine.local" / "leaf.crt").read_text()
    chain = (root / "certs" / "nesine.local" / "chain.pem").read_text()
    assert chain.startswith(leaf), "chain.pem must start with the leaf"
    assert chain.count("BEGIN CERTIFICATE") == 2


@needs_openssl
def test_issue_leaf_san_contains_host(root: Path) -> None:
    ca.init_ca(root=root)
    ca.issue_leaf("tff.local", root=root)
    crt = root / "certs" / "tff.local" / "leaf.crt"
    out = subprocess.check_output(
        ["openssl", "x509", "-in", str(crt), "-noout", "-text"],
        text=True,
    )
    assert "DNS:tff.local" in out


@needs_openssl
def test_serial_increments_per_leaf(root: Path) -> None:
    ca.init_ca(root=root)
    ca.issue_leaf("a.local", root=root)
    s_after_first = int((root / "ca" / "serial").read_text().strip(), 16)
    ca.issue_leaf("b.local", root=root)
    s_after_second = int((root / "ca" / "serial").read_text().strip(), 16)
    assert s_after_second == s_after_first + 1


@needs_openssl
def test_issue_leaf_idempotent(root: Path) -> None:
    ca.init_ca(root=root)
    ca.issue_leaf("openfootball.local", root=root)
    crt_before = (root / "certs" / "openfootball.local" / "leaf.crt").read_bytes()
    ca.issue_leaf("openfootball.local", root=root)
    crt_after = (root / "certs" / "openfootball.local" / "leaf.crt").read_bytes()
    assert crt_before == crt_after


@needs_openssl
def test_verify_leaf_succeeds(root: Path) -> None:
    ca.init_ca(root=root)
    ca.issue_leaf("mackolik.local", root=root)
    assert ca.verify_leaf("mackolik.local", root=root) is True


@needs_openssl
def test_verify_leaf_fails_for_unsigned_blob(root: Path, tmp_path: Path) -> None:
    ca.init_ca(root=root)
    ca.issue_leaf("mackolik.local", root=root)
    # Tamper: write a self-signed-but-different cert into the leaf slot.
    fake_dir = tmp_path / "fake-leaf"
    fake_dir.mkdir()
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(fake_dir / "k.pem"),
            "-out",
            str(fake_dir / "c.pem"),
            "-days",
            "30",
            "-subj",
            "/CN=evil.local",
        ],
        check=True,
        capture_output=True,
    )
    # Replace the legitimate leaf with the unsigned one.
    (root / "certs" / "mackolik.local" / "leaf.crt").write_bytes(
        (fake_dir / "c.pem").read_bytes()
    )
    assert ca.verify_leaf("mackolik.local", root=root) is False


@needs_openssl
def test_issue_all(root: Path) -> None:
    ca.init_ca(root=root)
    hosts = ("a.local", "b.local", "c.local")
    ca.issue_all(hosts, root=root)
    for h in hosts:
        assert (root / "certs" / h / "leaf.crt").exists()
