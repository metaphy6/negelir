"""Phase 22.5 proof test — pyproject.toml has correct root layout configuration."""
import tomllib
from pathlib import Path


def test_22_5_pyproject_toml_correct() -> None:
    """Verify pyproject.toml has correct testpaths, pythonpath, and coverage."""
    pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
    
    with open(pyproject_path, "rb") as f:
        config = tomllib.load(f)
    
    pytest_opts = config["tool"]["pytest"]["ini_options"]
    
    # Verify testpaths
    expected_testpaths = ["tests", "common/tests", "swarm/tests", "server/tests"]
    assert pytest_opts["testpaths"] == expected_testpaths, \
        f"testpaths mismatch: {pytest_opts['testpaths']}"
    
    # Verify pythonpath
    assert pytest_opts["pythonpath"] == ["."], \
        f"pythonpath must be ['.'], got {pytest_opts['pythonpath']}"
    
    # Verify known_first_party
    isort_config = config["tool"]["isort"]
    expected_packages = ["backtest", "common", "enrichment", "model", "nlp", 
                         "orchestrator", "pipeline", "proofreader", "qid", 
                         "scraper", "swarm", "server", "tqu", "trc", "xops"]
    assert sorted(isort_config["known_first_party"]) == sorted(expected_packages), \
        f"known_first_party mismatch"
    
    # Verify coverage source (should NOT include "ai")
    coverage_source = config["tool"]["coverage"]["run"]["source"]
    assert "ai" not in coverage_source, "coverage source must not include 'ai'"
    
    # Verify no "ai" anywhere in the file content
    content = pyproject_path.read_text(encoding="utf-8")
    # Avoid false positives from package names like "brain" — check for "ai/" or "ai" as word
    assert "pythonpath = [\"ai\"]" not in content, "pythonpath must not be ['ai']"
    assert "source = [" in content and "ai" not in content.split("source = [")[1].split("]")[0], \
        "coverage source must not include 'ai'"
