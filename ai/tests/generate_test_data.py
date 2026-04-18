"""
Generate deterministic test-only dataset snapshots.
Usage:
  python -m tests.generate_test_data --matches 200 --output ../data/test_fixture_real_like.json
"""

import argparse
import json

from tests.fixtures import generate_synthetic_dataset


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate test-only fixture dataset")
    parser.add_argument("--matches", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    X, y = generate_synthetic_dataset(n_matches=args.matches, seed=args.seed)
    payload = {
        "generated_for": "tests",
        "matches": args.matches,
        "seed": args.seed,
        "features": X.to_dict(orient="records"),
        "labels": y.tolist(),
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"Wrote test fixture: {args.output} ({args.matches} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
