"""ROADMAP §8.12 — post-test credential-leak sweeper.

Provides:

* :func:`check_output` — scan a log string for credential-shaped patterns;
  returns a list of ``(line_no, pattern_name, matched_fragment)`` triples.
* A pytest plugin (``_SecretSmokePlugin``) that sweeps WARN/ERROR log records
  captured during the session and fails the run if any credential pattern is
  found.  Registered via :func:`pytest_configure` so any conftest that imports
  this module automatically arms the sweep.

Pattern philosophy
------------------
Patterns are tuned to real credential formats (AWS key IDs, 40-char secrets,
bearer tokens, long ``key=value`` literals).  Short unit-test placeholders
("ak", "sk", "bkt", "us-east-1") do **not** match because the patterns enforce
a minimum meaningful length.  If a test legitimately uses a realistic-length
fake credential, prefix it with "FAKE_" and the scanner will skip it.
"""

from __future__ import annotations

import re
import warnings

# ---- credential patterns -------------------------------------------------------

# AWS access key ID: AKIA + exactly 16 uppercase alphanumeric characters.
_AWS_KEY_ID = re.compile(r"\bAKIA[A-Z0-9]{16}\b")

# AWS-style secret access key: exactly 40-char base64url string.
# The negative lookbehind skips any value prefixed with "FAKE_".
_AWS_SECRET = re.compile(r"(?<!FAKE_)[A-Za-z0-9+/]{40}(?:[A-Za-z0-9+/=]|\b)")

# Bearer / Authorization header tokens long enough to be real (>= 20 chars).
_BEARER_TOKEN = re.compile(r"Bearer\s+[A-Za-z0-9\-_\.]{20,}")

# key-value patterns like ``secret=RealSecretValue`` (value >= 8 chars).
_KV_SECRET = re.compile(
    r"(?i)(?:password|secret|access.?key|secret.?key)\s*=\s*[^\s\"\']{8,}"
)

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("aws_key_id", _AWS_KEY_ID),
    ("aws_secret", _AWS_SECRET),
    ("bearer_token", _BEARER_TOKEN),
    ("kv_secret", _KV_SECRET),
]

# ---- public API ----------------------------------------------------------------


def check_output(text: str) -> list[tuple[int, str, str]]:
    """Scan *text* for credential-shaped patterns.

    Returns a list of ``(line_no, pattern_name, matched_fragment)`` for every
    suspicious line found.  Returns an empty list when the text is clean.
    """
    hits: list[tuple[int, str, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for name, pattern in PATTERNS:
            match = pattern.search(line)
            if match:
                hits.append((lineno, name, match.group()))
                break  # one hit per line is enough
    return hits


# ---- pytest plugin -------------------------------------------------------------


class _SecretSmokePlugin:
    """Collect WARNING/ERROR log records during the session; fail on leaks."""

    def __init__(self) -> None:
        self._captured: list[str] = []

    def pytest_runtest_logreport(self, report) -> None:
        for title, content in getattr(report, "sections", []):
            if "log" in title.lower():
                self._captured.append(content)

    def pytest_sessionfinish(self, session, exitstatus) -> None:
        combined = "\n".join(self._captured)
        if not combined.strip():
            return
        hits = check_output(combined)
        if hits:
            formatted = "\n".join(
                f"  line {ln}: [{pat}] {frag!r}" for ln, pat, frag in hits
            )
            msg = (
                f"secret_smoke: {len(hits)} potential credential leak(s) detected "
                f"in WARN/ERROR test-log output:\n{formatted}"
            )
            warnings.warn(msg, stacklevel=1)
            try:
                session.exitstatus = max(int(session.exitstatus), 1)
            except (TypeError, ValueError):
                pass


def pytest_configure(config) -> None:
    """Register the secret-smoke plugin when this module is imported by a conftest."""
    config.pluginmanager.register(_SecretSmokePlugin(), "secret_smoke")
