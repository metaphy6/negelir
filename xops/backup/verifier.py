"""Phase 8 §8.3 — live ``RestoreVerifier`` adapter (subprocess).

This module provides the production driver for the
:class:`swarm.agents.maint.backup.RestoreVerifier` Protocol. It
restores the most-recent encrypted dump (produced by
:class:`xops.backup.executors.LocalPgDumpExecutor`) into an
ephemeral ``postgres:16-alpine`` container, runs the read-only
probes in :mod:`xops.backup.verify` (``verify.sql``), and returns
the per-table row counts the agent compares against the source DB
census.

Doctrine respected:

* **Single-source config (Rule 1).** Image tag, decrypt identity
  file, network, and target ports come from
  ``ai.common.config.cfg``. No ``*-latest`` Docker tags.
* **No silent fallback (Rule 3).** Any subprocess failure raises;
  the agent's state machine downgrades to
  ``backup_completed{outcome=verify_failed}`` and skips prune.
* **Orphan sweep.** ``sweep_orphans()`` lists scratch DBs/containers
  whose name prefix matches the verifier's lease and removes them
  — recovering from a prior crashed verify run.

The class is DI-friendly: tests inject a fake ``runner`` to avoid
spawning Docker.
"""
from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional, Protocol, Sequence

from xops.backup.executors import (
    CHECKSUM_NAME,
    CommandRunner,
    DUMP_DIR_NAME,
    ENCRYPTED_NAME,
    _default_runner,
)


_log = logging.getLogger("xops.backup.verifier")


# Container name prefix; the per-fire-window suffix is appended.
# A scrub of `docker ps -a --filter name=<prefix>` lets sweep_orphans
# recover from a verifier crash mid-restore.
_CONTAINER_PREFIX: str = "negelir-verify-"


