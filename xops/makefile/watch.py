#!/usr/bin/env python3
"""`make watch.*` — Phase 2.8 source-watcher dispatchers.

Targets:
    run       run one pass of source_watcher.scheduler.run_once against
              the live mock seed corpus; persists snapshots under
              infra/mock/seeds/history/<source>/.
    history   show snapshot history for one source (SOURCE=<key>).
    sources   list known source keys.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, List

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from xops.makefile._common import dispatch, info, ok, warn  # noqa: E402


def _fetch_seed(source_key: str) -> Any:
    """Read the current seed payload for a source from the mock corpus.

    For JSON targets, the parsed body is returned verbatim.
    For non-JSON (HTML, RSS, …) targets we cannot diff the DOM, so we
    capture a small probe envelope: ``_raw_len``, ``_suffix``,
    ``_sha256`` (over the bytes), and ``_status`` (read from the
    sidecar ``<file>.headers.json``). Those four are what the
    classifier's HTML rules look for — without them, total DOM
    rewrites at identical byte counts and 200→5xx flips would slip
    through the watcher silently. See
    docs/testing/phase2-source-watcher-stress.md.
    """
    import hashlib

    from xops.mock.sources import by_key

    src = by_key(source_key)
    seeds_root = REPO_ROOT / "infra" / "mock" / "seeds" / src.key
    if not seeds_root.exists():
        raise RuntimeError(
            f"no seeds for {source_key!r} — run `make mock.capture` first."
        )
    out: dict = {}
    for target in src.targets:
        candidates = list(seeds_root.glob(f"{target.name}.*"))
        candidates = [p for p in candidates if not p.name.endswith(".headers.json")]
        if not candidates:
            continue
        payload_path = candidates[0]
        raw = payload_path.read_bytes()
        if payload_path.suffix == ".json":
            try:
                out[target.name] = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                out[target.name] = {
                    "_raw_len": len(raw),
                    "_suffix": payload_path.suffix,
                    "_sha256": hashlib.sha256(raw).hexdigest(),
                    "_status": _read_status(payload_path),
                }
        else:
            out[target.name] = {
                "_raw_len": len(raw),
                "_suffix": payload_path.suffix,
                "_sha256": hashlib.sha256(raw).hexdigest(),
                "_status": _read_status(payload_path),
            }
    return out


def _read_status(payload_path: Path) -> int:
    """Read the captured HTTP status from <payload>.headers.json (default 200)."""
    sidecar = payload_path.with_suffix(payload_path.suffix + ".headers.json")
    if not sidecar.exists():
        return 200
    try:
        meta = json.loads(sidecar.read_text("utf-8"))
        return int(meta.get("status", 200))
    except (json.JSONDecodeError, ValueError, OSError):
        return 200


def cmd_run(argv: List[str]) -> int:
    """One-shot: snapshot every source, classify drift, print per-source plans."""
    from swarm.source_watcher import snapshot_store
    from swarm.source_watcher.scheduler import run_once
    from xops.mock.sources import all_keys, by_key

    keys = argv if argv else all_keys()
    sources = [by_key(k).mock_host for k in keys]  # keyed by mock_host in history

    def fetcher(mock_host: str) -> Any:
        # reverse-lookup: mock_host → source key
        from xops.mock.sources import SOURCES

        for s in SOURCES:
            if s.mock_host == mock_host:
                return _fetch_seed(s.key)
        raise KeyError(mock_host)

    info(f"watch.run: snapshotting {len(sources)} source(s) …")
    ticks = run_once(sources, fetcher=fetcher)
    for tick in ticks:
        if tick.plan is None:
            print(f"  • {tick.source}: {tick.skipped_reason}")
        else:
            print(f"  • {tick.source}: severity={tick.plan.severity}, actions={tick.plan.actions}")
    ok(f"watch.run complete ({len(ticks)} source(s))")
    return 0


def cmd_history(argv: List[str]) -> int:
    """Show snapshot history for one source. Source key passed as SOURCE=<key>."""
    # Support both `watch.py history mackolik.local` and SOURCE=mackolik.local
    import os

    from swarm.source_watcher import snapshot_store

    source = (argv[0] if argv else os.environ.get("SOURCE", "")).strip()
    if not source:
        warn("usage: make watch.history SOURCE=<mock_host>  (e.g. mackolik.local)")
        return 1
    paths = snapshot_store.list_snapshots(source)
    if not paths:
        print(f"(no history for {source})")
        return 0
    print(f"# {source} — {len(paths)} snapshot(s):")
    for p in paths:
        print(f"  {p.name}  ({p.stat().st_size} bytes)")
    return 0


def cmd_sources(_argv: List[str]) -> int:
    from xops.mock.sources import SOURCES

    for s in SOURCES:
        print(f"{s.key:<15} mock={s.mock_host:<22} real={s.real_host}")
    return 0


COMMANDS = {
    "run": cmd_run,
    "history": cmd_history,
    "sources": cmd_sources,
}


def main(argv: List[str]) -> int:
    return dispatch(argv, COMMANDS, script_name="watch.py")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
