"""Mock-data capture engine — fetch real upstreams, freeze to seeds.

Rate-limited per source and robots-respecting (we only fetch what's
declared in ``sources.py`` plus optional same-host links discovered
inside captured HTML up to a bounded depth). Agents may invoke this
module directly; only ``git`` operations remain AI-restricted in this
repo (see AGENTS.md §2 rule #10).

Design
------
* A pluggable ``HTTPClient`` protocol so unit tests can swap in a fake
  client and exercise the full pipeline offline.
* Rate-limited (per-source delay) and bounded.
* **Idempotent by default**: if every declared target already exists on
  disk, ``capture_all(force=False)`` returns the existing snapshot and
  skips the network. Pass ``force=True`` (or wipe with `make mock.reset`)
  to force a refetch.
* **Depth-1 same-host crawl** (opt-in): when ``crawl_depth >= 1`` and a
  target's content-type is HTML, the engine extracts ``href``/``src``
  attributes pointing to the same upstream host, dedupes, caps at
  ``crawl_max_pages`` per source, and fetches them under a
  deterministic ``crawl/<sha8>.<ext>`` path so the seed corpus stays
  diff-friendly.
* All writes go under ``infra/mock/seeds/<source_key>/<target_name>.<ext>``
  with a sibling ``.headers.json`` for response metadata.
"""

from __future__ import annotations

import hashlib
import html.parser
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Protocol, Tuple

from .manifest import (
    MANIFEST_PATH,
    SEEDS_ROOT,
    load_manifest,
    make_entry,
    save_manifest,
    sha256_file,
)
from .sources import SOURCES, Source, all_keys, by_key

DEFAULT_USER_AGENT = "Negelir-Mock-Capture/1.0 (+https://github.com/metaphy6/negelir)"
DEFAULT_TIMEOUT_S = 30.0
DEFAULT_DELAY_S = 1.5  # polite gap between requests within a source
DEFAULT_CRAWL_DEPTH = 0
DEFAULT_CRAWL_MAX_PAGES = 30  # per source — keeps the seed corpus bounded


class CaptureError(RuntimeError):
    pass


# ── HTTP abstraction ──────────────────────────────────────────


@dataclass(frozen=True)
class HTTPResponse:
    url: str
    status: int
    headers: Dict[str, str]
    body: bytes


class HTTPClient(Protocol):
    def fetch(self, url: str, *, timeout: float, user_agent: str) -> HTTPResponse: ...


class UrllibClient:
    """Real client using stdlib urllib. Used by `make mock.capture`."""

    def fetch(self, url: str, *, timeout: float, user_agent: str) -> HTTPResponse:
        req = urllib.request.Request(url, headers={"User-Agent": user_agent})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                body = resp.read()
                headers = {k.lower(): v for k, v in resp.headers.items()}
                return HTTPResponse(
                    url=url,
                    status=resp.status,
                    headers=headers,
                    body=body,
                )
        except urllib.error.HTTPError as exc:
            body = exc.read() if exc.fp else b""
            headers = {k.lower(): v for k, v in (exc.headers or {}).items()}
            return HTTPResponse(url=url, status=exc.code, headers=headers, body=body)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise CaptureError(f"fetch failed for {url}: {exc}") from exc


class StaticClient:
    """Fake client backed by an in-memory dict; used by unit tests."""

    def __init__(self, payloads: Dict[str, HTTPResponse]):
        self._payloads = payloads
        self.calls: List[str] = []

    def fetch(self, url: str, *, timeout: float, user_agent: str) -> HTTPResponse:
        self.calls.append(url)
        if url not in self._payloads:
            raise CaptureError(f"StaticClient: no payload for {url}")
        return self._payloads[url]


# ── Capture engine ────────────────────────────────────────────


@dataclass
class CaptureResult:
    source: str
    target: str
    url: str
    path: Path
    bytes_written: int
    sha256: str
    refreshed: bool       # True iff payload bytes changed vs prior capture
    status: int
    skipped: bool = False  # True iff network was skipped (already seeded)
    discovered: bool = False  # True iff fetched via depth-1 crawl


# ── Same-host link extractor (depth-1 crawl) ──────────────────


