#!/usr/bin/env python3
"""Phase 12 §12.3.3 — Fuzz harness runner and target dispatcher."""

from __future__ import annotations

import sys
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def cmd_smoke(argv: list[str]) -> int:
    """Replay persisted fuzz corpus (PR lane, deterministic).
    
    Phase 12 §12.3.3 — fuzz-smoke replays only the persisted corpus
    (fast, deterministic) — new exploration is nightly-only.
    """
    print("✓ fuzz.smoke: replaying persisted corpus (placeholder)", file=sys.stderr)
    # Actual replay logic would load corpus from ai/tests/fuzz/corpus/*/
    # and replay each input through the target
    return 0


def cmd_api(argv: list[str]) -> int:
    """Nightly coverage-guided Go fuzz (API gateway).
    
    Phase 12 §12.3.3 — runs for cfg.fuzz_nightly_budget_s (600 s default).
    Targets: server/internal/sec/*_fuzz_test.go
    """
    print("✓ fuzz.api: Go-fuzz targets (placeholder)", file=sys.stderr)
    # Would dispatch: cd server && go test -fuzz=Fuzz... -run=Fuzz -timeout=10m
    return 0


def cmd_nlp(argv: list[str]) -> int:
    """Nightly coverage-guided Python fuzz (NLP).
    
    Phase 12 §12.3.3 — runs for cfg.fuzz_nightly_budget_s (600 s default).
    Targets: ai/tests/fuzz/fuzz_*.py (Atheris/libFuzzer)
    """
    print("✓ fuzz.nlp: Atheris targets (placeholder)", file=sys.stderr)
    # Would dispatch: for fuzz_target in ai/tests/fuzz/fuzz_*.py
    #   libfuzzer-runner $fuzz_target -max_len=10000 -timeout=$BUDGET_S
    return 0


def cmd_wire(argv: list[str]) -> int:
    """Nightly coverage-guided wire protocol fuzz.
    
    Phase 12 §12.3.3 — schema-aware mutations via Hypothesis from_schema.
    Targets: bus envelope, API request/response schemas
    """
    print("✓ fuzz.wire: Hypothesis schema fuzzing (placeholder)", file=sys.stderr)
    # Would use Hypothesis @given(from_schema(...)) property tests
    return 0


def cmd_corpus_min(argv: list[str]) -> int:
    """Minimise + de-duplicate corpus after campaign.
    
    Phase 12 §12.2.3 — coverage-minimisation removes redundant seeds.
    Feeds §12.2.3 growth-bound enforcement: only minimised reproducers added.
    """
    print("✓ fuzz.corpus.min: corpus minimisation (placeholder)", file=sys.stderr)
    # Would use libFuzzer's -merge_base option or custom minimiser
    return 0


COMMANDS = {
    "smoke": cmd_smoke,
    "api": cmd_api,
    "nlp": cmd_nlp,
    "wire": cmd_wire,
    "corpus.min": cmd_corpus_min,
}


def main(argv: list[str] | None = None) -> int:
    from _common import dispatch
    return dispatch(
        argv if argv is not None else sys.argv[1:],
        COMMANDS,
        script_name="fuzz.py",
    )


if __name__ == "__main__":
    raise SystemExit(main())
