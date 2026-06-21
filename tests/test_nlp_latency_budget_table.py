"""
Phase 10 §10.12 — NLP latency budget table validation.

Ensures:
- latency_budgets.yaml exists and is loadable
- schema_version is present and valid
- all required budget paths are defined
- p50 <= p95 <= p99 ordering holds
- all budget values are positive integers
"""

import pathlib
import unittest
from typing import Any, Dict, List

import yaml


class TestNlpLatencyBudgetTable(unittest.TestCase):
    """
    Phase 10 §10.12 latency budget table structural validation.
    """

    @classmethod
    def setUpClass(cls):
        cls.budget_path = pathlib.Path(__file__).parent.parent / "nlp" / "data" / "latency_budgets.yaml"

    def test_latency_budgets_yaml_exists(self):
        """latency_budgets.yaml must exist."""
        self.assertTrue(
            self.budget_path.exists(),
            f"latency_budgets.yaml not found at {self.budget_path}"
        )

    def test_latency_budgets_yaml_loadable(self):
        """latency_budgets.yaml must be valid YAML."""
        with open(self.budget_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        
        self.assertIsInstance(data, dict, "Root must be a dict")

    def test_meta_schema_version_present(self):
        """_meta.schema_version must be present."""
        with open(self.budget_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        
        self.assertIn("_meta", data, "_meta section required")
        self.assertIn("schema_version", data["_meta"], "_meta.schema_version required")
        self.assertEqual(data["_meta"]["schema_version"], 1, "schema_version must be 1")

    def test_budgets_list_present(self):
        """budgets list must be present and non-empty."""
        with open(self.budget_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        
        self.assertIn("budgets", data, "budgets list required")
        self.assertIsInstance(data["budgets"], list, "budgets must be a list")
        self.assertGreater(len(data["budgets"]), 0, "budgets must be non-empty")

    def test_all_required_paths_present(self):
        """All 5 required paths from §10.12 table must be present."""
        with open(self.budget_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        
        budgets = data["budgets"]
        
        # Expected (path, condition) pairs from §10.12 table
        required_paths = [
            ("meta.help", "cache_hit"),
            ("data.fixture_lookup", "storage_hit"),
            ("predict.*", "template_only"),
            ("predict.*", "humanized"),
            ("summary.next_week", "10_fixtures"),
        ]
        
        found_paths = [(b["path"], b["condition"]) for b in budgets]
        
        for path, condition in required_paths:
            self.assertIn(
                (path, condition),
                found_paths,
                f"Required budget entry missing: path={path}, condition={condition}"
            )

    def test_all_budgets_have_required_fields(self):
        """Each budget entry must have path, condition, p50_ms, p95_ms, p99_ms."""
        with open(self.budget_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        
        required_fields = {"path", "condition", "p50_ms", "p95_ms", "p99_ms"}
        
        for i, budget in enumerate(data["budgets"]):
            self.assertIsInstance(budget, dict, f"Budget entry {i} must be a dict")
            missing = required_fields - budget.keys()
            self.assertEqual(
                len(missing), 0,
                f"Budget entry {i} (path={budget.get('path')}) missing fields: {missing}"
            )

    def test_all_budgets_have_positive_values(self):
        """All p50_ms, p95_ms, p99_ms values must be positive integers."""
        with open(self.budget_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        
        for i, budget in enumerate(data["budgets"]):
            for field in ["p50_ms", "p95_ms", "p99_ms"]:
                value = budget.get(field)
                self.assertIsInstance(
                    value, int,
                    f"Budget {i} (path={budget['path']}) {field} must be int, got {type(value)}"
                )
                self.assertGreater(
                    value, 0,
                    f"Budget {i} (path={budget['path']}) {field}={value} must be positive"
                )

    def test_all_budgets_have_correct_ordering(self):
        """For each budget entry: p50_ms <= p95_ms <= p99_ms."""
        with open(self.budget_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        
        for i, budget in enumerate(data["budgets"]):
            p50 = budget["p50_ms"]
            p95 = budget["p95_ms"]
            p99 = budget["p99_ms"]
            
            self.assertLessEqual(
                p50, p95,
                f"Budget {i} (path={budget['path']}) p50={p50} must be <= p95={p95}"
            )
            self.assertLessEqual(
                p95, p99,
                f"Budget {i} (path={budget['path']}) p95={p95} must be <= p99={p99}"
            )

    def test_meta_help_cache_hit_fastest(self):
        """meta.help (cache hit) must have the fastest p99 budget."""
        with open(self.budget_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        
        meta_help = next(
            (b for b in data["budgets"] if b["path"] == "meta.help" and b["condition"] == "cache_hit"),
            None
        )
        
        self.assertIsNotNone(meta_help, "meta.help (cache_hit) budget not found")
        
        # meta.help should be the fastest path (lowest p99)
        all_p99s = [b["p99_ms"] for b in data["budgets"]]
        self.assertEqual(
            meta_help["p99_ms"],
            min(all_p99s),
            "meta.help (cache_hit) should have the lowest p99"
        )

    def test_summary_next_week_slowest(self):
        """summary.next_week (10 fixtures) must have the slowest p99 budget."""
        with open(self.budget_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        
        summary = next(
            (b for b in data["budgets"] if b["path"] == "summary.next_week" and b["condition"] == "10_fixtures"),
            None
        )
        
        self.assertIsNotNone(summary, "summary.next_week (10_fixtures) budget not found")
        
        # summary.next_week should be the slowest path (highest p99)
        all_p99s = [b["p99_ms"] for b in data["budgets"]]
        self.assertEqual(
            summary["p99_ms"],
            max(all_p99s),
            "summary.next_week (10_fixtures) should have the highest p99"
        )

    def test_humanized_slower_than_template_only(self):
        """predict.* (humanized) must have higher p50/p95/p99 than predict.* (template_only)."""
        with open(self.budget_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        
        template_only = next(
            (b for b in data["budgets"] if b["path"] == "predict.*" and b["condition"] == "template_only"),
            None
        )
        humanized = next(
            (b for b in data["budgets"] if b["path"] == "predict.*" and b["condition"] == "humanized"),
            None
        )
        
        self.assertIsNotNone(template_only, "predict.* (template_only) budget not found")
        self.assertIsNotNone(humanized, "predict.* (humanized) budget not found")
        
        # Humanized should be slower at every percentile
        self.assertGreater(
            humanized["p50_ms"], template_only["p50_ms"],
            "Humanized p50 should be > template_only p50"
        )
        self.assertGreater(
            humanized["p95_ms"], template_only["p95_ms"],
            "Humanized p95 should be > template_only p95"
        )
        self.assertGreater(
            humanized["p99_ms"], template_only["p99_ms"],
            "Humanized p99 should be > template_only p99"
        )


if __name__ == "__main__":
    unittest.main()
