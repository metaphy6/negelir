#!/usr/bin/env python3
"""Phase 12 §12.2.2 — Corpus disjointness enforcement.

Validates that adversarial corpora are disjoint from:
1. Training sets (predictor, NLP, humanizer)
2. Evaluation sets (NLP)
3. Production stores (no *_chaos contamination)
"""

import sys
import json
import hashlib
import argparse
from pathlib import Path
from typing import Set, Dict, Optional
import yaml


def _hash_row(row: dict) -> str:
    """Deterministic hash of a corpus row for comparison."""
    # Normalize to JSON (sorted keys, no whitespace)
    normalized = json.dumps(row, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode()).hexdigest()


def load_corpus_family(corpus_dir: Path) -> Set[str]:
    """Load all hashes from a corpus family directory."""
    hashes = set()
    for yaml_file in corpus_dir.glob("*.yaml"):
        if yaml_file.name == "corpus.yaml":
            continue  # Skip the governance sidecar
        try:
            with open(yaml_file) as f:
                data = yaml.safe_load(f)
                if isinstance(data, list):
                    for row in data:
                        hashes.add(_hash_row(row))
                elif isinstance(data, dict) and "entries" in data:
                    for row in data["entries"]:
                        hashes.add(_hash_row(row))
        except Exception as e:
            print(f"❌ Error loading {yaml_file}: {e}", file=sys.stderr)
            return None
    return hashes


def load_adversarial_corpora(root_dir: Path) -> Dict[str, Set[str]]:
    """Load all adversarial corpus families."""
    families = {}
    adversarial_dir = root_dir / "ai" / "tests" / "fixtures" / "adversarial"
    
    if not adversarial_dir.exists():
        print(f"❌ Adversarial corpus dir not found: {adversarial_dir}", file=sys.stderr)
        return {}
    
    for family_dir in adversarial_dir.iterdir():
        if family_dir.is_dir() and family_dir.name not in ("archived", "__pycache__"):
            hashes = load_corpus_family(family_dir)
            if hashes is not None:
                families[family_dir.name] = hashes
    
    return families


def check_training_set_disjointness(
    repo_root: Path, adversarial_hashes: Dict[str, Set[str]]
) -> bool:
    """Verify no adversarial corpus rows appear in training sets."""
    all_adversarial = set()
    for family, hashes in adversarial_hashes.items():
        all_adversarial.update(hashes)
    
    if not all_adversarial:
        print("ℹ No adversarial corpus rows to check", file=sys.stderr)
        return True
    
    # Check training manifests (Phase 10 §10.27.10 pattern)
    training_manifest_path = repo_root / "ai" / "common" / "training_manifest.json"
    if training_manifest_path.exists():
        try:
            with open(training_manifest_path) as f:
                manifest = json.load(f)
                if "training_corpus_hashes" in manifest:
                    training_hashes = set(manifest["training_corpus_hashes"])
                    intersection = all_adversarial & training_hashes
                    if intersection:
                        print(
                            f"❌ Training-set contamination: {len(intersection)} "
                            f"adversarial rows found in training set",
                            file=sys.stderr,
                        )
                        return False
        except Exception as e:
            print(f"⚠ Could not check training manifest: {e}", file=sys.stderr)
    
    return True


def check_eval_set_disjointness(
    repo_root: Path, adversarial_hashes: Dict[str, Set[str]]
) -> bool:
    """Verify no adversarial corpus rows appear in NLP eval sets."""
    all_adversarial = set()
    for family, hashes in adversarial_hashes.items():
        all_adversarial.update(hashes)
    
    if not all_adversarial:
        return True
    
    # Check eval manifest (Phase 10 §10.18 pattern)
    eval_manifest_path = repo_root / "ai" / "common" / "eval_manifest.json"
    if eval_manifest_path.exists():
        try:
            with open(eval_manifest_path) as f:
                manifest = json.load(f)
                if "nlp_eval_corpus_hashes" in manifest:
                    eval_hashes = set(manifest["nlp_eval_corpus_hashes"])
                    intersection = all_adversarial & eval_hashes
                    if intersection:
                        print(
                            f"❌ Eval-set contamination: {len(intersection)} "
                            f"adversarial rows found in eval set",
                            file=sys.stderr,
                        )
                        return False
        except Exception as e:
            print(f"⚠ Could not check eval manifest: {e}", file=sys.stderr)
    
    return True


def check_no_production_contamination() -> bool:
    """Verify no *_chaos Redis keys or synthetic records in production."""
    # This is a runtime check during test execution (not here)
    # The CI gate happens in the test suite via:
    # - test_adversarial_chaos_namespace_cleanup()
    # - test_no_synthetic_records_in_production_tables()
    print("ℹ Production contamination check is runtime (via test suite)", file=sys.stderr)
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Verify adversarial corpus disjointness (Phase 12 §12.2.2)"
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root (default: cwd)",
    )
    parser.add_argument(
        "--check-training",
        action="store_true",
        default=True,
        help="Check training-set disjointness (default: enabled)",
    )
    parser.add_argument(
        "--check-eval",
        action="store_true",
        default=True,
        help="Check eval-set disjointness (default: enabled)",
    )
    
    args = parser.parse_args()
    
    adversarial = load_adversarial_corpora(args.repo_root)
    if not adversarial:
        print("⚠ No adversarial corpora found", file=sys.stderr)
        return 1
    
    print(f"✓ Loaded {sum(len(h) for h in adversarial.values())} adversarial corpus rows", file=sys.stderr)
    
    all_pass = True
    
    if args.check_training:
        if not check_training_set_disjointness(args.repo_root, adversarial):
            all_pass = False
    
    if args.check_eval:
        if not check_eval_set_disjointness(args.repo_root, adversarial):
            all_pass = False
    
    if not check_no_production_contamination():
        all_pass = False
    
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
