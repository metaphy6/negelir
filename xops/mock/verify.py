"""`make mock.verify` — offline integrity check for the seed corpus.

Re-hashes every payload referenced by ``infra/mock/seeds/manifest.json``
and exits non-zero on any drift. Stdlib only; safe in CI.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from xops.mock.manifest import ManifestError, load_manifest, verify  # noqa: E402


def main(argv: list) -> int:
    try:
        manifest = load_manifest()
    except ManifestError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 2

    if not manifest["entries"]:
        print("ℹ️  no seed entries yet — manifest is empty (Phase 2 scaffolding).")
        return 0

    failures = verify(manifest)
    if failures:
        print("❌ seed corpus integrity check failed:", file=sys.stderr)
        for line in failures:
            print(f"   • {line}", file=sys.stderr)
        return 1
    print(f"✅ {len(manifest['entries'])} seed(s) verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
