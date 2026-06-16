"""Phase 18.4 — Dockerfile install steps must touch only own requirements."""
from __future__ import annotations

import re
from pathlib import Path


def test_component_dockerfile_only_touches_own_deps() -> None:
    """Each Dockerfile's install step copies only its own requirements/go.mod."""
    repo_root = Path(__file__).parent.parent.parent
    components = {"ai": "requirements.txt", "server": "go.mod"}

    for component, dep_file in components.items():
        dockerfile = repo_root / component / "Dockerfile"
        with open(dockerfile) as f:
            lines = f.readlines()

        for i, line in enumerate(lines, 1):
            if "COPY" in line and ("requirements" in line.lower() or "go.mod" in line or "go.sum" in line):
                # Ensure it's not cross-component
                if "../" in line:
                    raise AssertionError(
                        f"{component}/Dockerfile:{i}: COPY crosses component boundary: {line.strip()}"
                    )

                # Check that if it's copying deps, it's the right component's
                if component == "ai" and "COPY" in line:
                    if "go.mod" in line or "go.sum" in line:
                        raise AssertionError(
                            f"{component}/Dockerfile:{i}: Copying Go files in Python component: {line.strip()}"
                        )

                if component == "server" and "COPY" in line:
                    if "requirements" in line.lower():
                        raise AssertionError(
                            f"{component}/Dockerfile:{i}: Copying requirements in Go component: {line.strip()}"
                        )
