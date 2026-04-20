"""60%-DOM-rewrite stress demo for the source_watcher.

Invoked from docs/testing/source-watcher-60pct-stress.md to
generate the live transcript embedded in that doc. Stdlib only; no
network; runs in <1s.

Scenario: the mackolik fixture page is rewritten in a redesign that
renames ~60% of CSS classes, swaps section tags, drops two H2
headers, restructures the score widget, and adds a new sponsor block.

We feed the *raw HTML* through the watcher exactly the way `watch.run`
does (as the {_raw_len, _suffix, _sha256, _status} envelope), then we
also feed a *parsed-DOM JSON view* to show what the watcher *would*
see if it ever switched to structural snapshots.

The point isn't to prescribe one approach — it's to make the
capabilities and shortcomings visible side-by-side.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from ai.swarm.source_watcher.classifier import classify  # noqa: E402
from ai.swarm.source_watcher.differ import diff_json  # noqa: E402
from ai.swarm.source_watcher.planner import plan  # noqa: E402


# ── 1. Build a realistic v1 fixture page ─────────────────────────────

V1_HTML = """\
<!doctype html>
<html lang="tr">
<head>
  <title>Mackolik · Süper Lig Fikstürü</title>
  <meta name="generator" content="mackolik-cms@4.2">
</head>
<body>
  <header class="site-hdr">
    <nav class="primary-nav"><a href="/">Ana Sayfa</a></nav>
  </header>
  <main class="content">
    <h1 class="page-title">Süper Lig — Hafta 30</h1>
    <h2 class="section-title">Maç Programı</h2>

    <section class="match-list" data-week="30">
      <article class="match" data-match-id="20260420-001">
        <span class="kickoff">20:00</span>
        <span class="home-team">Galatasaray</span>
        <span class="score">vs</span>
        <span class="away-team">Fenerbahçe</span>
      </article>
      <article class="match" data-match-id="20260420-002">
        <span class="kickoff">17:00</span>
        <span class="home-team">Beşiktaş</span>
        <span class="score">vs</span>
        <span class="away-team">Trabzonspor</span>
      </article>
      <article class="match" data-match-id="20260420-003">
        <span class="kickoff">14:30</span>
        <span class="home-team">Adana Demirspor</span>
        <span class="score">vs</span>
        <span class="away-team">Kayserispor</span>
      </article>
    </section>

    <h2 class="section-title">Puan Durumu</h2>
    <table class="standings">
      <thead><tr><th>#</th><th class="team">Takım</th><th class="pts">P</th></tr></thead>
      <tbody>
        <tr><td>1</td><td class="team">Galatasaray</td><td class="pts">76</td></tr>
        <tr><td>2</td><td class="team">Fenerbahçe</td><td class="pts">73</td></tr>
        <tr><td>3</td><td class="team">Beşiktaş</td><td class="pts">62</td></tr>
      </tbody>
    </table>
  </main>
  <footer class="site-ftr">© 2026 Mackolik</footer>
</body>
</html>
"""

# ── 2. Build the v2 page after a 60% redesign ────────────────────────
# Changes vs V1 (deliberately broad — meant to trip a real scraper):
#   • <header class="site-hdr">       → <div class="topbar">
#   • <nav class="primary-nav">       → <ul class="menu">
#   • <main class="content">          → <section class="page-body">
#   • <h1 class="page-title">         → <h1 class="hero__heading">
#   • <h2 class="section-title">      → <h3 class="block__title">
#   • <section class="match-list">    → <div class="fixtures-grid">
#   • <article class="match">         → <li class="card">
#   • <span class="home-team">        → <p class="card__home">
#   • <span class="away-team">        → <p class="card__away">
#   • <span class="kickoff">          → <time class="card__time">
#   • data-match-id                   → data-fixture-id
#   • <table class="standings">       → <ol class="leaderboard">
#   • <th class="pts">                → <th class="leaderboard__pts">
#   • Drops one H2 ("Puan Durumu" header text moved into <ol>'s caption)
#   • Adds a sponsor block in the header
#   • generator meta bumps to 5.0
# Net: ~60% of the selectors a scraper would use are renamed/moved.

V2_HTML = """\
<!doctype html>
<html lang="tr">
<head>
  <title>Mackolik · Süper Lig Fikstürü</title>
  <meta name="generator" content="mackolik-cms@5.0">
