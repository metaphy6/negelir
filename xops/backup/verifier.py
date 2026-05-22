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
    DUMP_FILE_NAME,
    ENCRYPTED_NAME,
    FILE_CHECKSUM_MANIFEST_NAME,
    MANIFEST_NAME,
    _default_runner,
)
from xops.backup.migration_state import (
    _REPO_ROOT,
    scan_in_tree_migrations as _scan_in_tree_migrations,
)


_log = logging.getLogger("xops.backup.verifier")


# Container name prefix; the per-fire-window suffix is appended.
# A scrub of `docker ps -a --filter name=<prefix>` lets sweep_orphans
# recover from a verifier crash mid-restore.
_CONTAINER_PREFIX: str = "negelir-verify-"


class VersionGapRefusalError(RuntimeError):
    """Raised inside ``_verify_inner`` when the dump's schema version is too
    old relative to in-tree migrations (gap > ``max_version_gap``).

    Caught exclusively by ``LocalSubprocessVerifier.verify`` — never
    escapes to callers.  Carries the structured refusal context so
    ``verify()`` can populate ``last_refusal_info`` before returning
    ``{}``.
    """

    def __init__(
        self,
        message: str,
        *,
        version_gap: int,
        manifest_max_version: int,
        in_tree_max_version: int,
        max_gap: int,
    ) -> None:
        super().__init__(message)
        self.version_gap = version_gap
        self.manifest_max_version = manifest_max_version
        self.in_tree_max_version = in_tree_max_version
        self.max_gap = max_gap


class FileManifestCorruptionError(RuntimeError):
    """Raised by ``_verify_inner`` when the inner per-file manifest
    (``negelir.files.sha256.txt``) detected at least one file whose
    computed SHA-256 does not match the recorded value.

    Carries ``failures`` — a list of
    ``{file: str, expected: str, actual: str}`` dicts, one per
    corrupted or missing file.
    """

    def __init__(self, message: str, *, failures: list) -> None:
        super().__init__(message)
        self.failures: list = failures


class VerifyPgTooOldError(RuntimeError):
    """Raised by ``_verify_inner`` when the verify image's Postgres major
    version is older than the source server that produced the dump.

    ``pg_restore`` of a dump from a newer Postgres into an older server
    is unsupported (§8.14.9 verify-PG version invariant). Callers MUST
    NOT attempt the restore — raise this before spinning the container.

    Carries:
        image_version_num: parsed from the image tag (e.g. 160000 for
            postgres:16-alpine).
        source_version_num: ``server_version_num`` integer read from the
            dump manifest (e.g. 170004 for PG 17.0.4).
    """

    def __init__(
        self,
        message: str,
        *,
        image_version_num: int,
        source_version_num: int,
    ) -> None:
        super().__init__(message)
        self.image_version_num = image_version_num
        self.source_version_num = source_version_num


