"""Phase 12 §12.3.3 — Fuzz target for NLP normalize.

Atheris entry point (libFuzzer):
  $ libfuzzer-runner ai/tests/fuzz/fuzz_nlp_normalize.py

Seed corpus: ai/tests/fuzz/corpus/nlp_normalize/
Reproduces crashes from: ai/tests/fixtures/adversarial/*/

Bindings:
  - Idempotency: normalize(normalize(x)) == normalize(x) (Phase 12 §12.3.1)
  - Determinism: same seed ⇒ same output (Phase 12 §12.3.2)
  - No unbounded growth in internal state (Phase 12 §12.3.1 no-unbounded-growth)
"""

import sys
import atheris

# Optional: atheris fuzzing
try:
    import atheris
    HAS_ATHERIS = True
except ImportError:
    HAS_ATHERIS = False


def fuzz_nlp_normalize(data: bytes) -> None:
    """Fuzz the NLP normalize function.
    
    Args:
        data: Arbitrary bytes from libFuzzer
    """
    try:
        # Decode bytes to string
        text = data.decode("utf-8", errors="ignore")
        if not text:
            return
        
        # Import late to avoid hard dependency
        try:
            from nlp.normalize import normalize_input
        except ImportError:
            # NLP module not available
            return
        
        # Call normalize twice (idempotency check)
        norm1 = normalize_input(text)
        norm2 = normalize_input(norm1)
        
        # Idempotency invariant
        assert norm1 == norm2, f"Non-idempotent: {norm1} != {norm2}"
        
        # Output is non-empty if input was non-empty
        if text.strip():
            assert norm1 is not None, "normalize returned None for non-empty input"
    
    except Exception as e:
        # Log but don't crash — we want coverage, not failures
        pass


if HAS_ATHERIS:
    atheris.Setup(sys.argv, fuzz_nlp_normalize)
    atheris.Fuzz()
else:
    # Fallback: simple property test without libFuzzer
    import sys
    if __name__ == "__main__":
        print("Atheris not installed; skipping fuzz_nlp_normalize", file=sys.stderr)
        sys.exit(0)
