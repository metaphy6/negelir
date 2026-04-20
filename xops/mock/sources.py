"""Source registry for the Phase 2 mock stack.

Each ``Source`` declares the upstream we mirror, the local mock vhost,
and the URLs to capture. Adding a new source means appending an entry
here — no code changes anywhere else.

Real-internet hits are gated by ``profile=="real"``; tests use
``profile=="mock"`` and the seed corpus.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass(frozen=True)
class CaptureTarget:
    """One URL to fetch, store, and serve back via mocksrv."""
    name: str             # short slug, becomes the relative file path stem
    path: str             # path on the upstream (no scheme/host)
    content_type: str = "text/html; charset=utf-8"
    method: str = "GET"


@dataclass(frozen=True)
class Source:
    """An upstream we mirror through the mock stack."""
    key: str              # short id used in seed paths and logs
    real_host: str        # production hostname, e.g. "www.mackolik.com"
    mock_host: str        # local host, e.g. "mackolik.local"
    description: str
    targets: Tuple[CaptureTarget, ...] = field(default_factory=tuple)

    def real_url(self, target: CaptureTarget) -> str:
        return f"https://{self.real_host}{target.path}"

    def mock_url(self, target: CaptureTarget) -> str:
        return f"https://{self.mock_host}{target.path}"


# ── Registry ──────────────────────────────────────────────────
# Targets are minimal on purpose — Phase 2.4 will grow them per league
# alongside the scraper changes. The registry stays declarative.

SOURCES: Tuple[Source, ...] = (
    Source(
        key="mackolik",
        real_host="www.mackolik.com",
        mock_host="mackolik.local",
        description="TR Süper Lig fixtures, scores, lineups (HTML).",
        targets=(
            CaptureTarget(name="home", path="/"),
        ),
    ),
    Source(
        key="nesine",
        real_host="www.nesine.com",
        mock_host="nesine.local",
        description="Bulletin / odds (HTML + XHR JSON).",
        targets=(
            CaptureTarget(name="home", path="/"),
        ),
    ),
    Source(
        key="tff",
        real_host="www.tff.org",
        mock_host="tff.local",
        description="Official TR Football Federation (HTML).",
        targets=(
            CaptureTarget(name="home", path="/"),
        ),
    ),
    Source(
        key="openfootball",
        real_host="raw.githubusercontent.com",
        mock_host="openfootball.local",
        description="openfootball/football.json datasets (JSON, MIT-licensed).",
        targets=(
            CaptureTarget(
                name="tr1_2024_25",
                path="/openfootball/football.json/master/2024-25/tr.1.json",
                content_type="application/json",
            ),
        ),
    ),
)


def by_key(key: str) -> Source:
    for s in SOURCES:
        if s.key == key:
            return s
    raise KeyError(f"unknown source: {key!r}; known: {[s.key for s in SOURCES]}")


def all_keys() -> List[str]:
    return [s.key for s in SOURCES]