class _LinkExtractor(html.parser.HTMLParser):
    """Pull href/src attributes out of HTML, no DOM, stdlib only."""

    _ATTRS = {"href", "src"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        for name, value in attrs:
            if name in self._ATTRS and value:
                self.links.append(value)


_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")


def _extract_same_host_links(body: bytes, *, base_host: str) -> List[str]:
    """Return a deduped list of same-host URL paths discovered in HTML."""
    try:
        text = body.decode("utf-8", errors="ignore")
    except Exception:
        return []
    parser = _LinkExtractor()
    try:
        parser.feed(text)
    except Exception:
        return []
    out: List[str] = []
    seen: set = set()
    for raw in parser.links:
        href = raw.strip()
        if not href or href.startswith("#") or href.startswith("javascript:") or href.startswith("mailto:"):
            continue
        if href.startswith("//"):
            href = "https:" + href
        if _SCHEME_RE.match(href):
            # absolute URL — keep only same-host
            try:
                rest = href.split("://", 1)[1]
                host, _, path = rest.partition("/")
                if host.lower() != base_host.lower():
                    continue
                path_q = "/" + path
            except Exception:
                continue
        else:
            # relative — must start with '/'
            if not href.startswith("/"):
                continue
            path_q = href
        # drop fragments
        path_q = path_q.split("#", 1)[0]
        if not path_q:
            path_q = "/"
        if path_q in seen:
            continue
        seen.add(path_q)
        out.append(path_q)
    return out


def _crawl_target_name(path_q: str) -> str:
    """Stable, fs-safe slug for a discovered URL path."""
    digest = hashlib.sha256(path_q.encode("utf-8")).hexdigest()[:10]
    # Pull a friendly hint from the last path segment (sans query/extension).
    seg = path_q.rstrip("/").rsplit("/", 1)[-1] or "root"
    seg = seg.split("?", 1)[0].split(".", 1)[0]
    seg = re.sub(r"[^A-Za-z0-9_-]+", "_", seg)[:24] or "page"
    return f"crawl_{seg}_{digest}"


# ── Idempotency helpers ────────────────────────────────────────


def _seed_path(seeds_root: Path, source: Source, target_name: str, ext: str) -> Path:
    return seeds_root / source.key / f"{target_name}{ext}"


def is_source_seeded(source: Source, *, seeds_root: Path = SEEDS_ROOT) -> bool:
    """True iff every declared target of ``source`` already has bytes on disk."""
    for target in source.targets:
        ext = _content_ext(target.content_type)
        path = _seed_path(seeds_root, source, target.name, ext)
        if not path.exists() or path.stat().st_size == 0:
            return False
    return True


def _write_payload(seeds_root: Path, source: Source, target_name: str, ext: str, body: bytes) -> Path:
    sub = seeds_root / source.key
    sub.mkdir(parents=True, exist_ok=True)
    path = sub / f"{target_name}{ext}"
    path.write_bytes(body)
    return path


def _content_ext(content_type: str) -> str:
    ct = content_type.split(";", 1)[0].strip().lower()
    return {
        "application/json": ".json",
        "text/html": ".html",
        "text/plain": ".txt",
        "application/xml": ".xml",
    }.get(ct, ".bin")


def capture_source(
    source: Source,
    *,
    client: HTTPClient,
    seeds_root: Path = SEEDS_ROOT,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout: float = DEFAULT_TIMEOUT_S,
    delay_s: float = DEFAULT_DELAY_S,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], str] = lambda: datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    force: bool = False,
    crawl_depth: int = DEFAULT_CRAWL_DEPTH,
    crawl_max_pages: int = DEFAULT_CRAWL_MAX_PAGES,
) -> List[CaptureResult]:
    """Capture every target of ``source``. Returns per-target results.

    Idempotent by default: if a target's seed file already exists, the
    network is skipped and the existing capture is reported as
    ``skipped=True`` (no ``refreshed`` flag). Pass ``force=True`` to
    re-fetch unconditionally.
    """
    out: List[CaptureResult] = []
    fetched_in_source = 0
    captured_html_for_crawl: List[Tuple[Source, bytes]] = []

    for i, target in enumerate(source.targets):
        ext = _content_ext(target.content_type)
        existing = _seed_path(seeds_root, source, target.name, ext)
        if existing.exists() and existing.stat().st_size > 0 and not force:
            digest = sha256_file(existing)
            out.append(
                CaptureResult(
                    source=source.key,
                    target=target.name,
                    url=source.real_url(target),
                    path=existing,
                    bytes_written=existing.stat().st_size,
                    sha256=digest,
                    refreshed=False,
                    status=200,  # we trust prior capture
                    skipped=True,
                )
            )
            continue

        if fetched_in_source > 0 and delay_s > 0:
            sleep(delay_s)
        fetched_in_source += 1

        url = source.real_url(target)
        resp = client.fetch(url, timeout=timeout, user_agent=user_agent)
        ext = _content_ext(target.content_type if resp.status < 400 else "text/html")
        before_path = _seed_path(seeds_root, source, target.name, ext)
        prior_hash = sha256_file(before_path) if before_path.exists() else ""
        path = _write_payload(seeds_root, source, target.name, ext, resp.body)
        new_hash = sha256_file(path)

        # write sibling headers metadata
        headers_path = path.with_suffix(path.suffix + ".headers.json")
        headers_path.write_text(
            json.dumps(
                {"status": resp.status, "headers": resp.headers, "url": url, "captured_at": now()},
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        out.append(
            CaptureResult(
                source=source.key,
                target=target.name,
                url=url,
                path=path,
                bytes_written=len(resp.body),
                sha256=new_hash,
                refreshed=(new_hash != prior_hash),
                status=resp.status,
            )
        )
        if crawl_depth >= 1 and resp.status < 400 and ext == ".html":
            captured_html_for_crawl.append((source, resp.body))

    # ── depth-1 crawl: same-host links found in the captured HTML ──
    if crawl_depth >= 1 and captured_html_for_crawl and crawl_max_pages > 0:
        budget = crawl_max_pages
        seen_paths: set = {t.path for t in source.targets}
        for src, body in captured_html_for_crawl:
            for path_q in _extract_same_host_links(body, base_host=src.real_host):
                if budget <= 0:
                    break
                if path_q in seen_paths:
                    continue
                seen_paths.add(path_q)
                target_name = _crawl_target_name(path_q)
                # Skip if already on disk (idempotent crawl too).
                # We don't know the ext upfront — guess from the path's tail.
                guess_ext = ".html"
                if "." in path_q.rsplit("/", 1)[-1]:
                    tail = path_q.rsplit(".", 1)[-1].split("?", 1)[0].lower()
                    if tail in ("json", "xml", "txt", "css", "js"):
                        guess_ext = "." + tail
                existing = _seed_path(seeds_root, src, target_name, guess_ext)
                if existing.exists() and existing.stat().st_size > 0 and not force:
                    out.append(
                        CaptureResult(
                            source=src.key, target=target_name,
                            url=f"https://{src.real_host}{path_q}",
                            path=existing,
                            bytes_written=existing.stat().st_size,
                            sha256=sha256_file(existing),
                            refreshed=False, status=200, skipped=True, discovered=True,
                        )
                    )
                    budget -= 1
                    continue

                if delay_s > 0:
                    sleep(delay_s)
                url = f"https://{src.real_host}{path_q}"
                try:
                    resp = client.fetch(url, timeout=timeout, user_agent=user_agent)
                except CaptureError:
                    continue  # tolerate individual crawl failures
                # Re-derive ext from response content-type if available.
                ct = resp.headers.get("content-type", "text/html")
                ext = _content_ext(ct if resp.status < 400 else "text/html")
                path = _write_payload(seeds_root, src, target_name, ext, resp.body)
                new_hash = sha256_file(path)
                headers_path = path.with_suffix(path.suffix + ".headers.json")
                headers_path.write_text(
                    json.dumps(
                        {"status": resp.status, "headers": resp.headers, "url": url, "captured_at": now()},
                        indent=2, ensure_ascii=False, sort_keys=True,
                    ) + "\n",
                    encoding="utf-8",
                )
                out.append(
                    CaptureResult(
                        source=src.key, target=target_name, url=url, path=path,
                        bytes_written=len(resp.body), sha256=new_hash,
                        refreshed=True, status=resp.status, discovered=True,
                    )
                )
                budget -= 1
            if budget <= 0:
                break

    return out


def capture_all(
    *,
    client: HTTPClient,
    sources: Iterable[Source] = SOURCES,
    seeds_root: Path = SEEDS_ROOT,
    manifest_path: Path = MANIFEST_PATH,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout: float = DEFAULT_TIMEOUT_S,
    delay_s: float = DEFAULT_DELAY_S,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], str] = lambda: datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    force: bool = False,
    crawl_depth: int = DEFAULT_CRAWL_DEPTH,
    crawl_max_pages: int = DEFAULT_CRAWL_MAX_PAGES,
) -> Tuple[List[CaptureResult], Dict]:
    """Capture every source and rebuild the manifest. Returns (results, manifest).

    Default behaviour is **idempotent**: targets whose seed file already
    exists are reported as ``skipped=True`` and the network is not hit.
    Pass ``force=True`` (or wipe the seeds with ``make mock.reset``) to
    refetch from the upstream.
    """
    seeds_root.mkdir(parents=True, exist_ok=True)
    all_results: List[CaptureResult] = []
    sources_by_key: Dict[str, Source] = {}
    captured_at = now()
    for source in sources:
        sources_by_key[source.key] = source
        results = capture_source(
            source,
            client=client,
            seeds_root=seeds_root,
            user_agent=user_agent,
            timeout=timeout,
            delay_s=delay_s,
            sleep=sleep,
            now=lambda: captured_at,
            force=force,
            crawl_depth=crawl_depth,
            crawl_max_pages=crawl_max_pages,
        )
        all_results.extend(results)

    # Rebuild manifest from the per-source results so crawled + skipped
    # entries are both represented faithfully.
    entries = []
    for r in all_results:
        src = sources_by_key.get(r.source)
        if src is None:
            continue
        if r.discovered:
            ct = _ext_to_content_type(r.path.suffix)
        else:
            ct = _content_type_for(src, r.target)
        entries.append(
            make_entry(
                source=src.mock_host,
                url=r.url,
                payload_path=r.path,
                captured_at=captured_at,
                content_type=ct,
                status=r.status,
                seeds_root=seeds_root,
            )
        )
    manifest = {"schema": 1, "captured_at": captured_at, "entries": entries}
    save_manifest(manifest, path=manifest_path)
    return all_results, manifest


def _content_type_for(source: Source, target_name: str) -> str:
    for t in source.targets:
        if t.name == target_name:
            return t.content_type
    return "application/octet-stream"


def _ext_to_content_type(ext: str) -> str:
    return {
        ".html": "text/html; charset=utf-8",
        ".json": "application/json",
        ".xml": "application/xml",
        ".css": "text/css",
        ".js": "application/javascript",
        ".txt": "text/plain; charset=utf-8",
    }.get(ext.lower(), "application/octet-stream")