</head>
<body>
  <div class="topbar">
    <ul class="menu"><li><a href="/">Ana Sayfa</a></li></ul>
    <aside class="sponsor-strip">Sponsorlu içerik</aside>
  </div>
  <section class="page-body">
    <h1 class="hero__heading">Süper Lig — Hafta 30</h1>
    <h3 class="block__title">Maç Programı</h3>

    <div class="fixtures-grid" data-gw="30">
      <ul>
        <li class="card" data-fixture-id="20260420-001">
          <time class="card__time">20:00</time>
          <p class="card__home">Galatasaray</p>
          <p class="card__sep">vs</p>
          <p class="card__away">Fenerbahçe</p>
        </li>
        <li class="card" data-fixture-id="20260420-002">
          <time class="card__time">17:00</time>
          <p class="card__home">Beşiktaş</p>
          <p class="card__sep">vs</p>
          <p class="card__away">Trabzonspor</p>
        </li>
        <li class="card" data-fixture-id="20260420-003">
          <time class="card__time">14:30</time>
          <p class="card__home">Adana Demirspor</p>
          <p class="card__sep">vs</p>
          <p class="card__away">Kayserispor</p>
        </li>
      </ul>
    </div>

    <ol class="leaderboard">
      <caption class="leaderboard__cap">Puan Durumu</caption>
      <li><span>1</span><span class="leaderboard__team">Galatasaray</span><span class="leaderboard__pts">76</span></li>
      <li><span>2</span><span class="leaderboard__team">Fenerbahçe</span><span class="leaderboard__pts">73</span></li>
      <li><span>3</span><span class="leaderboard__team">Beşiktaş</span><span class="leaderboard__pts">62</span></li>
    </ol>
  </section>
  <footer class="site-ftr">© 2026 Mackolik</footer>
</body>
</html>
"""


def envelope(html: str, *, status: int = 200) -> dict[str, Any]:
    """The exact shape ``watch.run`` records for an HTML probe."""
    raw = html.encode("utf-8")
    return {
        "_status": status,
        "_raw_len": len(raw),
        "_sha256": hashlib.sha256(raw).hexdigest(),
        "_suffix": html[-120:],
    }


def parsed_view(html: str) -> dict[str, Any]:
    """Coarse structural fingerprint — what the watcher *could* see if
    we ever taught it to parse the DOM. Stdlib-only so we count tags
    + classes + data-* attrs without pulling in lxml.
    """
    import re
    tags = re.findall(r"<([a-zA-Z][a-zA-Z0-9-]*)\b", html)
    classes = re.findall(r'class="([^"]+)"', html)
    data_attrs = re.findall(r"\bdata-([a-zA-Z0-9_-]+)=", html)
    flat_classes: list[str] = []
    for c in classes:
        flat_classes.extend(c.split())
    return {
        "tag_counts": dict(sorted({t: tags.count(t) for t in set(tags)}.items())),
        "class_set": sorted(set(flat_classes)),
        "data_attrs": sorted(set(data_attrs)),
    }


def run_pipeline(label: str, old: Any, new: Any) -> None:
    print(f"\n══════════════════════════════════════════════════════════════")
    print(f"  {label}")
    print(f"══════════════════════════════════════════════════════════════")
    diffs = diff_json(old, new)
    print(f"  raw FieldDiff count: {len(diffs)}")
    classified = classify(diffs)
    p = plan("mackolik", classified)
    print(f"  plan.severity:       {p.severity}")
    print(f"  plan.actions:        {p.actions}")
    print(f"  plan.summary:        {p.summary}")
    if p.diffs:
        print("  classified diffs:")
        for d in p.diffs[:12]:
            print(f"    [{d['severity']:14}] {d['kind']:12} {d['path']:55} — {d['reason']}")
        if len(p.diffs) > 12:
            print(f"    … {len(p.diffs) - 12} more")


def main() -> None:
    print(f"v1 raw_len = {len(V1_HTML.encode())}, "
          f"v2 raw_len = {len(V2_HTML.encode())}, "
          f"delta = {len(V2_HTML.encode()) - len(V1_HTML.encode())} bytes "
          f"({(len(V2_HTML.encode()) - len(V1_HTML.encode())) / len(V1_HTML.encode()):+.1%})")

    # Path A — what production actually feeds the watcher today.
    run_pipeline(
        "PATH A · production envelope (status + raw_len + sha256 + suffix)",
        envelope(V1_HTML),
        envelope(V2_HTML),
    )

    # Path B — same redesign, served behind a Cloudflare-style soft block.
    # Status still 200, but raw_len collapses by 90% to a challenge page.
    challenge_html = (
        "<!doctype html><html><head><title>Just a moment…</title></head>"
        "<body><h1>Checking your browser before accessing the site.</h1>"
        "</body></html>"
    )
    run_pipeline(
        "PATH B · soft-block (200 OK but content replaced by challenge)",
        envelope(V1_HTML),
        envelope(challenge_html, status=200),
    )

    # Path C — same redesign, but watcher fed a coarse parsed view.
    # This is the watcher's *future ceiling* — see §Improvements.
    run_pipeline(
        "PATH C · hypothetical parsed-DOM view (NOT in production today)",
        parsed_view(V1_HTML),
        parsed_view(V2_HTML),
    )


if __name__ == "__main__":
    main()
