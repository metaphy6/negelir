"""Phase 22.9 §22.9.7 — Proof test: new metric names are conforming."""
import re
from pathlib import Path

_CONFORMANCE_PATTERN = re.compile(r"^(datasource|swarm|server|common|patcher|gitops)_[a-z0-9_]+_(seconds|bytes|total|ratio|count|gauge)$")

def test_new_metric_names_conform():
    """Verify all new metric names in the migration table conform to Phase 18 pattern."""
    table_path = Path("/home/tech/code/negelir/docs/tracking/phase22_metric_rename_table.md")
    assert table_path.exists()
    
    content = table_path.read_text()
    lines = content.split('\n')
    rows = [line for line in lines if line.startswith('|') and '`' in line][2:]
    
    for row in rows:
        parts = row.split('|')
        if len(parts) < 3:
            continue
        new_name = parts[2].strip().strip('`')
        
        # All new names must match the pattern
        assert _CONFORMANCE_PATTERN.match(new_name), \
            f"New metric name {new_name} does not match conformance pattern"


if __name__ == "__main__":
    test_new_metric_names_conform()