@dataclass
class LocalSubprocessVerifier:
    """Restore the latest encrypted dump and run ``verify.sql``.

    The verifier is intentionally heavyweight: it spins a fresh
    ``postgres:16-alpine`` container per fire window, restores the
    dump with ``pg_restore --jobs=N``, then executes
    :file:`xops/backup/verify.sql` with ``psql`` and returns the
    row counts.

    On any subprocess failure, the call returns an empty mapping
    (the Protocol contract for ``verify_failed``) — never raises
    into the agent's state machine, so the ``backup_completed``
    event is always emitted.

    Construction:

        LocalSubprocessVerifier(
            backup_dir=cfg.maint_backup_dir,
            pg_image=cfg.maint_backup_verify_pg_image,
            age_identity_file=cfg.maint_backup_age_identity_file,
            pg_jobs=cfg.maint_backup_pg_jobs,
        )
    """

    backup_dir: str
    pg_image: str = "postgres:16-alpine"
    age_identity_file: str = ""
    pg_jobs: int = 2
    # Internal docker network — kept default so the container is
    # reachable only from the host. Override for compose-network
    # restores.
    docker_network: str = "bridge"
    runner: CommandRunner = field(default=_default_runner)
    docker_binary: Optional[str] = None
    age_binary: Optional[str] = None
    pg_restore_binary: Optional[str] = None
    psql_binary: Optional[str] = None
    # Path to verify.sql; defaults to the sibling file under this pkg.
    verify_sql_path: Optional[str] = None

    def verify(self, *, fire_window_id: str) -> Mapping[str, int]:
        """Restore the dump and return per-table row counts.

        Empty dict means verify failed (the Protocol contract
        ``MaintBackupAgent`` reads as ``verify_failed`` outcome).
        """
        try:
            return self._verify_inner(fire_window_id=fire_window_id)
        except Exception as exc:  # noqa: BLE001 — Protocol contract: empty dict on any failure
            _log.warning(
                "LocalSubprocessVerifier.verify window=%s failed: %s",
                fire_window_id, exc,
            )
            return {}

    def _verify_inner(self, *, fire_window_id: str) -> Mapping[str, int]:
        safe_window = fire_window_id.replace(":", "_").replace("/", "_")
        window_dir = Path(self.backup_dir) / safe_window
        encrypted = window_dir / ENCRYPTED_NAME
        checksum = window_dir / CHECKSUM_NAME
        if not encrypted.is_file():
            raise RuntimeError(f"encrypted dump missing: {encrypted}")
        if not checksum.is_file():
            raise RuntimeError(f"checksum missing: {checksum}")

        # ── Verify checksum (silent-corruption gate, §8.3) ─────────────
        expected = checksum.read_text(encoding="utf-8").split()[0].strip()
        actual = _sha256_file(encrypted)
        if expected.lower() != actual.lower():
            raise RuntimeError(
                f"checksum mismatch: expected={expected[:16]} "
                f"actual={actual[:16]}"
            )

        if not self.age_identity_file or not os.path.isfile(self.age_identity_file):
            raise RuntimeError(
                f"age identity file missing: {self.age_identity_file!r}"
            )

        verify_sql = (
            self.verify_sql_path
            or str(Path(__file__).parent / "verify.sql")
        )
        if not os.path.isfile(verify_sql):
            raise RuntimeError(f"verify.sql missing: {verify_sql}")

        container = f"{_CONTAINER_PREFIX}{safe_window}"
        docker = self.docker_binary or shutil.which("docker") or "docker"
        age = self.age_binary or shutil.which("age") or "age"
        pg_restore = (
            self.pg_restore_binary or shutil.which("pg_restore") or "pg_restore"
        )
        psql = self.psql_binary or shutil.which("psql") or "psql"

        with tempfile.TemporaryDirectory(prefix="negelir-verify-") as scratch:
            scratch_path = Path(scratch)
            tar_path = scratch_path / "dump.tar"
            dump_dir = scratch_path / DUMP_DIR_NAME

            # ── Decrypt with age (DR-class identity) ───────────────────
            self.runner([
                age, "-d",
                "-i", self.age_identity_file,
                "-o", str(tar_path),
                str(encrypted),
            ])
            # ── Untar to the directory pg_restore expects ─────────────
            import tarfile
            with tarfile.open(tar_path, "r") as tar:
                # filter=data avoids the Python 3.14 deprecation warning
                # while still rejecting absolute paths / device files.
                _safe_extract(tar, scratch_path)

            # ── Spin ephemeral postgres container ─────────────────────
            try:
                self.runner([
                    docker, "run", "-d", "--rm",
                    "--name", container,
                    "--network", self.docker_network,
                    "-e", "POSTGRES_PASSWORD=verify",
                    "-e", "POSTGRES_DB=negelir_verify",
                    "-p", "127.0.0.1:0:5432",  # ephemeral host port
                    self.pg_image,
                ])
                # Wait for readiness via pg_isready inside the container.
                self._wait_ready(docker, container)

                # Resolve the host port the daemon allocated. We use
                # `docker port <c> 5432/tcp` to get `0.0.0.0:NNNN`.
                port = self._resolve_port(docker, container)
                env = {
                    **os.environ,
                    "PGPASSWORD": "verify",
                    "PGUSER": "postgres",
                    "PGHOST": "127.0.0.1",
                    "PGPORT": str(port),
                    "PGDATABASE": "negelir_verify",
                }
                # ── pg_restore ────────────────────────────────────────
                self.runner(
                    [
                        pg_restore,
                        "--jobs", str(int(self.pg_jobs)),
                        "--no-owner",
                        "--no-privileges",
                        "--dbname=negelir_verify",
                        str(dump_dir),
                    ],
                    env=env,
                )
                # ── verify.sql ────────────────────────────────────────
                cp = self.runner(
                    [
                        psql,
                        "--no-psqlrc",
                        "--tuples-only",
                        "--no-align",
                        "--field-separator=,",
                        "-f", verify_sql,
                    ],
                    env=env,
                )
                stdout = (cp.stdout or b"").decode(errors="replace")
                return _parse_verify_output(stdout)
            finally:
                # Best-effort container cleanup.
                try:
                    self.runner([docker, "rm", "-f", container])
                except Exception:  # pragma: no cover
                    pass

    def sweep_orphans(self) -> tuple[str, ...]:
        """Drop any leftover ``negelir-verify-*`` containers.

        Returns the list of container names actually removed.
        """
        docker = self.docker_binary or shutil.which("docker") or "docker"
        try:
            cp = self.runner([
                docker, "ps", "-a",
                "--filter", f"name={_CONTAINER_PREFIX}",
                "--format", "{{.Names}}",
            ])
        except Exception as exc:  # noqa: BLE001
            _log.warning("sweep_orphans list failed: %s", exc)
            return ()
        names = [
            n.strip()
            for n in (cp.stdout or b"").decode(errors="replace").splitlines()
            if n.strip().startswith(_CONTAINER_PREFIX)
        ]
        swept: list[str] = []
        for name in names:
            try:
                self.runner([docker, "rm", "-f", name])
                swept.append(name)
            except Exception as exc:  # noqa: BLE001
                _log.warning("sweep_orphans rm %s failed: %s", name, exc)
        return tuple(swept)

    # ── Internal helpers ────────────────────────────────────────────────
    def _wait_ready(self, docker: str, container: str) -> None:
        # Up to ~30s of pg_isready polling. We do not import time for
        # sleep — the runner is allowed to block on docker exec, which
        # itself takes wall time per attempt.
        import time
        for _attempt in range(30):
            try:
                self.runner([
                    docker, "exec", container,
                    "pg_isready", "-U", "postgres",
                ])
                return
            except Exception:  # noqa: BLE001 — keep polling
                time.sleep(1.0)
        raise RuntimeError(f"verify container {container} never became ready")

    def _resolve_port(self, docker: str, container: str) -> int:
        cp = self.runner([docker, "port", container, "5432/tcp"])
        line = (cp.stdout or b"").decode(errors="replace").splitlines()[0]
        # Format: "0.0.0.0:54321" or "[::]:54321"
        port_str = line.rsplit(":", 1)[-1].strip()
        return int(port_str)


def _safe_extract(tar, dest: Path) -> None:
    """Extract ``tar`` into ``dest`` rejecting traversal entries."""
    dest = dest.resolve()
    for member in tar.getmembers():
        member_path = (dest / member.name).resolve()
        if not str(member_path).startswith(str(dest)):
            raise RuntimeError(
                f"refusing tar member outside dest: {member.name!r}"
            )
        if member.islnk() or member.issym():
            raise RuntimeError(
                f"refusing link member in dump tar: {member.name!r}"
            )
    tar.extractall(dest, filter="data")  # noqa: S202 — guarded above; data filter rejects links/devices


def _sha256_file(path: Path, *, chunk_size: int = 1 << 20) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_verify_output(stdout: str) -> dict[str, int]:
    """Parse psql ``--tuples-only --no-align -F,`` output.

    Each non-empty line is ``<table>,<count>``. Returns a dict
    suitable for the ``RestoreVerifier`` Protocol.
    """
    out: dict[str, int] = {}
    for raw in stdout.splitlines():
        line = raw.strip()
        if not line or "," not in line:
            continue
        name, _, value = line.partition(",")
        name = name.strip()
        try:
            out[name] = int(value.strip())
        except ValueError:
            # Skip non-integer rows (e.g. blank lines from psql).
            continue
    return out


__all__ = ["LocalSubprocessVerifier"]
