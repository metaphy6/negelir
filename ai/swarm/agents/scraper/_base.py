"""Phase 4.1 — Scraper agent base.

A scraper agent subscribes to `scrape.request` and emits `scrape.raw`.
It owns:

  * Source-name filter (only handle requests for its own `source`)
  * Mock/real profile resolution via `cfg.scrape_profile`
  * Token-bucket rate limit (in-process; Redis-backed bucket lives
    one layer up under xops/, deferred to Phase 8)
  * Retry / DLQ semantics inherited from `AgentRunner`
  * 404 → `proof.flag` (data missing upstream); 5xx after N retries
    → DLQ + a proof.flag note (real `sec.alert` lives behind Phase 6)

Concrete scrapers (mackolik/nesine/tff/openfootball) subclass
`ScraperAgentBase` and override `fetch()` only. Everything else —
envelope handling, sha256, mock URL substitution — lives here so all
sources behave the same way.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Callable, Iterable, Protocol

from ai.common.config import cfg

from ...sdk.types import Message
from ..payloads import ProofFlagKind, ScrapeRaw, ScrapeRequest
from ..topics import PROOF_FLAG, SCRAPE_RAW, SCRAPE_REQUEST

_log = logging.getLogger(__name__)


class FetchClient(Protocol):
    """Minimal fetch interface so tests can inject fakes."""

    def get(self, url: str, *, timeout: int) -> "FetchResponse": ...


class FetchResponse(Protocol):
    status_code: int
    content: bytes
    headers: dict[str, str]


class _RealFetchClient:
    """Default ``requests``-based client. Imported lazily."""

    def get(self, url: str, *, timeout: int) -> FetchResponse:  # pragma: no cover - thin wrapper
        import requests

        resp = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": cfg.scrape_user_agent},
        )
        return resp  # type: ignore[return-value]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ScraperAgentBase:
    """Base class for `scraper.<source>.v1` agents.

    Subclasses set `source_key` (matches `ScrapeRequest.source`) and
    `mock_host` / `real_host` (used by ``resolve_url``). They override
    ``fetch()`` only when the default HTTP path is insufficient.
    """

    source_key: str = ""
    mock_host: str = ""
    real_host: str = ""

    # SDK contract — names visible to the runner / registry. Tuples
    # so a subclass cannot accidentally mutate the parent's list.
    subscribes: tuple[str, ...] = (SCRAPE_REQUEST,)
    publishes: tuple[str, ...] = (SCRAPE_RAW, PROOF_FLAG)

    def __init__(
        self,
        *,
        client: FetchClient | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not self.source_key:
            raise ValueError(
                f"{type(self).__name__}: source_key must be set on subclass"
            )
        self.name = f"scraper.{self.source_key}.v1"
        self._client = client or _RealFetchClient()
        self._clock = clock
        self._sleep = sleep
        # Token bucket per-source: at most one fetch per `scrape_rate_limit` sec.
        self._next_allowed_at = 0.0

    # ── Bus contract ────────────────────────────────────────────────
    def handle(self, msg: Message) -> Iterable[Message]:
        try:
            req = ScrapeRequest.from_dict(msg.payload)
        except (KeyError, TypeError, ValueError) as exc:
            _log.warning("%s: malformed scrape.request: %s", self.name, exc)
            return ()

        if req.source != self.source_key:
            # Not ours — silently ignore; Redis Streams consumer-group
            # fan-out means each scraper sees every request.
            return ()

        self._wait_for_token()

        url = self.resolve_url(req.target)
        try:
            resp = self.fetch(url)
        except Exception as exc:  # noqa: BLE001 — runner converts to retry/DLQ
            _log.error("%s: fetch failed for %s: %s", self.name, url, exc)
            raise

        sha = hashlib.sha256(resp.content).hexdigest()
        content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip()

        if 200 <= resp.status_code < 300:
            raw = ScrapeRaw(
                source=self.source_key,
                target=req.target,
                bytes_sha256=sha,
                http_status=resp.status_code,
                content_type=content_type,
                bytes_b64=base64.b64encode(resp.content).decode("ascii"),
                league_id=req.league_id,
                competition_id=req.competition_id,
                fetched_at=_utc_now_iso(),
            )
            return (
                Message.new(
                    SCRAPE_RAW,
                    raw.as_dict(),
                    producer=self.name,
                    trace_id=msg.envelope.trace_id,
                ),
            )

        if resp.status_code == 404:
            return (
                Message.new(
                    PROOF_FLAG,
                    {
                        "source": self.source_key,
                        "target": req.target,
                        "kind": ProofFlagKind.UPSTREAM_MISSING,
                        "http_status": 404,
                    },
                    producer=self.name,
                    trace_id=msg.envelope.trace_id,
                ),
            )

        # 5xx and other failures: raise so the runner counts retries
        # and ultimately DLQs the message.
        raise RuntimeError(
            f"{self.name}: upstream {url} returned {resp.status_code}"
        )

    # ── Helpers subclasses may override ─────────────────────────────
    def fetch(self, url: str) -> FetchResponse:
        return self._client.get(url, timeout=cfg.scrape_http_timeout)

    def resolve_url(self, target: str) -> str:
        """Map a target spec to an absolute URL.

        ``target`` may be a path (``/foo``) or a full URL. In the
        ``mock`` profile, the host is rewritten to ``mock_host``; in
        the ``real`` profile we hit ``real_host``. Tests therefore
        need only declare paths.
        """
        profile = self._scrape_profile()
        host = self.mock_host if profile == "mock" else self.real_host
        if target.startswith("http://") or target.startswith("https://"):
            return target  # caller supplied a fully-qualified URL
        if not target.startswith("/"):
            target = "/" + target
        return f"https://{host}{target}"

    # ── Internals ───────────────────────────────────────────────────
    def _scrape_profile(self) -> str:
        # Single source of truth: cfg. Falls back to "mock" because
        # AGENTS.md §5 file-touch etiquette forbids hitting real
        # upstreams from tests, and dev defaults to mock.
        return getattr(cfg, "scrape_profile", "mock") or "mock"

    def _wait_for_token(self) -> None:
        now = self._clock()
        if now < self._next_allowed_at:
            # Use the injected sleep so tests with a fake clock don't
            # block on the real wall clock.
            self._sleep(self._next_allowed_at - now)
        self._next_allowed_at = self._clock() + float(cfg.scrape_rate_limit)


__all__ = ["FetchClient", "FetchResponse", "ScraperAgentBase"]
