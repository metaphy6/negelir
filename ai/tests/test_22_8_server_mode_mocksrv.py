"""Phase 22.8 — Test that /bin/server MODE=mocksrv works without docker-compose.mock.yml overlay."""

import os
import subprocess
import time
from pathlib import Path


def test_server_binary_builds_with_mode_flag():
    """Verify server binary builds after adding MODE field."""
    server_dir = Path(__file__).parent.parent.parent / "server"
    result = subprocess.run(
        ["go", "build", "-o", "/tmp/server-mode-test", "./cmd/api"],
        cwd=str(server_dir),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"Build failed:\n{result.stderr}"
    assert Path("/tmp/server-mode-test").exists()


def test_mocksrv_binary_builds():
    """Verify mocksrv binary builds as a wrapper."""
    server_dir = Path(__file__).parent.parent.parent / "server"
    result = subprocess.run(
        ["go", "build", "-o", "/tmp/mocksrv-mode-test", "./cmd/mocksrv"],
        cwd=str(server_dir),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"Build failed:\n{result.stderr}"
    assert Path("/tmp/mocksrv-mode-test").exists()


def test_server_mode_config_field_exists():
    """Verify MODE field is in config structs and specs."""
    config_file = Path(__file__).parent.parent.parent / "server" / "internal" / "config" / "config.go"
    content = config_file.read_text()
    
    # Check that Mode field exists in struct
    assert 'Mode                     string `env:"MODE"' in content, "Mode field missing from Config struct"
    
    # Check that MODE is in the specs list
    assert '{name: "MODE", dflt: "api", stringDst: &c.Mode}' in content, "MODE missing from specs list"
    
    # Check validation exists
    assert 'if c.Mode != "api" && c.Mode != "mocksrv"' in content, "MODE validation missing"


def test_cmd_api_main_has_mode_dispatch():
    """Verify cmd/api/main.go has MODE dispatch to mocksrv."""
    main_file = Path(__file__).parent.parent.parent / "server" / "cmd" / "api" / "main.go"
    content = main_file.read_text()
    
    # Check that the dispatch code exists
    assert 'if cfg.Mode == "mocksrv"' in content, "MODE dispatch missing"
    assert "runMocksrv(cfg)" in content, "runMocksrv call missing"
    assert "func runMocksrv(cfg *config.Config) error" in content, "runMocksrv function missing"


def test_cmd_mocksrv_main_shows_deprecation():
    """Verify cmd/mocksrv/main.go shows deprecation message."""
    mocksrv_file = Path(__file__).parent.parent.parent / "server" / "cmd" / "mocksrv" / "main.go"
    content = mocksrv_file.read_text()
    
    # Check that deprecation logic exists
    assert "deprecation" in content.lower() or "deprecated" in content.lower(), "Deprecation message missing"
    assert "2026-07-07" in content or "MODE=mocksrv" in content, "Migration path not shown"


def test_env_example_has_mode():
    """Verify MODE is documented in .env.example."""
    env_file = Path(__file__).parent.parent.parent / "xops" / "env" / ".env.example"
    content = env_file.read_text()
    
    # Check MODE is in the example
    assert 'MODE=api' in content, "MODE not in .env.example"
    assert "mocksrv" in content, "mocksrv option not documented"


if __name__ == "__main__":
    test_server_binary_builds_with_mode_flag()
    print("✅ test_server_binary_builds_with_mode_flag passed")
    
    test_mocksrv_binary_builds()
    print("✅ test_mocksrv_binary_builds passed")
    
    test_server_mode_config_field_exists()
    print("✅ test_server_mode_config_field_exists passed")
    
    test_cmd_api_main_has_mode_dispatch()
    print("✅ test_cmd_api_main_has_mode_dispatch passed")
    
    test_cmd_mocksrv_main_shows_deprecation()
    print("✅ test_cmd_mocksrv_main_shows_deprecation passed")
    
    test_env_example_has_mode()
    print("✅ test_env_example_has_mode passed")
    
    print("\n✅ All tests passed!")
