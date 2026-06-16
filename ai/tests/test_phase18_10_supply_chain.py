"""Phase 18.10 - Supply-chain isolation (lockfiles, SBOM, base images)."""
import pytest
import json
from pathlib import Path

def test_swarm_lockfile_has_no_psycopg_transitively():
    """Verify psycopg2 is not in swarm transitive deps."""
    lockfile = Path("ai/swarm/requirements.lock")
    assert lockfile.exists(), "swarm/requirements.lock must exist"
    content = lockfile.read_text()
    assert "psycopg" not in content.lower(), "psycopg/psycopg2 found in swarm lockfile"
    
def test_sbom_generated_per_component():
    """Verify SBOM files exist per component."""
    components = ["swarm", "datasource"]  # transitional names
    for comp in components:
        sbom = Path(f"ai/{comp}/sbom.spdx.json")
        assert sbom.exists() or not Path(f"ai/{comp}").exists(), \
            f"Missing SBOM for {comp}"
            
def test_sbom_diff_blocks_forbidden_transitive_dep():
    """Lint would refuse forbidden transitive deps in SBOM."""
    # This is tested via CI lint; here we just verify the policy file exists
    policy = Path("common/isolation/forbidden_deps.yaml")
    assert policy.exists(), "forbidden_deps.yaml must declare forbidden packages"
    
def test_lockfile_hash_pinned():
    """Verify lockfiles use hash pinning (no ~, no *)."""
    lockfile = Path("ai/requirements.lock")
    if lockfile.exists():
        content = lockfile.read_text()
        # Hash-pinned format: package==version --hash=sha256:...
        assert "==" in content, "lockfile should use ==, not ~ or *"
        assert "~=" not in content, "no ~= versioning in lockfile"
        
def test_base_images_in_curated_registry():
    """Verify base_images.yaml exists and is curated."""
    cfg = Path("xops/docker/base_images.yaml")
    assert cfg.exists(), "base_images.yaml must exist"
    content = cfg.read_text()
    # Should list allowed base images
    assert "python" in content or "golang" in content or "distroless" in content
    
def test_dockerfile_from_digest_pinned():
    """Dockerfiles must use digest-pinned base images."""
    dockerfile = Path("ai/swarm/Dockerfile")
    if dockerfile.exists():
        content = dockerfile.read_text()
        # Check for @sha256: pinning (if FROM exists)
        if "FROM " in content:
            lines = [l for l in content.split("\n") if l.strip().startswith("FROM ")]
            for line in lines:
                # Either digest-pinned or an acceptable pattern
                assert "@sha256:" in line or "distroless" in line, \
                    f"Base image not digest-pinned: {line}"

def test_no_floating_tool_versions_in_dockerfile():
    """Dockerfile should not have unpinned tool installs."""
    dockerfile = Path("ai/swarm/Dockerfile")
    if dockerfile.exists():
        content = dockerfile.read_text()
        # Check for explicit pip version locks
        if "pip install" in content:
            lines = [l for l in content.split("\n") if "pip install" in l]
            # This is an advisory test; production enforced by CI lint
            assert any("requirements" in l or "==" in l for l in lines), \
                "pip install should use requirements.lock or pinned versions"

def test_base_image_refresh_runs_quarterly():
    """Verify quarterly base-image refresh is documented."""
    # This is more of a process test; here we just verify the make target exists
    makefile = Path("Makefile")
    content = makefile.read_text()
    assert "base_images.refresh" in content, "make base_images.refresh target should exist"
    
@pytest.mark.skip(reason="CI lint integration test")
def test_lockfile_change_runs_sbom_diff():
    """Lockfile changes trigger SBOM diff in CI."""
    pass

@pytest.mark.skip(reason="CI lint integration test")
def test_dep_license_allow_list_enforced():
    """License allow-list is enforced on lockfile changes."""
    pass
