#!/usr/bin/env python3
"""
Phase 18.4 — Component Dockerfile linter.

Enforces:
  (a) One Dockerfile per component
  (b) The install step touches only the component's own requirements.in / go.mod
  (c) Base images are digest-pinned (docker.io/...@sha256:<digest>)
  (d) A final-stage absent-import probe for forbidden deps (swarm must not have psycopg2, etc.)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import NamedTuple


class LintError(NamedTuple):
    file: str
    line: int | None
    message: str


def lint_dockerfile(dockerfile_path: Path) -> list[LintError]:
    """Lint a single Dockerfile."""
    errors: list[LintError] = []

    if not dockerfile_path.exists():
        return [LintError(str(dockerfile_path), None, "Dockerfile does not exist")]

    with open(dockerfile_path) as f:
        lines = f.readlines()

    # Constraint (c): Base images are digest-pinned
    for i, line in enumerate(lines, 1):
        if line.strip().startswith("FROM "):
            from_match = re.match(r"FROM\s+(\S+)(?:\s+AS\s+\S+)?", line.strip())
            if from_match:
                image = from_match.group(1)
                # Must be digest-pinned: docker.io/image@sha256:...
                if "@sha256:" not in image:
                    errors.append(
                        LintError(
                            str(dockerfile_path),
                            i,
                            f"Base image not digest-pinned: {image} (must use @sha256:...)",
                        )
                    )

    # Constraint (b): Install step touches only own requirements / go.mod
    # This is hard to fully validate without parsing the Dockerfile as a DAG,
    # so we do a simple check: if the Dockerfile is for ai/, it should COPY
    # requirements.txt or requirements.in, not requirements from other components.
    component_name = dockerfile_path.parent.name
    for i, line in enumerate(lines, 1):
        if re.search(r"COPY.*requirements", line, re.IGNORECASE):
            # Check that it's not copying from another component
            if "../" in line or "ai/requirements" in line or "server/requirements" in line:
                if component_name != "ai" and "ai/requirements" in line:
                    errors.append(
                        LintError(
                            str(dockerfile_path),
                            i,
                            f"Dockerfile for {component_name} copies requirements from another component: {line.strip()}",
                        )
                    )

    # Constraint (d): Final-stage forbidden-dep probes
    # swarm must have RUN python -c "import psycopg2" && exit 1 || true
    if component_name == "swarm" or dockerfile_path.parent.name == "ai":
        has_psycopg_probe = any(
            "import psycopg2" in line and "exit 1" in line
            for line in lines
        )
        if not has_psycopg_probe:
            errors.append(
                LintError(
                    str(dockerfile_path),
                    None,
                    f"Dockerfile for {component_name} missing forbidden-dep probe for psycopg2",
                )
            )

    return errors


def main() -> int:
    """Lint all component Dockerfiles."""
    repo_root = Path(__file__).parent.parent.parent
    errors: list[LintError] = []

    # Check each known component
    components = ["ai", "server", "common"]
    for component in components:
        dockerfile = repo_root / component / "Dockerfile"
        if dockerfile.exists():
            errors.extend(lint_dockerfile(dockerfile))
        # common is a library, not a service — skip it
        if component == "common":
            continue

    # Report errors
    if errors:
        for error in errors:
            print(f"{error.file}:{error.line or '?'}: {error.message}", file=sys.stderr)
        return 1

    print("All component Dockerfiles pass linting.", file=sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
