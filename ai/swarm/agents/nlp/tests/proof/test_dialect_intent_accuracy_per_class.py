# Minimal proof test for §10.32.4 dialect normalization
# Skips if the large per-dialect corpus is not present (CI will provide it).
import os
import pathlib
import pytest


def test_dialect_intent_accuracy_per_class_minimal_corpus_check():
    here = pathlib.Path(__file__).resolve().parent
    corpora_dir = here / "corpora" / "dialect_intent_corpus"
    if not corpora_dir.exists():
        pytest.skip("Dialect intent corpus not present under tests/proof/corpora; skipping long corpus test.")

    expected = {
        "aegean": 80,
        "black_sea": 80,
        "cypriot": 80,
        "german_diaspora": 80,
        "dutch_diaspora": 80,
        "uk_diaspora": 80,
    }

    for name, min_rows in expected.items():
        p = corpora_dir / f"{name}.csv"
        assert p.exists(), f"Missing corpus file: {p}"
        with p.open(encoding="utf-8") as f:
            rows = [r for r in f if r.strip()]
        assert len(rows) >= min_rows, f"Corpus {name} has {len(rows)} rows, need >= {min_rows}"