def _parse_pg_image_version_num(image: str) -> int:
    """Parse a postgres docker image tag to a major-version integer.

    Maps ``postgres:16-alpine`` → 160000, ``postgres:17.1`` → 170000,
    ``postgres:14`` → 140000. Only the major version is used because
    pg_restore compatibility is major-version-scoped, not patch-scoped.
    Returns 0 when the tag cannot be parsed (caller skips the check).
    """
    import re as _re

    tag = image.split(":")[-1] if ":" in image else image
    m = _re.match(r"(\d+)", tag)
    if not m:
        return 0
    major = int(m.group(1))
    return major * 10000


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
    # §8.13.4 version-skew guard: maximum schema-version gap
    # (in_tree_max - manifest.max_version) before refusing with
    # backup_dump_too_old.  Default 5 (matches cfg default).
    # Tests inject a smaller value to exercise the guard cheaply.
    max_version_gap: int = 5
    # §8.13.4: scan-root override for in-tree migrations (None = repo default).
    # Tests inject a synthetic migrations directory.
    migrations_dir: Optional[Path] = None
    # §8.13.4: populated when the last verify() call refused due to a
    # version gap.  None when verify succeeded or failed for another
    # reason.  Cleared at the start of each verify() call.
    # Callers check this to emit the specific backup_dump_too_old
    # sec.alert.v1 rather than the generic backup_verify_failed.
    last_refusal_info: Optional[dict] = field(default=None, compare=False)
    # §8.14.2: populated when the last verify() call detected one or more
    # files whose SHA-256 does not match the inner per-file manifest
    # (negelir.files.sha256.txt inside the encrypted tarball).  Each entry
    # is {file: str, expected: str, actual: str}. None when verify
    # succeeded, failed for another reason, or the manifest check was not
    # reached.  Callers emit sec.alert.v1{kind=backup_dump_file_corrupted}.
    last_file_manifest_failures: Optional[list] = field(default=None, compare=False)
    # §8.14.2: True when the encrypted tarball contains no inner per-file
    # manifest (legacy dump pre-§8.14.2).  Callers emit
    # maint.event.v1{kind=backup_legacy_no_file_manifest, severity=info}.
    # Cleared at the start of each verify() call.
    last_legacy_no_file_manifest: bool = field(default=False, compare=False)
    # §8.14.9: populated when the last verify() call refused because the
    # verify-PG image is older than the source server version.  None when
    # verify succeeded or failed for another reason.  Cleared at the start
    # of each verify() call.  Callers emit
    # sec.alert.v1{kind=fail_safe_verify_pg_too_old}.
    last_verify_pg_too_old_info: Optional[dict] = field(default=None, compare=False)

    def verify(
        self, *, fire_window_id: str, mode: str = "full",
    ) -> Mapping[str, int]:
        """Restore the dump and return per-table row counts.

        ``mode`` is the ROADMAP §8.3 escape hatch:

        * ``"full"`` (default) — decrypt → untar → spin postgres →
          ``pg_restore`` → forward-migrate (§8.13.4) → ``verify.sql``
          → return row counts.
        * ``"toc_only"`` — decrypt → untar → ``pg_restore --list``
          only. No container, no row restore. Returns
          ``{"_toc_only": 1, "_toc_entries": <int>}`` on success;
          empty dict on any failure (Protocol contract).

        §8.13.4 version-skew semantics:

        * When the manifest carries ``migrations_at_dump_time`` and the
          version gap exceeds ``max_version_gap``, ``verify()`` returns
          ``{}`` AND sets ``self.last_refusal_info`` with
          ``kind="backup_dump_too_old"`` so the caller can emit a
          targeted ``sec.alert.v1{severity=error}`` rather than the
          generic ``backup_verify_failed``.
        * When the manifest pre-dates this revision (no
          ``migrations_at_dump_time`` field), forward-migration is
          skipped and ``verify.sql`` runs against the dump's schema
          only.  The result includes ``_legacy_manifest: 1``.

        Empty dict means verify failed (the Protocol contract
        ``MaintBackupAgent`` reads as ``verify_failed`` outcome).
        """
        # Clear per-call state so stale info from a prior call never
        # contaminates a fresh verify.
        self.last_refusal_info = None
        self.last_file_manifest_failures = None
        self.last_legacy_no_file_manifest = False
        self.last_verify_pg_too_old_info = None

        if mode not in ("full", "toc_only"):
            _log.warning(
                "LocalSubprocessVerifier.verify window=%s rejected unknown mode=%r",
                fire_window_id, mode,
            )
            return {}
        try:
            if mode == "toc_only":
                return self._verify_toc_only(fire_window_id=fire_window_id)
            return self._verify_inner(fire_window_id=fire_window_id)
        except VersionGapRefusalError as exc:
            self.last_refusal_info = {
                "kind": "backup_dump_too_old",
                "version_gap": exc.version_gap,
                "manifest_max_version": exc.manifest_max_version,
                "in_tree_max_version": exc.in_tree_max_version,
                "max_gap": exc.max_gap,
            }
            _log.warning(
                "LocalSubprocessVerifier.verify window=%s backup_dump_too_old: %s",
                fire_window_id, exc,
            )
            return {}
        except VerifyPgTooOldError as exc:
            self.last_verify_pg_too_old_info = {
                "kind": "fail_safe_verify_pg_too_old",
                "image_version_num": exc.image_version_num,
                "source_version_num": exc.source_version_num,
                "pg_image": self.pg_image,
            }
            _log.warning(
                "LocalSubprocessVerifier.verify window=%s "
                "fail_safe_verify_pg_too_old: %s",
                fire_window_id, exc,
            )
            return {}
        except FileManifestCorruptionError as exc:
            self.last_file_manifest_failures = exc.failures
            _log.warning(
                "LocalSubprocessVerifier.verify window=%s "
                "backup_dump_file_corrupted: %s",
                fire_window_id, exc,
            )
            return {}
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

        # ── §8.13.4 version-skew check (fail-fast, before container) ──
        legacy_manifest: bool = False
        forward_migrations: list[tuple[int, Path]] = []

        manifest_path = window_dir / MANIFEST_NAME
        manifest_max_version: Optional[int] = None
        if manifest_path.is_file():
            try:
                mdata = json.loads(manifest_path.read_text(encoding="utf-8"))
                mig_meta = mdata.get("migrations_at_dump_time")
                if isinstance(mig_meta, dict) and "max_version" in mig_meta:
                    manifest_max_version = int(mig_meta["max_version"])
                # §8.14.9 verify-PG version invariant: refuse to restore a dump
                # produced by a newer Postgres major version than the verify image.
                _source_version_num = int(mdata.get("server_version_num") or 0)
                if _source_version_num > 0:
                    _image_version_num = _parse_pg_image_version_num(self.pg_image)
                    if _image_version_num > 0 and (
                        _image_version_num // 10000 < _source_version_num // 10000
                    ):
                        raise VerifyPgTooOldError(
                            f"fail_safe_verify_pg_too_old: "
                            f"image={self.pg_image} "
                            f"image_major={_image_version_num // 10000} < "
                            f"source_major={_source_version_num // 10000} "
                            f"(source_version_num={_source_version_num})",
                            image_version_num=_image_version_num,
                            source_version_num=_source_version_num,
                        )
            except (VerifyPgTooOldError, VersionGapRefusalError):
                raise
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                _log.debug(
                    "LocalSubprocessVerifier: manifest parse error %s: %s",
                    manifest_path, exc,
                )

        in_tree = _scan_in_tree_migrations(migrations_dir=self.migrations_dir)
        in_tree_max = int(in_tree["max_version"])

        if manifest_max_version is None:
            # Legacy manifest (pre-§8.13.4) — no migrations_at_dump_time field.
            # Skip forward-migration; run verify.sql against the dump's schema only.
            legacy_manifest = True
            _log.info(
                "LocalSubprocessVerifier.verify window=%s: legacy manifest "
                "(no migrations_at_dump_time); skipping forward-migrate, "
                "running verify.sql against dump schema only",
                fire_window_id,
            )
        else:
            version_gap = in_tree_max - manifest_max_version
            max_gap = self.max_version_gap
            _log.debug(
                "LocalSubprocessVerifier.verify window=%s: "
                "manifest_max=%d in_tree_max=%d gap=%d max_gap=%d",
                fire_window_id, manifest_max_version, in_tree_max,
                version_gap, max_gap,
            )
            if version_gap > max_gap:
                raise VersionGapRefusalError(
                    f"backup_dump_too_old: version_gap={version_gap} > "
                    f"max_gap={max_gap} "
                    f"(manifest_max={manifest_max_version}, in_tree_max={in_tree_max})",
                    version_gap=version_gap,
                    manifest_max_version=manifest_max_version,
                    in_tree_max_version=in_tree_max,
                    max_gap=max_gap,
                )
            # Restore-verify never runs migrations backward.  See Phase 8
            # doctrine (AGENTS.md §2, CLAUDE.md: "never DROP").
            # A future destructive migration (Phase 14+) requires an
            # explicit escape-hatch design before restore-verify can
            # run it — this loop is intentionally forward-only.
            # Collect forward migrations in (manifest_max_version, in_tree_max].
            if version_gap > 0:
                mig_root = (
                    self.migrations_dir
                    if self.migrations_dir is not None
                    else _REPO_ROOT / "migrations"
                )
                for ver in sorted(in_tree["applied_versions"]):
                    if ver > manifest_max_version:
                        # Find the SQL file by version-number prefix.
                        # Try zero-padded (e.g. 003_*.sql) then bare (3_*.sql).
                        candidates: list[Path] = []
                        for pat in (f"{ver:03d}_*.sql", f"{ver}_*.sql"):
                            for p in mig_root.glob(pat):
                                if p not in candidates:
                                    candidates.append(p)
                        if candidates:
                            forward_migrations.append((ver, candidates[0]))
                        else:
                            _log.warning(
                                "LocalSubprocessVerifier: forward migration "
                                "file for version %d not found under %s; "
                                "skipping (schema may be incomplete)",
                                ver, mig_root,
                            )

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
            dump_file = scratch_path / DUMP_FILE_NAME

            # ── Decrypt with age (DR-class identity) ───────────────────────
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

            # §8.3 binding: the dump artefact is either ``dump.d/``
            # (``-Fd``, multi-job) or ``negelir.dump`` (``-Fc``,
            # single-job). Detect which one is present and pass that
            # path to ``pg_restore`` — it auto-detects the format.
            if dump_dir.is_dir():
                restore_target = dump_dir
            elif dump_file.is_file():
                restore_target = dump_file
            else:
                raise RuntimeError(
                    f"no recognised dump artefact in {scratch_path} "
                    f"(expected {DUMP_DIR_NAME}/ or {DUMP_FILE_NAME})"
                )

            # ── §8.14.2 per-file manifest check (inner corruption gate) ──
            # Manifest location depends on dump format:
            #   -Fd (dir):  inside dump.d/ → dump.d/negelir.files.sha256.txt
            #   -Fc (file): at tar root    → negelir.files.sha256.txt
            _dir_manifest = dump_dir / FILE_CHECKSUM_MANIFEST_NAME
            _root_manifest = scratch_path / FILE_CHECKSUM_MANIFEST_NAME
            if _dir_manifest.is_file():
                _inner_manifest: Optional[Path] = _dir_manifest
                _manifest_base = dump_dir
            elif _root_manifest.is_file():
                _inner_manifest = _root_manifest
                _manifest_base = scratch_path
            else:
                _inner_manifest = None
                _manifest_base = scratch_path  # unused
            if _inner_manifest is not None:
                _failures: list = []
                for _raw_line in _inner_manifest.read_text(encoding="utf-8").splitlines():
                    _raw_line = _raw_line.strip()
                    if not _raw_line:
                        continue
                    _parts = _raw_line.split("  ", 1)
                    if len(_parts) != 2:
                        _log.warning(
                            "LocalSubprocessVerifier: malformed manifest"
                            " line in window=%s: %r",
                            fire_window_id, _raw_line,
                        )
                        continue
                    _expected_hex, _relpath = _parts
                    _fpath = _manifest_base / _relpath
                    if not _fpath.is_file():
                        _failures.append({
                            "file": _relpath,
                            "expected": _expected_hex,
                            "actual": "missing",
                        })
                        continue
                    _actual_hex = _sha256_file(_fpath)
                    if _expected_hex.lower() != _actual_hex.lower():
                        _failures.append({
                            "file": _relpath,
                            "expected": _expected_hex[:16],
                            "actual": _actual_hex[:16],
                        })
                if _failures:
                    raise FileManifestCorruptionError(
                        f"inner manifest check failed for window={fire_window_id}:"
                        f" {len(_failures)} corrupted file(s)",
                        failures=_failures,
                    )
                _log.debug(
                    "LocalSubprocessVerifier.verify window=%s: inner manifest OK",
                    fire_window_id,
                )
            else:
                # Legacy dump — no inner per-file manifest (pre-§8.14.2).
                _log.info(
                    "LocalSubprocessVerifier.verify window=%s: no inner "
                    "file manifest (legacy dump); outer-checksum-only "
                    "verification proceeds (§8.14.2)",
                    fire_window_id,
                )
                self.last_legacy_no_file_manifest = True

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
                        str(restore_target),
                    ],
                    env=env,
                )
                # ── Forward-migrate (§8.13.4) ─────────────────────────
                # Apply each migration in (manifest.max_version,
                # in_tree_max] in numeric order so verify.sql always
                # evaluates against the in-tree schema regardless of
                # dump age. Skipped when legacy_manifest is True or
                # version_gap == 0.
                for _ver, sql_path in forward_migrations:
                    _log.info(
                        "LocalSubprocessVerifier.verify window=%s: "
                        "applying forward migration %d (%s)",
                        fire_window_id, _ver, sql_path.name,
                    )
                    self.runner(
                        [
                            psql,
                            "--no-psqlrc",
                            "--dbname=negelir_verify",
                            "-f", str(sql_path),
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
                result = dict(_parse_verify_output(stdout))
                if legacy_manifest:
                    result["_legacy_manifest"] = 1
                return result
            finally:
                # Best-effort container cleanup.
                try:
                    self.runner([docker, "rm", "-f", container])
                except Exception:  # pragma: no cover
                    pass

    def _verify_toc_only(self, *, fire_window_id: str) -> Mapping[str, int]:
        """ROADMAP §8.3 escape hatch: validate the dump's TOC only.

        Decrypts + untars the dump like the full path, then runs
        ``pg_restore --list <target>`` and counts the TOC entries.
        No ephemeral Postgres container is started; suitable for
        very-large-DB nightly windows where a full restore exceeds
        the maintenance window. Weekly cold-verify still runs the
        full suite — toc-only catches checksum/decrypt/format
        corruption, not row-level integrity.
        """
        safe_window = fire_window_id.replace(":", "_").replace("/", "_")
        window_dir = Path(self.backup_dir) / safe_window
        encrypted = window_dir / ENCRYPTED_NAME
        checksum = window_dir / CHECKSUM_NAME
        if not encrypted.is_file():
            raise RuntimeError(f"encrypted dump missing: {encrypted}")
        if not checksum.is_file():
            raise RuntimeError(f"checksum missing: {checksum}")

        # Same checksum gate as the full path — silent-corruption is
        # the threat model toc_only must still catch.
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

        age = self.age_binary or shutil.which("age") or "age"
        pg_restore = (
            self.pg_restore_binary or shutil.which("pg_restore") or "pg_restore"
        )

        with tempfile.TemporaryDirectory(prefix="negelir-verify-toc-") as scratch:
            scratch_path = Path(scratch)
            tar_path = scratch_path / "dump.tar"
            dump_dir = scratch_path / DUMP_DIR_NAME
            dump_file = scratch_path / DUMP_FILE_NAME

            # Decrypt + untar (same as full path).
            self.runner([
                age, "-d",
                "-i", self.age_identity_file,
                "-o", str(tar_path),
                str(encrypted),
            ])
            import tarfile
            with tarfile.open(tar_path, "r") as tar:
                _safe_extract(tar, scratch_path)

            if dump_dir.is_dir():
                restore_target = dump_dir
            elif dump_file.is_file():
                restore_target = dump_file
            else:
                raise RuntimeError(
                    f"no recognised dump artefact in {scratch_path} "
                    f"(expected {DUMP_DIR_NAME}/ or {DUMP_FILE_NAME})"
                )

            cp = self.runner([pg_restore, "--list", str(restore_target)])
            stdout = (cp.stdout or b"").decode(errors="replace")
            entries = sum(
                1
                for raw in stdout.splitlines()
                if raw.strip() and not raw.lstrip().startswith(";")
            )
            if entries <= 0:
                raise RuntimeError("pg_restore --list returned no TOC entries")
            return {"_toc_only": 1, "_toc_entries": int(entries)}

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


__all__ = ["FileManifestCorruptionError", "LocalSubprocessVerifier", "VersionGapRefusalError"]
