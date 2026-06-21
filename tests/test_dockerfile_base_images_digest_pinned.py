"""Phase 18.4 — Dockerfile base images must be digest-pinned."""
from __future__ import annotations

import re
from pathlib import Path


def test_dockerfile_base_images_digest_pinned() -> None:
    """All FROM statements must use digest-pinned base images (sha256:...)."""
    repo_root = Path(__file__).parent.parent.parent
    components = ["ai", "server"]

    for component in components:
        dockerfile = repo_root / component / "Dockerfile"
        with open(dockerfile) as f:
            lines = f.readlines()

        for i, line in enumerate(lines, 1):
            if line.strip().startswith("FROM "):
                from_match = re.match(r"FROM\s+(\S+)(?:\s+AS\s+\S+)?", line.strip())
                assert from_match, f"Invalid FROM line: {line}"

                image = from_match.group(1)
                assert "@sha256:" in image, (
                    f"{component}/Dockerfile:{i}: Base image not digest-pinned: {image}\n"
                    "Must use format: image@sha256:..."
                )
