"""Phase 18.7 ledger #18 proof test: metric naming documentation exists."""

from pathlib import Path


def test_metric_naming_doc_exists() -> None:
    """Verify common/observability/metric_naming.md exists and is complete."""
    doc_path = Path("/home/tech/code/negelir/common/observability/metric_naming.md")
    assert doc_path.exists(), f"{doc_path} does not exist"
    
    content = doc_path.read_text()
    
    # Verify key sections
    required_sections = [
        "# Metric Naming Convention",
        "Pattern:",
        "Components",
        "Subsystems",
        "Verbs",
        "Units",
        "Labels",
        "CI Enforcement",
    ]
    
    for section in required_sections:
        assert section in content, f"Missing section: {section}"
    
    print(f"✓ Metric naming doc exists with all required sections ({len(content)} bytes)")


if __name__ == "__main__":
    test_metric_naming_doc_exists()
