#!/usr/bin/env python3
"""Verify DLQ replay-policy overrides against the security exception registry."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AI_ROOT = REPO_ROOT / "ai"
for path in (str(REPO_ROOT), str(AI_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from swarm.agents.maint.dlq.replay_policy import current_allow_overrides


DOC_PATH = REPO_ROOT / "docs" / "design" / "security_exceptions.md"
_HEADER = ["topic", "reason", "responsible_agent", "phase12_stub", "sign_off"]


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    undocumented: tuple[str, ...]
    stale_docs: tuple[str, ...]


def documented_override_topics(doc_path: Path = DOC_PATH) -> tuple[str, ...]:
    if not doc_path.is_file():
        raise FileNotFoundError(f"security exception registry missing: {doc_path}")

    topics: list[str] = []
    lines = doc_path.read_text(encoding="utf-8").splitlines()
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) != len(_HEADER):
            continue
        lowered = [cell.lower() for cell in cells]
        if lowered == _HEADER:
            continue
        if all(set(cell) <= {"-", ":"} for cell in cells):
            continue
        topic = cells[0]
        if topic:
            topics.append(topic)
    return tuple(topics)


def verify_policy(doc_path: Path = DOC_PATH) -> VerificationResult:
    runtime = tuple(current_allow_overrides())
    docs = documented_override_topics(doc_path)
    runtime_set = set(runtime)
    docs_set = set(docs)
    undocumented = tuple(sorted(runtime_set - docs_set))
    stale_docs = tuple(sorted(docs_set - runtime_set))
    return VerificationResult(
        ok=not undocumented and not stale_docs,
        undocumented=undocumented,
        stale_docs=stale_docs,
    )


def main(argv: list[str] | None = None) -> int:
    _ = argv
    try:
        result = verify_policy()
    except FileNotFoundError as exc:
        print(f"verify.dlq-replay-policy: {exc}", file=sys.stderr)
        return 1

    if result.ok:
        print(
            "verify.dlq-replay-policy: ok "
            f"({len(current_allow_overrides())} override(s) documented)"
        )
        return 0

    print("verify.dlq-replay-policy: FAILED", file=sys.stderr)
    for topic in result.undocumented:
        print(
            f"  undocumented override: {topic} is present in "
            "NEGELIR_MAINT_DLQ_REPLAY_ALLOW_OVERRIDES but missing from "
            "docs/design/security_exceptions.md",
            file=sys.stderr,
        )
    for topic in result.stale_docs:
        print(
            f"  stale docs row: {topic} is documented in "
            "docs/design/security_exceptions.md but not present in "
            "NEGELIR_MAINT_DLQ_REPLAY_ALLOW_OVERRIDES",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
