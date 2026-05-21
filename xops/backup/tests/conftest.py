"""Pytest config for xops/backup/tests — registers the secret-smoke plugin."""

from __future__ import annotations

import xops.backup.secret_smoke as _secret_smoke  # registers plugin via pytest_configure  # noqa: F401
