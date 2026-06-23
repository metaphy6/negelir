"""Phase 22.9 §22.9.7 — Proof test: metric names are string literals, not dynamic."""
import ast
import inspect
from pathlib import Path

def test_metric_names_are_string_literals():
    """Verify metric names are string literals, not dynamic __name__/__module__ references."""
    telemetry_path = Path("/home/tech/code/negelir/common/telemetry.py")
    assert telemetry_path.exists()
    
    content = telemetry_path.read_text()
    tree = ast.parse(content)
    
    # Find all Counter/Gauge/Histogram/Summary/Info calls
    found_metrics = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in ("Counter", "Gauge", "Histogram", "Summary", "Info"):
                found_metrics = True
                # First argument should be a string literal
                if node.args:
                    first_arg = node.args[0]
                    assert isinstance(first_arg, ast.Constant), f"Metric name not a string literal: {ast.unparse(first_arg)}"
                    assert isinstance(first_arg.value, str), f"Metric name not a string: {first_arg.value}"
    
    assert found_metrics, "No metrics found in telemetry.py"


if __name__ == "__main__":
    test_metric_names_are_string_literals()
