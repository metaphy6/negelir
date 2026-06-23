#!/usr/bin/env python3
"""`make mock.*` — Phase 2 dev-stack dispatchers (real implementations).

Targets:
    up        docker compose up -d mocksrv nginx-mock
    down      docker compose down (mock services)
    ca-init   generate root CA + leaf certs for the four mock vhosts
    ca-trust  print platform-specific instructions to trust the root CA
    capture   hit real upstreams and refresh the seed corpus (rate-limited)
    verify    offline integrity check of the seed corpus
    nginx     re-render infra/mock/nginx/{nginx.conf, conf.d/vhost-*.conf}
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from xops.makefile._common import COMPOSE, ENV_FILE, dispatch, info, ok, sudo_run, warn  # noqa: E402


def _mock_compose_base() -> str:
    """`docker compose --env-file <env> -f base --profile mock` as a single shell string.

    Centralised so cmd_up/cmd_down can't drift from the project-wide env-file
    convention enforced in _common.py.
    
    Mock services are now in the base docker-compose.yml with the 'mock' profile.
    """
    parts = list(COMPOSE)
    if ENV_FILE.is_file():
        parts += ["--env-file", str(ENV_FILE)]
    parts += ["-f", "docker-compose.yml", "--profile", "mock"]
    return " ".join(parts)


def cmd_up(_argv: List[str]) -> int:
    base = _mock_compose_base()
    info(f"{base} up -d --build mocksrv nginx-mock")
    rc = os.system(f"{base} up -d --build mocksrv nginx-mock")
    return 0 if rc == 0 else 1


def cmd_down(_argv: List[str]) -> int:
    rc = os.system(f"{_mock_compose_base()} down")
    return 0 if rc == 0 else 1


def cmd_ca_init(argv: List[str]) -> int:
    from xops.mock import ca

    force = "--force" in argv
    try:
        ca.init_ca(force=force)
        for host in ("mackolik.local", "nesine.local", "tff.local", "openfootball.local"):
            ca.issue_leaf(host, force=force)
        ok("root CA + leaf certs ready under infra/mock/{ca,certs}/")
        return 0
    except ca.CAError as exc:
        warn(str(exc))
        return 1


def cmd_ca_trust(_argv: List[str]) -> int:
    crt = REPO_ROOT / "infra" / "mock" / "ca" / "root.crt"
    if not crt.exists():
        warn("Root CA missing — run `make mock.ca-init` first.")
        return 1
    info(f"Root CA path: {crt}")
    sysname = platform.system().lower()
    if sysname == "linux":
        print("# Linux (Debian/Ubuntu):")
        print(f"  sudo cp {crt} /usr/local/share/ca-certificates/negelir-mock.crt")
        print("  sudo update-ca-certificates")
    elif sysname == "darwin":
        print("# macOS:")
        print(
            f"  sudo security add-trusted-cert -d -r trustRoot "
            f"-k /Library/Keychains/System.keychain {crt}"
        )
    elif sysname.startswith("win"):
        print("# Windows (PowerShell as Admin):")
        print(
            f"  Import-Certificate -FilePath '{crt}' "
            f"-CertStoreLocation Cert:\\LocalMachine\\Root"
        )
    else:
        warn(f"unknown OS: {sysname}; please trust {crt} manually.")
    return 0


def cmd_capture(argv: List[str]) -> int:
    """Hit real upstreams and refresh the seed corpus.

    Idempotent by default — already-seeded targets are skipped without a
    network call. Pass ``FORCE=1`` (env) or ``--force`` to refetch, and
    ``DEPTH=1`` (env) to follow same-host links one level deep so a user
    clicking around the mocked sites lands on real content rather than 404.

    Rate-limited per-source via ``DEFAULT_DELAY_S`` in capture_engine.
    Agents may invoke this target directly; it is not a privileged
    operation. Only git operations remain AI-restricted.
    """
    from xops.mock.capture_engine import (
        DEFAULT_CRAWL_MAX_PAGES, UrllibClient, capture_all,
    )
    from xops.mock.sources import SOURCES, by_key

    force = ("--force" in argv) or (os.environ.get("FORCE") == "1")
    positional = [a for a in argv if not a.startswith("--")]
    try:
        depth = int(os.environ.get("DEPTH", "0"))
    except ValueError:
        warn("DEPTH must be an integer; defaulting to 0")
        depth = 0
    try:
        max_pages = int(os.environ.get("MAX_PAGES", str(DEFAULT_CRAWL_MAX_PAGES)))
    except ValueError:
        max_pages = DEFAULT_CRAWL_MAX_PAGES

    if positional:
        try:
            sources = [by_key(k) for k in positional]
        except KeyError as exc:
            warn(str(exc))
            return 1
    else:
        sources = list(SOURCES)

    info(
        f"capturing {len(sources)} source(s) (force={force}, depth={depth}, "
        f"max_pages={max_pages}) …"
    )
    results, _ = capture_all(
        client=UrllibClient(), sources=sources,
        force=force, crawl_depth=depth, crawl_max_pages=max_pages,
    )
    refreshed = sum(1 for r in results if r.refreshed)
    skipped = sum(1 for r in results if r.skipped)
    discovered = sum(1 for r in results if r.discovered)
    ok(
        f"captured {len(results)} target(s); {refreshed} refreshed; "
        f"{skipped} skipped (already seeded); {discovered} discovered via crawl; "
        f"manifest updated"
    )
    if skipped and not force:
        info("hint: pass FORCE=1 or run `make mock.reset` to refetch.")
    return 0


def cmd_reset(argv: List[str]) -> int:
    """Wipe the seed corpus + manifest so the next capture starts fresh.

    This is the only path that authorises mock.capture to re-fetch from
    the real upstreams without ``FORCE=1``.
    """
    import shutil
    from xops.mock.capture_engine import MANIFEST_PATH, SEEDS_ROOT
    from xops.mock.sources import SOURCES, by_key

    if argv:
        try:
            sources = [by_key(k) for k in argv]
        except KeyError as exc:
            warn(str(exc))
            return 1
    else:
        sources = list(SOURCES)

    wiped = 0
    for s in sources:
        d = SEEDS_ROOT / s.key
        if d.exists():
            shutil.rmtree(d)
            wiped += 1
    if not argv and MANIFEST_PATH.exists():
        MANIFEST_PATH.unlink()
        info(f"removed {MANIFEST_PATH}")
    ok(f"reset {wiped} source(s); next `make mock.capture` will refetch.")
    return 0


def _firefox_profile_dirs() -> List[tuple[str, Path]]:
    """Detect Firefox profile directories across native / Snap / Flatpak installs.

    Returns ``[(flavour, profile_dir), …]`` with the canonical ``*.default*``
    profiles. Returns an empty list when no install is found, so the caller
    can fall back to the generic glob hint. Profiles are detected by reading
    ``profiles.ini`` is overkill here — Firefox creates exactly one
    ``*.default*`` per fresh profile, which is what we want to trust.
    """
    home = Path.home()
    roots = [
        ("native",  home / ".mozilla" / "firefox"),
        ("snap",    home / "snap" / "firefox" / "common" / ".mozilla" / "firefox"),
        ("flatpak", home / ".var" / "app" / "org.mozilla.firefox" / ".mozilla" / "firefox"),
    ]
    found: List[tuple[str, Path]] = []
    for flavour, root in roots:
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if child.is_dir() and (".default" in child.name):
                found.append((flavour, child))
    return found


def cmd_browser(_argv: List[str]) -> int:
    """One-shot guide: trust the CA, install hostnames, hint Firefox NSS.

    Per AGENTS.md doctrine, the actual sudo-needing writes are deferred
    to the human — this target only PRINTS the exact commands.
    """
    crt = REPO_ROOT / "infra" / "mock" / "ca" / "root.crt"
    if not crt.exists():
        warn("Root CA missing — run `make mock.ca-init` first.")
        return 1
    info("Browser-ready *.local — copy/paste these by hand (sudo required):")
    print()
    print("# 1) Hostnames (writes /etc/hosts):")
    print("   sudo make hosts.install")
    print()
    print("# 2) Trust the dev root CA:")
    sysname = platform.system().lower()
    if sysname == "linux":
        print(f"   sudo cp {crt} /usr/local/share/ca-certificates/negelir-mock.crt")
        print("   sudo update-ca-certificates")
        print()
        print("# 3) Firefox uses its own NSS DB — import there too.")
        print("   (Quit Firefox first; it locks the DB while running.)")
        profiles = _firefox_profile_dirs()
        if profiles:
            print(f"   # Detected {len(profiles)} Firefox profile(s):")
            for flavour, prof in profiles:
                print(f"   #   [{flavour}] {prof}")
                print(
                    f"   certutil -A -n 'negelir-mock' -t 'TC,,' "
                    f"-i {crt} -d \"sql:{prof}\""
                )
        else:
            print("   # (no Firefox profile found — install Firefox or adjust paths below)")
            print("   for db in $HOME/.mozilla/firefox/*.default*/ \\")
            print("             $HOME/snap/firefox/common/.mozilla/firefox/*.default*/ \\")
            print("             $HOME/.var/app/org.mozilla.firefox/.mozilla/firefox/*.default*/; do \\")
            print(f"     [ -d \"$db\" ] && certutil -A -n 'negelir-mock' -t 'TC,,' -i {crt} -d \"sql:$db\"; \\")
            print("   done")
        print("   # (chromium/chrome read /etc/ssl/certs — no extra step)")
    elif sysname == "darwin":
        print(
            f"   sudo security add-trusted-cert -d -r trustRoot "
            f"-k /Library/Keychains/System.keychain {crt}"
        )
        print()
        print("# 3) (Firefox: Settings → Privacy & Security → Certificates → Import)")
    elif sysname.startswith("win"):
        print(
            f"   Import-Certificate -FilePath '{crt}' "
            f"-CertStoreLocation Cert:\\LocalMachine\\Root"
        )
    else:
        print(f"   (unknown OS {sysname}; trust {crt} manually)")
    print()
    print("# 4) Bring the mock stack up:")
    print("   make mock.up")
    print()
    print("# 5) Visit:")
    for h in ("mackolik.local", "nesine.local", "tff.local", "openfootball.local"):
        print(f"   https://{h}/")
    return 0


def cmd_smoke(_argv: List[str]) -> int:
    """From-zero E2E sanity: reset → capture → up → curl every vhost.

    Designed to answer the question "is the mock site BROWSABLE?". It
    follows depth-1 links during capture and then proves the mocksrv
    home-page fallback works for unknown URLs.
    """
    import json
    import subprocess
    import time

    print("=== mock.smoke ===")
    crt = REPO_ROOT / "infra" / "mock" / "ca" / "root.crt"
    if not crt.exists():
        warn("Root CA missing — run `make mock.ca-init` first.")
        return 1

    steps = [
        ([sys.executable, str(REPO_ROOT / "xops/makefile/mock.py"), "reset"], "reset"),
        ([sys.executable, str(REPO_ROOT / "xops/makefile/mock.py"), "capture"], "capture (depth=1)"),
        ([sys.executable, str(REPO_ROOT / "xops/makefile/mock.py"), "nginx"], "render nginx"),
        ([sys.executable, str(REPO_ROOT / "xops/makefile/mock.py"), "up"], "compose up"),
    ]
    env = os.environ.copy()
    # Smoke is intentionally tiny: DEPTH=1 proves the crawler runs, but
    # MAX_PAGES is capped so the whole sequence finishes in well under a
    # minute. Larger crawls belong in `make mock.capture DEPTH=1`.
    env.setdefault("DEPTH", "1")
    env.setdefault("MAX_PAGES", "3")
    for cmd, label in steps:
        info(f"→ {label}: {' '.join(cmd)}")
        rc = subprocess.call(cmd, env=env)
        if rc != 0:
            warn(f"step '{label}' failed (rc={rc}); aborting smoke.")
            return rc

    # Now curl every vhost. The mock stack listens on host port 443.
    ca_arg = ["--cacert", str(crt)]
    hosts = ["mackolik.local", "nesine.local", "tff.local", "openfootball.local"]

    failures = []
    for h in hosts:
        url = f"https://{h}/"
        # nginx-mock races with curl on cold-start (first TLS handshake can
        # fail with SSL_ERROR_SYSCALL while the server binds 443). One retry
        # after a short wait is enough; permanent breakage will fail twice.
        rc = 1
        for attempt in range(3):
            rc = subprocess.call(
                ["curl", "-sSI", "--max-time", "5", "--resolve", f"{h}:443:127.0.0.1", *ca_arg, url],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            if rc == 0:
                break
            time.sleep(1.0)
        if rc != 0:
            failures.append((url, "home"))
            continue
        # Hit a deliberately-unknown path → must fall back to home (200 + header).
        url2 = f"https://{h}/__smoke_fallback__"
        out = subprocess.run(
            ["curl", "-sSI", "--max-time", "5", "--resolve", f"{h}:443:127.0.0.1", *ca_arg, url2],
            capture_output=True, text=True,
        )
        if out.returncode != 0 or "200" not in (out.stdout.splitlines()[0] if out.stdout else ""):
            failures.append((url2, "fallback"))
        ok(f"{h}: home + fallback OK")

    if failures:
        warn(f"smoke FAILED: {failures}")
        return 1
    ok("smoke PASS — every vhost reachable; fallback working.")
    return 0


def cmd_sources(_argv: List[str]) -> int:
    """Print the registered mock sources (key, mock host, real URL)."""
    from xops.mock.sources import SOURCES
    for s in SOURCES:
        print(f"  {s.key:14} → {s.mock_host:24} (real: {s.real_url(s.targets[0])})")
    return 0


def cmd_verify(_argv: List[str]) -> int:
    import importlib

    mod = importlib.import_module("xops.mock.verify")
    return int(mod.main([]))


def cmd_nginx(_argv: List[str]) -> int:
    from xops.mock.nginx import write_all

    paths = write_all()
    ok(f"wrote {len(paths)} nginx config file(s) under infra/mock/nginx/")
    return 0


# ── End-to-end provisioning (sudo allow-list per AGENTS.md §10) ──

_SYSTEM_CA_DEST = Path("/usr/local/share/ca-certificates/negelir-mock.crt")


def _certutil_available() -> bool:
    return shutil.which("certutil") is not None


def cmd_trust(_argv: List[str]) -> int:
    """Install the dev root CA into the system trust store and every
    detected Firefox NSS profile. POSIX only.

    System bits run via ``sudo`` (per AGENTS.md §10 allow-list); Firefox
    profile updates run as the invoking user (no elevation needed).
    """
    if os.name == "nt":
        warn("mock.trust is POSIX-only. On Windows use the Import-Certificate hint from `make mock.browser`.")
        return 1
    crt = REPO_ROOT / "infra" / "mock" / "ca" / "root.crt"
    if not crt.exists():
        warn("Root CA missing — run `make mock.ca-init` first.")
        return 1

    sysname = platform.system().lower()
    # ─ System trust store ─
    if sysname == "linux":
        if not shutil.which("update-ca-certificates"):
            warn("`update-ca-certificates` not found — non-Debian distro? Install ca-certificates and retry.")
            return 1
        try:
            sudo_run(["cp", str(crt), str(_SYSTEM_CA_DEST)],
                     reason=f"install CA → {_SYSTEM_CA_DEST}")
            sudo_run(["update-ca-certificates"], reason="rebuild system CA bundle")
        except subprocess.CalledProcessError as exc:
            warn(f"system trust install failed (exit {exc.returncode})")
            return 1
        ok(f"system trust: {_SYSTEM_CA_DEST}")
    elif sysname == "darwin":
        try:
            sudo_run(
                ["security", "add-trusted-cert", "-d", "-r", "trustRoot",
                 "-k", "/Library/Keychains/System.keychain", str(crt)],
                reason="add CA to System keychain",
            )
        except subprocess.CalledProcessError as exc:
            warn(f"keychain add failed (exit {exc.returncode})")
            return 1
        ok("system trust: System keychain (trustRoot)")
    else:
        warn(f"unknown OS {sysname}; skipping system trust step")

    # ─ Firefox NSS DBs ─
    profiles = _firefox_profile_dirs()
    if not profiles:
        info("no Firefox profile detected — skipping NSS step")
    elif not _certutil_available():
        warn("`certutil` not found — install libnss3-tools (Debian/Ubuntu) for Firefox trust.")
    else:
        installed = 0
        for flavour, prof in profiles:
            try:
                subprocess.run(
                    ["certutil", "-A", "-n", "negelir-mock", "-t", "TC,,",
                     "-i", str(crt), "-d", f"sql:{prof}"],
                    check=True,
                )
                ok(f"Firefox [{flavour}] {prof.name}: trusted")
                installed += 1
            except subprocess.CalledProcessError as exc:
                # cert9.db is locked while Firefox runs — common pitfall.
                warn(f"Firefox [{flavour}] {prof.name}: certutil failed "
                     f"(exit {exc.returncode}). Quit Firefox and re-run `make mock.trust`.")
        info(f"Firefox profiles trusted: {installed}/{len(profiles)}")
    return 0


def cmd_untrust(_argv: List[str]) -> int:
    """Remove the dev root CA from the system trust store and every
    detected Firefox NSS profile. POSIX only. Idempotent."""
    if os.name == "nt":
        warn("mock.untrust is POSIX-only.")
        return 1
    sysname = platform.system().lower()
    if sysname == "linux":
        if _SYSTEM_CA_DEST.exists():
            try:
                sudo_run(["rm", "-f", str(_SYSTEM_CA_DEST)],
                         reason=f"remove {_SYSTEM_CA_DEST}")
                if shutil.which("update-ca-certificates"):
                    sudo_run(["update-ca-certificates", "--fresh"],
                             reason="rebuild system CA bundle")
            except subprocess.CalledProcessError as exc:
                warn(f"system untrust failed (exit {exc.returncode})")
        else:
            info(f"{_SYSTEM_CA_DEST} not present")
    elif sysname == "darwin":
        try:
            sudo_run(
                ["security", "delete-certificate", "-c", "negelir-mock",
                 "/Library/Keychains/System.keychain"],
                reason="remove CA from System keychain",
                check=False,
            )
        except subprocess.CalledProcessError:
            pass

    if _certutil_available():
        for flavour, prof in _firefox_profile_dirs():
            r = subprocess.run(
                ["certutil", "-D", "-n", "negelir-mock", "-d", f"sql:{prof}"],
                capture_output=True, text=True,
            )
            if r.returncode == 0:
                ok(f"Firefox [{flavour}] {prof.name}: removed")
            else:
                info(f"Firefox [{flavour}] {prof.name}: nothing to remove")
    return 0


def cmd_setup(_argv: List[str]) -> int:
    """End-to-end: install /etc/hosts entries, trust the CA everywhere,
    and bring the mock stack up. Idempotent — safe to re-run."""
    info("Step 1/3: /etc/hosts entries")
    rc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "xops" / "makefile" / "hosts.py"), "install"],
    ).returncode
    if rc != 0:
        return rc
    info("Step 2/3: trust the dev root CA")
    rc = cmd_trust([])
    if rc != 0:
        return rc
    info("Step 3/3: docker compose up nginx-mock")
    rc = cmd_up([])
    if rc != 0:
        return rc
    ok("mock stack ready. Try: https://mackolik.local/")
    return 0


COMMANDS = {
    "up": cmd_up,
    "down": cmd_down,
    "ca-init": cmd_ca_init,
    "ca-trust": cmd_ca_trust,
    "capture": cmd_capture,
    "reset": cmd_reset,
    "browser": cmd_browser,
    "smoke": cmd_smoke,
    "sources": cmd_sources,
    "verify": cmd_verify,
    "nginx": cmd_nginx,
    "trust": cmd_trust,
    "untrust": cmd_untrust,
    "setup": cmd_setup,
}


def main(argv: List[str]) -> int:
    return dispatch(argv, COMMANDS, script_name="mock.py")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
