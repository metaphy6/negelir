"""Phase 10 §10.21.11 — patcher scope boundary proofs.

The patcher scope allow-list is documented in ``CLAUDE.md``. This test
parses that registry and enforces that NLP agent paths are never in-scope.
"""

from __future__ import annotations

from pathlib import Path

from swarm.source_watcher.classifier import SCHEMA_BREAKING
from swarm.source_watcher.planner import ACTION_PAGE_HUMAN, _actions_for
from swarm.source_watcher.agent import SourceWatcherAgent
from swarm.agents.topics import PROOF_FLAG


def _patcher_scope_registry() -> dict[str, str]:
    """Return scope -> path-spec rows from the CLAUDE.md scope table."""
    claude_md = Path(__file__).parents[2] / "CLAUDE.md"
    lines = claude_md.read_text(encoding="utf-8").splitlines()

    registry: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("| `"):
            continue
        parts = [part.strip() for part in stripped.split("|")]
        if len(parts) < 4:
            continue
        scope_cell = parts[1]
        path_cell = parts[2]
        if "`" not in scope_cell:
            continue
        scope = scope_cell.split("`")[1]
        if scope in {"extractor", "schema", "migration", "fixture", "detector_tuning"}:
            registry[scope] = path_cell

    return registry


def test_patcher_scope_excludes_nlp_paths() -> None:
    """Patcher scope table must not include any NLP runtime path."""
    registry = _patcher_scope_registry()
    expected = {"extractor", "schema", "migration", "fixture", "detector_tuning"}
    assert expected.issubset(set(registry)), (
        "CLAUDE.md patcher scope table is incomplete; expected extractor/schema/"
        "migration/fixture/detector_tuning"
    )

    for scope, path_spec in registry.items():
        lowered = path_spec.lower()
        assert "nlp/" not in lowered, (
            f"patcher scope {scope!r} must not include NLP paths: {path_spec}"
        )
        assert "ai/swarm/agents/nlp" not in lowered, (
            f"patcher scope {scope!r} must not include ai/swarm/agents/nlp: {path_spec}"
        )


def test_schema_breaking_path_pages_humans_and_keeps_proof_flag_surface() -> None:
    """Schema-breaking watcher path must keep the human escalation surface."""
    assert ACTION_PAGE_HUMAN in _actions_for(SCHEMA_BREAKING)
    assert PROOF_FLAG in tuple(SourceWatcherAgent.publishes)


def test_patcher_scope_excludes_phase_10_nlp_lang_tr_paths() -> None:
    """Patcher scope docs must not mention the Phase 10 NLP lang_tr tables."""
    claude_md = Path(__file__).parents[2] / "CLAUDE.md"
    text = claude_md.read_text(encoding="utf-8").lower()
    forbidden_paths = [
        "ai/nlp/lang_tr/spelling/",
        "ai/nlp/lang_tr/loanwords/",
        "ai/nlp/lang_tr/fragments/",
        "ai/nlp/lang_tr/preamble_strippers.tr.yaml",
        "ai/nlp/lang_tr/meta_questions.tr.yaml",
        "ai/common/security/tr_pii.py",
    ]
    for forbidden in forbidden_paths:
        assert forbidden not in text, (
            f"CLAUDE.md patcher scope must not mention {forbidden}"
        )
