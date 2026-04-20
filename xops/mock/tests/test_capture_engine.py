"""Tests for the capture engine — entirely offline via StaticClient."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

import pytest

from xops.mock.capture_engine import (
    CaptureError,
    HTTPResponse,
    StaticClient,
    capture_all,
    capture_source,
)
from xops.mock.sources import CaptureTarget, Source


def _src(name: str = "demo", host: str = "demo.local", *targets: CaptureTarget) -> Source:
    return Source(
        key=name,
        real_host=f"www.{name}.com",
        mock_host=host,
        description="test source",
        targets=tuple(targets),
    )


def _resp(url: str, body: bytes, *, ct: str = "text/html", status: int = 200) -> HTTPResponse:
    return HTTPResponse(url=url, status=status, headers={"content-type": ct}, body=body)


def test_capture_source_writes_payload_and_headers(tmp_path: Path) -> None:
    src = _src("demo", "demo.local", CaptureTarget(name="home", path="/"))
    url = src.real_url(src.targets[0])
    client = StaticClient({url: _resp(url, b"<html>hi</html>")})

    results = capture_source(
        src,
        client=client,
        seeds_root=tmp_path,
        sleep=lambda _s: None,
        delay_s=0,
    )
    assert len(results) == 1
    r = results[0]
    assert r.path.read_bytes() == b"<html>hi</html>"
    assert r.path.name == "home.html"
    headers_path = r.path.with_suffix(".html.headers.json")
    assert headers_path.exists()
    meta = json.loads(headers_path.read_text())
    assert meta["status"] == 200
    assert meta["url"] == url


def test_capture_source_marks_refreshed_only_on_change(tmp_path: Path) -> None:
    src = _src("demo", "demo.local", CaptureTarget(name="home", path="/"))
    url = src.real_url(src.targets[0])
    client = StaticClient({url: _resp(url, b"first")})

    r1 = capture_source(src, client=client, seeds_root=tmp_path, sleep=lambda _s: None, delay_s=0)
    assert r1[0].refreshed is True
    assert r1[0].skipped is False

    # Same payload AND not forced → idempotent skip (no network call).
    r2 = capture_source(src, client=client, seeds_root=tmp_path, sleep=lambda _s: None, delay_s=0)
    assert r2[0].refreshed is False
    assert r2[0].skipped is True

    # force=True bypasses the skip; same payload → not refreshed.
    r3 = capture_source(
        src, client=client, seeds_root=tmp_path, sleep=lambda _s: None, delay_s=0, force=True,
    )
    assert r3[0].refreshed is False
    assert r3[0].skipped is False

    # Different payload + force=True → refreshed.
    client._payloads[url] = _resp(url, b"second")  # type: ignore[attr-defined]
    r4 = capture_source(
        src, client=client, seeds_root=tmp_path, sleep=lambda _s: None, delay_s=0, force=True,
    )
    assert r4[0].refreshed is True
    assert r4[0].skipped is False


def test_capture_source_records_http_error_status_without_raising(tmp_path: Path) -> None:
    """4xx/5xx is recorded as drift (seed + status), not an exception — the
    source-watcher must see the bad status as a signal, not a stacktrace."""
    src = _src("demo", "demo.local", CaptureTarget(name="x", path="/x"))
    url = src.real_url(src.targets[0])
    client = StaticClient({url: _resp(url, b"oops", status=503)})
    results = capture_source(
        src, client=client, seeds_root=tmp_path, sleep=lambda _s: None, delay_s=0
    )
    assert len(results) == 1
    assert results[0].status == 503
    assert results[0].path.read_bytes() == b"oops"
    # headers sidecar records the bad status
    headers_path = results[0].path.with_suffix(results[0].path.suffix + ".headers.json")
    assert json.loads(headers_path.read_text())["status"] == 503


def test_capture_source_respects_delay(tmp_path: Path) -> None:
    src = _src(
        "demo",
        "demo.local",
        CaptureTarget(name="a", path="/a"),
        CaptureTarget(name="b", path="/b"),
    )
    payloads = {src.real_url(t): _resp(src.real_url(t), b"x") for t in src.targets}
    client = StaticClient(payloads)
    sleeps = []
    capture_source(
        src, client=client, seeds_root=tmp_path,
        sleep=sleeps.append, delay_s=2.5,
    )
    # 2 targets → 1 inter-request sleep of 2.5s
    assert sleeps == [2.5]


def test_capture_all_rebuilds_manifest(tmp_path: Path) -> None:
    src1 = _src("a", "a.local", CaptureTarget(name="home", path="/"))
    src2 = _src("b", "b.local", CaptureTarget(name="home", path="/"))
    payloads: Dict[str, HTTPResponse] = {}
    for s in (src1, src2):
        url = s.real_url(s.targets[0])
        payloads[url] = _resp(url, f"hello-{s.key}".encode())
    client = StaticClient(payloads)

    manifest_path = tmp_path / "manifest.json"
    results, manifest = capture_all(
        client=client,
        sources=[src1, src2],
        seeds_root=tmp_path,
        manifest_path=manifest_path,
        sleep=lambda _s: None,
        delay_s=0,
    )
    assert len(results) == 2
    assert manifest_path.exists()
    assert manifest["schema"] == 1
    assert len(manifest["entries"]) == 2
    sources_seen = {e["source"] for e in manifest["entries"]}
    assert sources_seen == {"a.local", "b.local"}
    for entry in manifest["entries"]:
        assert "sha256" in entry
        assert entry["bytes"] > 0


def test_static_client_records_calls(tmp_path: Path) -> None:
    src = _src("demo", "demo.local", CaptureTarget(name="home", path="/"))
    url = src.real_url(src.targets[0])
    client = StaticClient({url: _resp(url, b"x")})
    capture_source(src, client=client, seeds_root=tmp_path, sleep=lambda _s: None, delay_s=0)
    assert client.calls == [url]


def test_unknown_url_raises(tmp_path: Path) -> None:
    src = _src("demo", "demo.local", CaptureTarget(name="home", path="/"))
    client = StaticClient({})  # nothing registered
    with pytest.raises(CaptureError):
        capture_source(src, client=client, seeds_root=tmp_path, sleep=lambda _s: None, delay_s=0)


def test_capture_all_idempotent_skips_seeded_sources(tmp_path: Path) -> None:
    """Second capture_all on a seeded corpus must not hit the network."""
    src = _src("demo", "demo.local", CaptureTarget(name="home", path="/"))
    url = src.real_url(src.targets[0])
    client = StaticClient({url: _resp(url, b"hello")})

    manifest_path = tmp_path / "manifest.json"
    capture_all(
        client=client, sources=[src], seeds_root=tmp_path,
        manifest_path=manifest_path, sleep=lambda _s: None, delay_s=0,
    )
    assert client.calls == [url]

    # Second pass — defaults to idempotent. No new HTTP calls.
    results, manifest = capture_all(
        client=client, sources=[src], seeds_root=tmp_path,
        manifest_path=manifest_path, sleep=lambda _s: None, delay_s=0,
    )
    assert client.calls == [url], "second pass must not hit the network"
    assert all(r.skipped for r in results)
    assert len(manifest["entries"]) == 1


def test_capture_all_force_refetches(tmp_path: Path) -> None:
    src = _src("demo", "demo.local", CaptureTarget(name="home", path="/"))
    url = src.real_url(src.targets[0])
    client = StaticClient({url: _resp(url, b"x")})

    manifest_path = tmp_path / "manifest.json"
    capture_all(
        client=client, sources=[src], seeds_root=tmp_path,
        manifest_path=manifest_path, sleep=lambda _s: None, delay_s=0,
    )
    assert len(client.calls) == 1

    capture_all(
        client=client, sources=[src], seeds_root=tmp_path,
        manifest_path=manifest_path, sleep=lambda _s: None, delay_s=0,
        force=True,
    )
    assert len(client.calls) == 2


def test_capture_with_depth_1_crawls_same_host_links(tmp_path: Path) -> None:
    """depth=1 must follow same-host hrefs, ignore cross-host + JS/anchors,
    and respect crawl_max_pages."""
    src = _src("demo", "demo.local", CaptureTarget(name="home", path="/"))
    home_url = src.real_url(src.targets[0])
    home_html = (
        b'<html><body>'
        b'<a href="/page-a">A</a>'
        b'<a href="https://www.demo.com/page-b">B</a>'
        b'<a href="https://other.com/x">cross-host (skip)</a>'
        b'<a href="javascript:void(0)">js (skip)</a>'
        b'<a href="#frag">frag (skip)</a>'
        b'<img src="/static/img.png">'
        b'</body></html>'
    )
    payloads = {
        home_url: _resp(home_url, home_html),
        "https://www.demo.com/page-a": _resp("https://www.demo.com/page-a", b"PAGE A"),
        "https://www.demo.com/page-b": _resp("https://www.demo.com/page-b", b"PAGE B"),
        "https://www.demo.com/static/img.png": _resp(
            "https://www.demo.com/static/img.png", b"PNGDATA", ct="image/png",
        ),
    }
    client = StaticClient(payloads)

    results = capture_source(
        src, client=client, seeds_root=tmp_path,
        sleep=lambda _s: None, delay_s=0,
        crawl_depth=1, crawl_max_pages=10,
    )
    discovered = [r for r in results if r.discovered]
    discovered_urls = {r.url for r in discovered}
    # All same-host links got fetched; cross-host + js + frag were filtered.
    assert "https://www.demo.com/page-a" in discovered_urls
    assert "https://www.demo.com/page-b" in discovered_urls
    assert "https://www.demo.com/static/img.png" in discovered_urls
    assert all("other.com" not in u for u in discovered_urls)
    # Idempotent: second pass discovers nothing new (everything skipped).
    results2 = capture_source(
        src, client=client, seeds_root=tmp_path,
        sleep=lambda _s: None, delay_s=0,
        crawl_depth=1, crawl_max_pages=10,
    )
    discovered2 = [r for r in results2 if r.discovered]
    assert all(r.skipped for r in discovered2)


def test_capture_crawl_respects_max_pages(tmp_path: Path) -> None:
    src = _src("demo", "demo.local", CaptureTarget(name="home", path="/"))
    home_url = src.real_url(src.targets[0])
    links = "".join(f'<a href="/p{i}">x</a>' for i in range(50))
    home_html = f"<html><body>{links}</body></html>".encode()
    payloads = {home_url: _resp(home_url, home_html)}
    for i in range(50):
        u = f"https://www.demo.com/p{i}"
        payloads[u] = _resp(u, f"page{i}".encode())
    client = StaticClient(payloads)

    results = capture_source(
        src, client=client, seeds_root=tmp_path,
        sleep=lambda _s: None, delay_s=0,
        crawl_depth=1, crawl_max_pages=5,
    )
    discovered = [r for r in results if r.discovered]
    assert len(discovered) == 5
