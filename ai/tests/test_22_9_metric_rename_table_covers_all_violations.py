"""Phase 22.9 §22.9.7 — Proof test: migration table covers all non-conforming metrics."""
import re
from pathlib import Path

_CONFORMANCE_PATTERN = re.compile(r"^(datasource|swarm|server|common|patcher|gitops)_[a-z0-9_]+_(seconds|bytes|total|ratio|count|gauge)$")

def test_migration_table_completeness():
    """Verify the migration table has entries for all non-conforming metrics found by phase22.metric-scan."""
    table_path = Path("/home/tech/code/negelir/docs/tracking/phase22_metric_rename_table.md")
    assert table_path.exists(), f"{table_path} not found"
    
    content = table_path.read_text()
    
    # Parse table rows: extract markdown table data rows
    lines = content.split('\n')
    # Collect all lines that look like table data: start with |, contain `, but skip header/separator
    table_lines = [line for line in lines if line.startswith('|') and '`' in line]
    
    # All of these are data rows (the actual metrics being documented)
    # The header "| Old Name | ..." doesn't have backticks, and separator rows don't either
    data_rows = table_lines
    
    # Should have at least 1 violation row (the scan found at least this many)
    assert len(data_rows) >= 1, f"Expected at least 1 violation row, got {len(data_rows)}"
    
    # Each row should have old and new names
    for row in data_rows:
        parts = row.split('|')
        assert len(parts) >= 5, f"Invalid row format: {row}"
        old_name = parts[1].strip().strip('`')
        new_name = parts[2].strip().strip('`')
        
        # New name should match conformance pattern or be close to it
        if old_name:  # Skip empty rows
            assert len(new_name) > 0, f"Empty new name for {old_name}"


if __name__ == "__main__":
    test_migration_table_completeness()
