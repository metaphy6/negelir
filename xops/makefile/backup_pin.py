#!/usr/bin/env python3
"""`make verify.age-pin` and `make ops.backup-bump-age` — ROADMAP §8.14.3.

verify-age-pin:
    Read infra/maint/age_binary_provenance.txt, re-fetch the pinned tarball
    URL, recompute its SHA-256, and assert it matches the recorded value.
    Exit non-zero with "provenance_drift" on mismatch — CI gate.

    In test / offline mode the network fetch is replaced by a SHA-256
    computed from a local file path supplied via $AGE_PIN_LOCAL_TARBALL.
    This lets proof test (b) assert provenance_drift on a tampered file
    without hitting the network.

backup-bump-age (future operator entrypoint):
    Fetch new release, verify checksum, update Dockerfile and provenance
    file atomically, then re-run verify-age-pin.  Implemented as a stub
    that prints usage guidance until the operator-facing CLI lands in
    a follow-up §8.14.3 ticket.
"""
from __future__ import annotations

import configparser
import hashlib
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import REPO_ROOT, dispatch, err, ok, warn  # noqa: E402

# Allow tests to override the provenance file path so the proof test
# for (b) can inject a tampered file without touching the committed one.
_PROVENANCE_OVERRIDE = os.environ.get("_NEGELIR_PROVENANCE_OVERRIDE", "").strip()
PROVENANCE_FILE = (
    Path(_PROVENANCE_OVERRIDE)
    if _PROVENANCE_OVERRIDE
    else REPO_ROOT / "infra" / "maint" / "age_binary_provenance.txt"
)


def _read_provenance(version: str | None = None) -> dict:
    """Parse the provenance file and return the record for `version`.

    If `version` is None, returns the record for the first section found.
    Raises SystemExit(1) with a descriptive error on parse / not-found.
    """
    if not PROVENANCE_FILE.is_file():
        err(
            f"verify.age-pin: provenance file not found: {PROVENANCE_FILE}\n"
            "  Create it at infra/maint/age_binary_provenance.txt "
            "(ROADMAP §8.14.3)."
        )
        sys.exit(1)

    cfg = configparser.ConfigParser()
    # configparser strips inline comments; preserve raw values.
    cfg.read(str(PROVENANCE_FILE))

    sections = cfg.sections()
    if not sections:
        err(
            "verify.age-pin: provenance file has no version sections. "
            "Expected [<version>] sections."
        )
        sys.exit(1)

    if version is None:
        # Default: use the highest-numbered (last) section.
        version = sections[-1]

    if version not in sections:
        err(
            f"verify.age-pin: version {version!r} not found in provenance file. "
            f"Available: {sections}"
        )
        sys.exit(1)

    record = dict(cfg[version])
    required = ("version", "sha256", "source_url", "recorded_at")
    missing = [k for k in required if not record.get(k, "").strip()]
    if missing:
        err(
            f"verify.age-pin: provenance record [{version}] missing fields: {missing}"
        )
        sys.exit(1)
    return record


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_of_url(url: str) -> str:
    """Download `url` in streaming fashion and return its SHA-256 hex digest."""
    h = hashlib.sha256()
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "negelir-verify-age-pin/1"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def cmd_verify_age_pin(argv: list) -> int:
    """Verify the pinned age binary SHA-256 against the provenance record.

    Usage: backup_pin.py verify-age-pin [--version VERSION]
    Environment:
        AGE_PIN_LOCAL_TARBALL — path to a local tarball; skips network fetch.
            Used by proof tests to assert provenance_drift on tampered files.
        AGE_PIN_SKIP_FETCH    — set to "1" to skip the fetch entirely
            (only validates the provenance file is well-formed).
    """
    version: str | None = None
    _argv = list(argv)
    while _argv:
        tok = _argv.pop(0)
        if tok in ("--version", "-v") and _argv:
            version = _argv.pop(0)

    record = _read_provenance(version)
    pinned_sha = record["sha256"].strip().lower()
    source_url = record["source_url"].strip()
    rec_version = record["version"].strip()

    local_tarball = os.environ.get("AGE_PIN_LOCAL_TARBALL", "").strip()
    skip_fetch = os.environ.get("AGE_PIN_SKIP_FETCH", "").strip() == "1"

    if skip_fetch:
        ok(
            f"verify.age-pin: skip-fetch mode — provenance record for "
            f"{rec_version!r} is well-formed (SHA not verified)."
        )
        return 0

    if local_tarball:
        p = Path(local_tarball)
        if not p.is_file():
            err(f"verify.age-pin: AGE_PIN_LOCAL_TARBALL={local_tarball!r} not found")
            return 1
        computed = _sha256_of_file(p)
        source_desc = f"local file {p.name}"
    else:
        print(f"→ verify.age-pin: downloading {source_url} …")
        try:
            computed = _sha256_of_url(source_url)
        except Exception as exc:  # noqa: BLE001
            err(f"verify.age-pin: fetch failed: {exc}")
            err(
                "  Tip: set AGE_PIN_LOCAL_TARBALL=<path> to verify against "
                "a local copy, or AGE_PIN_SKIP_FETCH=1 to skip the network check."
            )
            return 1
        source_desc = source_url

    if computed != pinned_sha:
        err(
            f"verify.age-pin: provenance_drift — "
            f"SHA-256 mismatch for age {rec_version}\n"
            f"  source     : {source_desc}\n"
            f"  recorded   : {pinned_sha}\n"
            f"  recomputed : {computed}\n"
            "Supply-chain incident: rotate the pin via `make ops.backup-bump-age`."
        )
        return 2  # provenance_drift exit code

    ok(
        f"verify.age-pin: age {rec_version} ok — "
        f"SHA-256 matches provenance record"
    )
    return 0


def cmd_backup_bump_age(argv: list) -> int:
    """Stub for `make ops.backup-bump-age VERSION=<v>`.

    Full implementation (fetch + checksum + Dockerfile patch +
    provenance update + verify) lands in a follow-up operator-CLI
    ticket. Prints usage guidance and exits 1 so CI does not
    accidentally treat this stub as successful.
    """
    err(
        "ops.backup-bump-age: full operator CLI not yet implemented.\n"
        "Manual upgrade procedure:\n"
        "  1. Download the new tarball from the upstream GitHub release.\n"
        "  2. Recompute its SHA-256 (sha256sum <tarball>).\n"
        "  3. Add a new [<version>] section to "
        "infra/maint/age_binary_provenance.txt.\n"
        "  4. Update the Dockerfile RUN block to use the new URL and checksum.\n"
        "  5. Run `make verify.age-pin` to confirm the recorded SHA matches.\n"
        "  6. Bump cfg.maint_backup_age_binary_version in .env / Helm values."
    )
    return 1


COMMANDS = {
    "verify-age-pin": cmd_verify_age_pin,
    "backup-bump-age": cmd_backup_bump_age,
}


def main(argv=None):
    return dispatch(
        argv if argv is not None else sys.argv[1:],
        COMMANDS,
        script_name="backup_pin.py",
    )


if __name__ == "__main__":
    sys.exit(main())
