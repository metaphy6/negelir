import json
from pathlib import Path


def test_engines_registry_schema() -> None:
    p = Path("xops/compute/engines.json")
    assert p.exists(), f"Missing engines registry: {p}"
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert doc.get("schema_version") == "1.0"
    engines = doc.get("engines")
    assert isinstance(engines, list) and engines, "engines must be a non-empty list"
    required = {"name", "vendor", "deterministic_when", "known_quirks_ref"}
    for e in engines:
        missing = required - set(e.keys())
        assert not missing, f"engine entry missing keys: {missing} in {e}"
        assert isinstance(e.get("deterministic_when"), list), "deterministic_when must be a list"
