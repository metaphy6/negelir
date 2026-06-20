"""Seccomp sandbox profile for extractors running on unverified sources."""

import os
from pathlib import Path

# Path to the seccomp sandbox profile JSON
SANDBOX_PROFILE = str(Path(__file__).parent / "extractor_sandbox.json")


def get_sandbox_profile() -> str:
    """Get path to sandbox profile."""
    return SANDBOX_PROFILE


def sandbox_is_available() -> bool:
    """Check if seccomp sandbox is available on this system."""
    try:
        # Check for seccomp library / kernel support
        import ctypes
        ctypes.CDLL("libseccomp.so.2")
        return True
    except (OSError, ImportError):
        return False
