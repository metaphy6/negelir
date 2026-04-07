"""
Negelir P2P — Full network simulation runner.
Per roadmap §7: nodes produce analyses, share them, build reputations,
and the network collectively improves.

Includes:
  - Real match data loading from scraped JSON
  - AI pipeline (TQU → GBDT → TRC) running across all nodes
  - Turkish question-answer demonstration through P2P network
  - Reputation-weighted ensemble results
"""

import hashlib
import json
import os
import random
import sys
import time
from pathlib import Path

from node.peer import PeerNode, PeerAnalysis, ScrapedRecord, DataStore, get_p2p_logger
from protocol.messages import P2PMessage, MessageType
from protocol.transport import SimulatedTransport
from reputation.tracker import compute_network_summary, print_reputation_matrix

log = get_p2p_logger("simulation")


# ── Real data loading ────────────────────────────────────────

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_REAL_DATA_PATH = _DATA_DIR / "tr_super_lig_real.json"


def _load_real_matches(limit: int = 30) -> list[dict]:
    """
    Load real matches from the scraped JSON file and convert to
    the simulation format (team stats + Elo approximation).
    Returns the most recent `limit` matches that have scores.
    """
    if not _REAL_DATA_PATH.exists():
        log.warning(f"⚠️  Real data not found at {_REAL_DATA_PATH}, using fallback")
        return []

    with open(_REAL_DATA_PATH) as f:
        raw = json.load(f)

    matches = [m for m in raw.get("matches", []) if m.get("score", {}).get("ft")]

    # Build rolling team stats from the full history
    team_stats: dict[str, dict] = {}  # team → {goals_for, goals_against, matches, form}
    for m in matches:
        for side, opp_side in [("team1", "team2"), ("team2", "team1")]:
            team = m[side]
            if team not in team_stats:
                team_stats[team] = {"gf": [], "ga": [], "form": [], "elo": 1500.0}
            ft = m["score"]["ft"]
            gf = ft[0] if side == "team1" else ft[1]
            ga = ft[1] if side == "team1" else ft[0]
            team_stats[team]["gf"].append(gf)
            team_stats[team]["ga"].append(ga)
            # Form: W=3, D=1, L=0
            if gf > ga:
                team_stats[team]["form"].append(3)
            elif gf == ga:
                team_stats[team]["form"].append(1)
            else:
                team_stats[team]["form"].append(0)
            # Simple Elo update
            expected = 1.0 / (1.0 + 10 ** ((team_stats.get(m[opp_side], {}).get("elo", 1500) - team_stats[team]["elo"]) / 400))
            actual = 1.0 if gf > ga else (0.5 if gf == ga else 0.0)
            team_stats[team]["elo"] += 20 * (actual - expected)

    # Take the last `limit` matches and build simulation-format dicts
    recent = matches[-limit:]
    result = []
    for m in recent:
        t1, t2 = m["team1"], m["team2"]
        s1 = team_stats.get(t1, {})
        s2 = team_stats.get(t2, {})
        ft = m["score"]["ft"]
        ht = m["score"].get("ht", [0, 0])

        def _avg(lst, n=5):
            window = lst[-n:] if lst else [0]
            return sum(window) / max(1, len(window))

        result.append({
            "home_team": t1,
            "away_team": t2,
            "match_date": m.get("date", ""),
            "league": "Süper Lig",
            "week": int(m.get("round", "Matchday 1").split()[-1]) if "Matchday" in m.get("round", "") else 1,
            "home_form": s1.get("form", [1])[-5:],
            "away_form": s2.get("form", [1])[-5:],
            "h2h_last5": {"home_wins": 2, "away_wins": 1, "draws": 2, "avg_goals": 2.5},
            "home_elo": round(s1.get("elo", 1500)),
            "away_elo": round(s2.get("elo", 1500)),
            "home_avg_scored": round(_avg(s1.get("gf", [1])), 2),
            "away_avg_scored": round(_avg(s2.get("gf", [1])), 2),
            "home_avg_conceded": round(_avg(s1.get("ga", [1])), 2),
            "away_avg_conceded": round(_avg(s2.get("ga", [1])), 2),
            "sentiment_home": round(random.uniform(0.3, 0.8), 2),
            "sentiment_away": round(random.uniform(0.2, 0.7), 2),
            "stats": {
                "possession_h": random.randint(40, 60),
                "possession_a": 0,  # filled below
                "shots_on_h": random.randint(2, 8),
                "shots_on_a": random.randint(2, 8),
                "corners_h": random.randint(2, 10),
                "corners_a": random.randint(2, 10),
                "fouls_h": random.randint(8, 20),
                "fouls_a": random.randint(8, 20),
            },
            # Store actual result for validation
            "_actual_ft": ft,
            "_actual_ht": ht,
        })
        result[-1]["stats"]["possession_a"] = 100 - result[-1]["stats"]["possession_h"]

    log.info(f"📂 Loaded {len(result)} real matches from {_REAL_DATA_PATH.name}")
    return result


# ── Simulated scraping data — now loaded from real data or fallback ──
_real_matches = _load_real_matches(limit=30)

SIMULATED_SCRAPED_DATA: dict[str, dict] = {}
if _real_matches:
    for m in _real_matches[:10]:  # Use 10 matches for the main simulation dict
        key = f"{m['home_team']}-{m['away_team']}"
        SIMULATED_SCRAPED_DATA[key] = m
else:
    # Fallback: hardcoded data if real data is unavailable
    SIMULATED_SCRAPED_DATA = {
        "Galatasaray-Fenerbahçe": {
            "home_team": "Galatasaray", "away_team": "Fenerbahçe",
            "match_date": "2026-04-05", "league": "Süper Lig", "week": 30,
            "home_form": [3, 3, 1, 3, 0], "away_form": [3, 1, 0, 3, 3],
            "h2h_last5": {"home_wins": 3, "away_wins": 1, "draws": 1, "avg_goals": 2.8},
            "home_elo": 1720, "away_elo": 1680,
            "home_avg_scored": 1.9, "away_avg_scored": 1.6,
            "home_avg_conceded": 0.7, "away_avg_conceded": 0.9,
            "sentiment_home": 0.72, "sentiment_away": 0.55,
            "stats": {"possession_h": 56, "possession_a": 44, "shots_on_h": 6, "shots_on_a": 4,
                      "corners_h": 7, "corners_a": 5, "fouls_h": 14, "fouls_a": 16},
        },
        "Beşiktaş-Trabzonspor": {
            "home_team": "Beşiktaş", "away_team": "Trabzonspor",
            "match_date": "2026-04-05", "league": "Süper Lig", "week": 30,
            "home_form": [3, 0, 3, 1, 3], "away_form": [1, 3, 0, 3, 1],
            "h2h_last5": {"home_wins": 2, "away_wins": 2, "draws": 1, "avg_goals": 3.0},
            "home_elo": 1650, "away_elo": 1590,
            "home_avg_scored": 1.6, "away_avg_scored": 1.3,
            "home_avg_conceded": 1.0, "away_avg_conceded": 1.2,
            "sentiment_home": 0.60, "sentiment_away": 0.45,
            "stats": {"possession_h": 52, "possession_a": 48, "shots_on_h": 5, "shots_on_a": 5,
                      "corners_h": 6, "corners_a": 6, "fouls_h": 12, "fouls_a": 13},
        },
    }


# Build demo questions from whichever data we loaded
P2P_DEMO_QUESTIONS: list[tuple[str, str]] = []
_question_templates = [
    "{home} bu maçı kazanır mı?",
    "Bu maçta 2.5 üstü gol olur mu?",
    "İki takım da gol atar mı?",
    "Bu maç berabere biter mi?",
    "İlk yarıda gol olur mu?",
    "{home} kalesini gol yemeden korur mu?",
    "{away} galip gelebilir mi?",
]
for match_key, data in list(SIMULATED_SCRAPED_DATA.items())[:7]:
    home = data["home_team"]
    away = data["away_team"]
    for tmpl in _question_templates:
        P2P_DEMO_QUESTIONS.append(
            (match_key, tmpl.format(home=home, away=away))
        )

# ── Turkish intent classification (inline TQU for P2P) ───
import re

_INTENT_RULES = [
    ("match_winner",     [re.compile(r"(kazan[ıiır]|yener|alır)", re.I)]),
    ("draw",             [re.compile(r"(berabere|eşit)", re.I)]),
    ("over_under",       [re.compile(r"(\d+\.?\d*)\s*(üst|alt|over|under)", re.I)]),
    ("goal_range",       [re.compile(r"kaç\s*gol", re.I)]),
    ("both_teams_score", [re.compile(r"(iki|her)\s*(takım|iki).*(gol|skor)", re.I)]),
    ("clean_sheet",      [re.compile(r"(kale|gol\s*ye)", re.I)]),
    ("half_time",        [re.compile(r"(ilk|ikinci)\s*yarı", re.I)]),
    ("form_query",       [re.compile(r"(form|performans|son\s*maç)", re.I)]),
    ("head_to_head",     [re.compile(r"(kafa\s*kafa|h2h|karşılaşma)", re.I)]),
    ("score_predict",    [re.compile(r"(skor|kaç.kaç|tahmin)", re.I)]),
]


def _classify_question(text: str) -> tuple[str, float]:
    """Lightweight intent classification for P2P demo."""
    for intent_id, patterns in _INTENT_RULES:
        for pat in patterns:
            if pat.search(text):
                return intent_id, 0.75
    return "match_winner", 0.40


def _compose_turkish_answer(intent: str, match_data: dict, analysis: PeerAnalysis) -> str:
    """Compose a Turkish natural-language answer from analysis + scraped data."""
    home = match_data["home_team"]
    away = match_data["away_team"]
    h2h = match_data.get("h2h_last5", {})
    hp = analysis.home_win_prob
    dp = analysis.draw_prob
    ap = analysis.away_win_prob
    conf = analysis.confidence

    if intent == "match_winner":
        if hp > max(dp, ap):
            verdict = "Büyük ihtimalle evet." if hp > 0.55 else "Muhtemelen evet, ama kolay değil."
            return (
                f"{verdict} {home} son 5 maçta {sum(1 for x in match_data['home_form'] if x == 3)} "
                f"galibiyet almış, Elo puanı {match_data['home_elo']}. "
                f"Kafa kafaya {h2h.get('home_wins', 0)}-{h2h.get('away_wins', 0)} {home} lehine. "
                f"Ev sahibi kazanma olasılığı: %{hp*100:.0f}. Güven: %{conf*100:.0f}."
            )
        else:
            return (
                f"Muhtemelen hayır. {away} son dönemde daha iyi form yakalamış, "
                f"Elo puanı {match_data['away_elo']}. "
                f"Deplasman kazanma olasılığı: %{ap*100:.0f}. Güven: %{conf*100:.0f}."
            )

    elif intent == "draw":
        if dp > 0.28:
            return (
                f"Beraberlik ihtimali var (%{dp*100:.0f}). "
                f"Son 5 karşılaşmada {h2h.get('draws', 0)} beraberlik çıkmış. "
                f"İki takımın gücü birbirine yakın (Elo farkı: {abs(match_data['home_elo'] - match_data['away_elo'])}). "
                f"Güven: %{conf*100:.0f}."
            )
        else:
            return (
                f"Beraberlik olasılığı düşük (%{dp*100:.0f}). "
                f"İki takım arasında belirgin güç farkı var. Güven: %{conf*100:.0f}."
            )

    elif intent == "over_under":
        avg_goals = match_data["home_avg_scored"] + match_data["away_avg_scored"]
        over_prob = min(0.95, max(0.05, 1.0 / (1.0 + 2.71828 ** (-(avg_goals - 2.5)))))
        if over_prob > 0.55:
            return (
                f"Büyük ihtimalle üst. Son maçlarda ortalama toplam gol: {avg_goals:.1f}. "
                f"{home} ort. {match_data['home_avg_scored']:.1f} gol atıyor, "
                f"{away} ort. {match_data['away_avg_scored']:.1f} gol atıyor. "
                f"Kafa kafaya maçların ort. golü: {h2h.get('avg_goals', 2.5):.1f}. "
                f"2.5 üstü olasılığı: %{over_prob*100:.0f}. Güven: %{conf*100:.0f}."
            )
        else:
            return (
                f"Alt olasılığı daha yüksek. Ortalama toplam gol: {avg_goals:.1f}. "
                f"Savunmalar güçlü, düşük skorlu maç bekleniyor. Güven: %{conf*100:.0f}."
            )

    elif intent == "both_teams_score":
        bts = match_data["home_avg_scored"] > 0.8 and match_data["away_avg_scored"] > 0.8
        pct = 65 if bts else 40
        return (
            f"{'Muhtemelen evet.' if bts else 'Kesin değil.'} "
            f"{home} ort. {match_data['home_avg_scored']:.1f}, "
            f"{away} ort. {match_data['away_avg_scored']:.1f} gol atıyor. "
            f"Karşılıklı gol olasılığı: %{pct}. Güven: %{conf*100:.0f}."
        )

    elif intent == "clean_sheet":
        conceded = match_data.get("home_avg_conceded", 1.0)
        cs_prob = max(0.1, 1.0 - conceded)
        return (
            f"{'Zor görünüyor.' if conceded > 0.8 else 'Mümkün.'} "
            f"{home} son 5 maçta ort. {conceded:.1f} gol yemiş. "
            f"Kale kapama olasılığı: %{cs_prob*100:.0f}. Güven: %{conf*100:.0f}."
        )

    elif intent == "goal_range":
        avg = match_data["home_avg_scored"] + match_data["away_avg_scored"]
        low = max(0, round(avg - 1))
        high = round(avg + 1)
        return (
            f"Tahmini gol aralığı: {low}-{high}. "
            f"Ortalama toplam gol: {avg:.1f}. "
            f"Kafa kafaya ortalama: {h2h.get('avg_goals', 2.5):.1f}. "
            f"Güven: %{conf*100:.0f}."
        )

    return f"Analiz tamamlandı. Ev: %{hp*100:.0f}, Berabere: %{dp*100:.0f}, Deplasman: %{ap*100:.0f}. Güven: %{conf*100:.0f}."


class P2PSimulation:
    """
    Simulates a P2P network of Negelir AI nodes.
    Demonstrates: web scraping → data processing → AI analysis → P2P sharing →
                  reputation building → Turkish Q&A answers.

    Supports dynamic peer scaling: add_node() / remove_node() at any point.
    Implements P2P data retention via SCRAPE_DATA message broadcasts.
    """

    def __init__(self):
        self.node_count = int(os.getenv("P2P_NODE_COUNT", "5"))
        self.match_count = int(os.getenv("P2P_SIMULATION_MATCHES", "10"))
        self.nodes: list[PeerNode] = []
        self.transport = SimulatedTransport()
        self._next_port = int(os.getenv("P2P_BASE_PORT", "9000"))
        self._node_counter = 0
        self._removed_nodes: list[PeerNode] = []  # track departed peers

    def run(self):
        """Run the full P2P simulation with AI pipeline integration."""
        from rich.console import Console
        from rich.table import Table
        console = Console(force_terminal=True)

        console.rule("[bold cyan]🌐 NEGELIR P2P NETWORK SIMULATION[/bold cyan]", style="cyan")
        console.print("[bold]Scraping → Processing → AI Analysis → P2P Sharing → Turkish Response[/bold]\n")
        start = time.time()

        # Phase A: Network Setup
        self._create_nodes()

        # Phase B: Simulated Web Scraping
        scraped_data = self._simulate_web_scraping(console)

        # Phase C: Data Processing & Quality Validation
        processed_matches = self._process_and_validate_data(scraped_data, console)

        # Phase D: P2P Match Analysis Rounds
        all_results = self._simulate_matches(processed_matches)

        # Phase E: Turkish Q&A Through P2P Network
        self._run_turkish_qa_pipeline(console)

        # Phase F: Final Reputation Matrix
        console.rule("[bold cyan]📊 Final Reputation Matrix[/bold cyan]", style="cyan")
        print_reputation_matrix(self.nodes)

        # Phase G: Network Summary
        summary = compute_network_summary(self.nodes)
        console.print(f"\n🏁 [bold]Simulation Summary:[/bold]")
        console.print(f"   📡 Node count: {summary.total_nodes}")
        console.print(f"   📈 Average accuracy: {summary.avg_accuracy:.1%}")
        console.print(f"   ⭐ Leader: {summary.leader_count}  🟢 High: {summary.high_count}  "
                       f"🟡 Medium: {summary.medium_count}  🔴 Low: {summary.low_count}  "
                       f"🆕 New: {summary.new_count}")

        elapsed = time.time() - start
        # Transport realism stats
        ts = self.transport.stats
        console.print(f"\n📡 [bold]Transport Realism Stats:[/bold]")
        console.print(f"   📨 Messages sent: {ts.messages_sent:,}")
        console.print(f"   📬 Delivered: {ts.messages_delivered:,}")
        console.print(f"   💀 Dropped: {ts.messages_dropped:,} ({ts.drop_rate:.1%})")
        console.print(f"   📦 Bytes serialized: {ts.bytes_serialized:,}")
        console.print(f"   ⚠️  Serde errors: {ts.serde_errors}")
        console.print(f"   ⏱️  Avg latency: {ts.avg_latency_ms:.1f}ms")
        console.print(f"   🔗 Topology: k={self.transport.k_neighbors} neighbors, fanout={self.transport.gossip_fanout}")
        console.print(f"\n✅ [bold green]Simulation complete! ({elapsed:.1f}s)[/bold green]\n")

    # ── Phase A: Node Creation ──────────────────────────

    def _create_nodes(self):
        """Create simulated P2P nodes."""
        log.info(f"📡 Creating {self.node_count} nodes...")

        for i in range(self.node_count):
            self.add_node(announce=False)

        # Inject one Sybil-like bad node for reputation testing
        if len(self.nodes) >= 2:
            self.nodes[-1].model_bias = 0.3
            log.info(f"   ⚠️  Node {self.nodes[-1].node_id[:8]}: deliberate bias (Sybil test)")

    # ── Dynamic Scaling ─────────────────────────────────

    def add_node(self, announce: bool = True) -> PeerNode:
        """Add a new peer node to the live network."""
        idx = self._node_counter
        self._node_counter += 1
        node_id = hashlib.sha256(f"node_{idx}_negelir".encode()).hexdigest()[:16]
        port = self._next_port
        self._next_port += 1
        node = PeerNode(node_id=node_id, port=port)
        self.nodes.append(node)
        self.transport.register_node(node_id)

        if announce:
            log.info(f"🟢 Node JOINED: {node_id[:8]} (port: {port}, total: {len(self.nodes)})")
            # Propagate data from existing peers to the new node
            self._sync_data_to_node(node)
        else:
            log.info(f"   🖥️  Node {idx + 1}: {node_id[:8]} (port: {port})")

        return node

    def remove_node(self, node: PeerNode | None = None) -> PeerNode | None:
        """Remove a peer from the live network. Defaults to a random non-first node."""
        if len(self.nodes) <= 1:
            log.warning("⚠️  Cannot remove last node")
            return None
        if node is None:
            node = random.choice(self.nodes[1:])  # never remove first node (lead)
        if node not in self.nodes:
            return None
        self.nodes.remove(node)
        self.transport.unregister_node(node.node_id)
        self._removed_nodes.append(node)
        log.info(f"🔴 Node LEFT: {node.node_id[:8]} (total: {len(self.nodes)}, data retained: {node.data_store.size} records)")
        return node

    def _sync_data_to_node(self, new_node: PeerNode):
        """Synchronise existing scraped data to a newly joined node.
        Per Gemini §4 Phase 4: manifest-based delta sync — exchange hash
        manifests first, then transfer only missing records."""
        if not self.nodes:
            return
        # Gather all donors that have data
        donors = [n for n in self.nodes if n.node_id != new_node.node_id and n.data_store.size > 0]
        if not donors:
            return

        new_manifest = set(new_node.data_store.get_manifest())
        synced_total = 0

        for donor in donors:
            donor_manifest = donor.data_store.get_manifest()
            # Only transfer hashes the new node doesn't have
            missing = [h for h in donor_manifest if h not in new_manifest]
            if not missing:
                continue
            synced = 0
            for h in missing:
                record = donor.data_store.get(h)
                if record and new_node.data_store.merge_record(record):
                    new_manifest.add(h)
                    synced += 1
            if synced:
                log.info(
                    f"   📦 Delta-synced {synced}/{len(donor_manifest)} records "
                    f"from {donor.node_id[:8]} → {new_node.node_id[:8]}"
                )
                synced_total += synced

        if synced_total:
            log.info(
                f"   ✅ Manifest sync complete: {synced_total} new records "
                f"(store: {new_node.data_store.size})"
            )

    # ── Phase B: Simulated Web Scraping ─────────────────

    def _simulate_web_scraping(self, console) -> dict:
        """
        Simulate fetching data from Turkish football sources.
        Demonstrates scraping performance, rate limiting, and data intake.
        """
        from rich.table import Table

        console.rule("[bold yellow]🌐 Phase B: Web Scraping Simulation[/bold yellow]", style="yellow")
        log.info("🕷️  Web scraping starting (3 sources, rate-limited)...")

        sources = [
            {"name": "Source-A (Statistics)", "url": "source-a.example", "pages": 12, "delay_ms": 180},
            {"name": "Source-B (Live Score)",  "url": "source-b.example", "pages": 8,  "delay_ms": 220},
            {"name": "Source-C (Archive)",        "url": "source-c.example", "pages": 15, "delay_ms": 150},
        ]

        scrape_results = []
        total_bytes = 0
        total_pages = 0
        total_time_ms = 0

        for src in sources:
            src_start = time.time()
            pages_fetched = 0
            bytes_this_source = 0

            log.info(f"\n🔗 Source: {src['name']}")
            log.info(f"   ⏱️  Rate limit: {src['delay_ms']}ms/request")

            for page_num in range(1, src["pages"] + 1):
                # Simulate network delay
                simulate_delay = random.uniform(0.01, 0.03)
                time.sleep(simulate_delay)

                # Simulate page size (30-80 KB of HTML)
                page_bytes = random.randint(30_000, 80_000)
                bytes_this_source += page_bytes
                pages_fetched += 1

                # Simulate parsing: extract 2-4 matches per page
                matches_found = random.randint(2, 4)

                if page_num <= 3 or page_num == src["pages"]:
                    log.info(
                        f"   📄 Page {page_num}/{src['pages']}: "
                        f"{page_bytes/1024:.1f} KB → {matches_found} matches parsed "
                        f"(HTML discarded from memory ✓)"
                    )
                elif page_num == 4:
                    log.info(f"   ... ({src['pages'] - 6} more pages processing)")

            src_elapsed_ms = (time.time() - src_start) * 1000
            total_bytes += bytes_this_source
            total_pages += pages_fetched
            total_time_ms += src_elapsed_ms

            scrape_results.append({
                "source": src["name"],
                "pages": pages_fetched,
                "bytes": bytes_this_source,
                "time_ms": src_elapsed_ms,
            })

            log.info(
                f"   ✅ {src['name']}: {pages_fetched} pages, "
                f"{bytes_this_source/1024:.0f} KB, {src_elapsed_ms:.0f}ms"
            )

        # Summary table
        table = Table(title="🕷️ Scraping Performance Summary", show_lines=True)
        table.add_column("Source", style="cyan")
        table.add_column("Pages", justify="right")
        table.add_column("Data (KB)", justify="right")
        table.add_column("Time (ms)", justify="right")
        table.add_column("Speed (KB/s)", justify="right")

        for r in scrape_results:
            speed = (r["bytes"] / 1024) / max(0.001, r["time_ms"] / 1000)
            table.add_row(
                r["source"],
                str(r["pages"]),
                f"{r['bytes']/1024:.0f}",
                f"{r['time_ms']:.0f}",
                f"{speed:.0f}",
            )

        table.add_row(
            "[bold]TOTAL[/bold]",
            f"[bold]{total_pages}[/bold]",
            f"[bold]{total_bytes/1024:.0f}[/bold]",
            f"[bold]{total_time_ms:.0f}[/bold]",
            f"[bold]{(total_bytes/1024)/max(0.001, total_time_ms/1000):.0f}[/bold]",
            style="bold green",
        )
        console.print(table)

        log.info(
            f"🏁 Total: {total_pages} pages, {total_bytes/1024:.0f} KB, "
            f"{total_time_ms:.0f}ms — all HTML cleared from RAM ✓"
        )

        # ── Data Retention: ingest into scraper node and broadcast ──
        scraper_node = self.nodes[0]  # First node is the scraper
        new_records = 0
        duplicate_records = 0
        for match_key, data in SIMULATED_SCRAPED_DATA.items():
            rec = scraper_node.ingest_scraped_data("match", data)
            if rec:
                new_records += 1
                # Broadcast SCRAPE_DATA to all peers
                msg = P2PMessage(
                    message_type=MessageType.SCRAPE_DATA.value,
                    sender_id=scraper_node.node_id,
                    payload={
                        "data_hash": rec.data_hash,
                        "data_type": rec.data_type,
                        "payload": rec.payload,
                        "source_node_id": rec.source_node_id,
                    },
                )
                self.transport.broadcast(scraper_node.node_id, msg)
            else:
                duplicate_records += 1

        # Peers receive and store scraped data (dedup happens automatically)
        peer_new_total = 0
        peer_dup_total = 0
        for node in self.nodes:
            if node.node_id == scraper_node.node_id:
                continue
            messages = self.transport.get_pending(node.node_id)
            for msg in messages:
                if msg.message_type == MessageType.SCRAPE_DATA.value:
                    record = ScrapedRecord(
                        data_hash=msg.payload["data_hash"],
                        source_node_id=msg.payload["source_node_id"],
                        data_type=msg.payload["data_type"],
                        payload=msg.payload["payload"],
                    )
                    if node.receive_scraped_data(record):
                        peer_new_total += 1
                    else:
                        peer_dup_total += 1

        log.info(
            f"📦 Data retention: {new_records} new records ingested, "
            f"{duplicate_records} duplicates skipped at source"
        )
        log.info(
            f"📡 P2P propagation: {peer_new_total} new records across peers, "
            f"{peer_dup_total} duplicates rejected"
        )

        # Data store summary
        from rich.table import Table as RichTable
        ds_table = RichTable(title="📦 P2P Data Store Summary", show_lines=True)
        ds_table.add_column("Node", style="cyan")
        ds_table.add_column("Records", justify="right")
        ds_table.add_column("Types", justify="left")
        for node in self.nodes:
            summary = node.data_store.to_summary()
            types_str = ", ".join(f"{k}:{v}" for k, v in summary["by_type"].items()) or "—"
            ds_table.add_row(node.node_id[:8], str(summary["total"]), types_str)
        console.print(ds_table)

        return SIMULATED_SCRAPED_DATA

    # ── Phase C: Data Processing & Validation ───────────

    def _process_and_validate_data(self, scraped_data: dict, console) -> dict:
        """Process and validate scraped data — proofreader checks."""
        from rich.table import Table

        console.rule("[bold green]⚙️ Phase C: Data Processing & Validation[/bold green]", style="green")
        processed = {}

        for match_key, data in scraped_data.items():
            log.info(f"\n📦 Processing: {match_key}")

            # 1. Range checks
            stats = data.get("stats", {})
            range_ok = True
            for k, v in stats.items():
                if "possession" in k and not (0 <= v <= 100):
                    log.warning(f"   ⚠️  Out of range: {k}={v}")
                    range_ok = False
                if "shots" in k and not (0 <= v <= 40):
                    log.warning(f"   ⚠️  Out of range: {k}={v}")
                    range_ok = False

            # 2. Consistency check: possession sums to ~100
            poss_total = stats.get("possession_h", 0) + stats.get("possession_a", 0)
            if abs(poss_total - 100) > 5:
                log.warning(f"   ⚠️  Possession inconsistent: {poss_total} (≈100 expected)")
            else:
                log.info(f"   ✅ Possession consistent: {poss_total}%")

            # 3. Plausibility: Elo range
            for team_type in ["home_elo", "away_elo"]:
                elo = data.get(team_type, 0)
                if 800 <= elo <= 2200:
                    log.info(f"   ✅ {team_type}: {elo} (valid range)")
                else:
                    log.warning(f"   ⚠️  {team_type}: {elo} (suspicious)")

            # 4. Feature extraction summary
            n_features = 87
            form_pts = sum(data.get("home_form", []))
            log.info(f"   📊 Feature extraction: {n_features} dimensions ({match_key})")
            log.info(f"   📊 Home form score: {form_pts}/15")
            log.info(f"   📊 Sentiment score: home={data.get('sentiment_home', 0):.2f}, away={data.get('sentiment_away', 0):.2f}")

            if range_ok:
                processed[match_key] = data
                log.info(f"   ✅ {match_key} validated and processed")
            else:
                log.warning(f"   🔒 {match_key} quarantined")

        # Validation summary table
        table = Table(title="📋 Data Validation Summary", show_lines=True)
        table.add_column("Match", style="cyan")
        table.add_column("Status", justify="center")
        table.add_column("Features", justify="right")
        table.add_column("Ev Elo", justify="right")
        table.add_column("Dep Elo", justify="right")
        table.add_column("Ev Form", justify="right")

        for mk, d in scraped_data.items():
            status = "✅ Valid" if mk in processed else "🔒 Quarantined"
            form_pts = sum(d.get("home_form", []))
            table.add_row(mk, status, "87", str(d.get("home_elo", 0)),
                          str(d.get("away_elo", 0)), f"{form_pts}/15")
        console.print(table)

        return processed

    # ── Phase D: P2P Match Analysis Rounds ──────────────

    def _simulate_matches(self, processed_matches: dict) -> list[dict]:
        """Run P2P analysis rounds for each match."""
        results = []
        rng = random.Random(42)

        match_list = list(processed_matches.items())
        if not match_list:
            log.warning("⚠️  No processed match data, using synthetic data")
            match_list = [
                ("Galatasaray-Fenerbahçe", SIMULATED_SCRAPED_DATA["Galatasaray-Fenerbahçe"]),
            ]

        # Also add additional synthetic match-ups for reputation building
        extra_teams = [
            ("Konyaspor", "Sivasspor"),
            ("Samsunspor", "Alanyaspor"),
            ("Kayserispor", "Gaziantep FK"),
            ("Rizespor", "Pendikspor"),
            ("Galatasaray", "Beşiktaş"),
            ("Fenerbahçe", "Trabzonspor"),
            ("Kasımpaşa", "Antalyaspor"),
        ]

        log.info(f"\n{'═' * 70}")
        log.info(f"⚽ Phase D: P2P Analysis Rounds ({len(match_list)} scraped + {len(extra_teams)} extra matches)")
        log.info(f"{'═' * 70}")

        # Process scraped matches first
        for match_idx, (match_key, data) in enumerate(match_list):
            home = data["home_team"]
            away = data["away_team"]
            match_id = hashlib.sha256(f"{home}:{away}:{match_idx}".encode()).hexdigest()[:16]
            true_home_prob = min(0.85, max(0.15,
                data["home_elo"] / (data["home_elo"] + data["away_elo"]) +
                data.get("sentiment_home", 0.5) * 0.1 - 0.05
            ))

            self._run_single_match_round(match_idx, home, away, match_id, true_home_prob, rng, results, match_data=data)

        # Additional matches for reputation building
        for extra_idx, (home, away) in enumerate(extra_teams):
            match_idx = len(match_list) + extra_idx
            match_id = hashlib.sha256(f"{home}:{away}:{match_idx}".encode()).hexdigest()[:16]
            true_home_prob = rng.uniform(0.25, 0.65)

            self._run_single_match_round(match_idx, home, away, match_id, true_home_prob, rng, results)

        return results

    def _run_single_match_round(self, match_idx, home, away, match_id, true_home_prob, rng, results, match_data=None):
        """Execute one P2P round: local analysis → broadcast → receive → ensemble → validate."""
        log.info(f"\n{'─' * 60}")
        log.info(f"⚽ Match {match_idx + 1}: {home} vs {away} (ID: {match_id[:8]})")
        log.info(f"{'─' * 60}")

        # Each node produces local analysis
        log.info("📊 Local GBDT analyses generating...")
        for node in self.nodes:
            analysis = node.produce_analysis(match_id, base_home_prob=true_home_prob)
            msg = P2PMessage(
                message_type=MessageType.ANALYSIS.value,
                sender_id=node.node_id,
                payload=analysis.to_dict(),
            )
            self.transport.broadcast(node.node_id, msg)

        # Receive peer analyses
        for node in self.nodes:
            messages = self.transport.get_pending(node.node_id)
            for msg in messages:
                if msg.message_type == MessageType.ANALYSIS.value:
                    peer_analysis = PeerAnalysis(
                        analysis_id=msg.payload["analysis_id"],
                        node_id=msg.sender_id,
                        match_id=msg.payload["match_id"],
                        home_win_prob=msg.payload["distribution"]["home_win"],
                        draw_prob=msg.payload["distribution"]["draw"],
                        away_win_prob=msg.payload["distribution"]["away_win"],
                        confidence=msg.payload["confidence"],
                    )
                    node.receive_peer_analysis(peer_analysis)

        # Ensemble
        log.info("🔀 Reputation-weighted ensemble predictions...")
        for node in self.nodes:
            node.compute_ensemble(match_id)

        # Simulate result & validate
        actual_result = self._simulate_result(true_home_prob, rng, match_data)
        result_text = {"H": f"{home} won", "D": "Draw", "A": f"{away} won"}
        log.info(f"🏆 Result: {result_text.get(actual_result, actual_result)}")

        for node in self.nodes:
            node.validate_outcome(match_id, actual_result)

        results.append({
            "match_id": match_id, "home": home, "away": away,
            "result": actual_result, "true_home_prob": true_home_prob,
        })

    # ── Phase E: Turkish Q&A Through P2P ───────────────

    def _run_turkish_qa_pipeline(self, console):
        """
        Run Turkish questions through the P2P network.
        Each node classifies, analyzes, and composes a Turkish response.
        The lead node's ensemble answer is shown.
        """
        from rich.panel import Panel

        console.rule("[bold magenta]🗣️ Phase E: Turkish Q&A Pipeline (P2P)[/bold magenta]", style="magenta")
        log.info(f"📋 {len(P2P_DEMO_QUESTIONS)} Turkish questions to process through P2P network...\n")

        lead_node = self.nodes[0]  # Lead node composes final answers

        for q_idx, (match_key, question) in enumerate(P2P_DEMO_QUESTIONS, 1):
            log.info(f"{'─' * 60}")
            log.info(f"❓ Q{q_idx}: \"{question}\"")
            log.info(f"   📌 Match: {match_key}")

            # Step 1: TQU — Intent classification
            intent, confidence = _classify_question(question)
            log.info(f"   🧠 TQU → intent={intent}, confidence={confidence:.2f}")

            # Step 2: Get match data (from scraped data)
            match_data = SIMULATED_SCRAPED_DATA.get(match_key)
            if not match_data:
                log.warning(f"   ⚠️  Match data not found: {match_key}")
                continue

            # Step 3: Record query intent on all nodes (QID)
            match_id = hashlib.sha256(
                f"{match_data['home_team']}:{match_data['away_team']}:0".encode()
            ).hexdigest()[:16]

            for node in self.nodes:
                node.record_query_intent(match_id, intent, confidence)

            # Step 4: Get P2P ensemble from lead node
            ensemble = lead_node.compute_ensemble(match_id)
            # Step 5: Produce fresh analysis if no ensemble exists
            if not ensemble:
                ensemble = lead_node.produce_analysis(match_id, base_home_prob=0.55)

            # Step 6: TRC — Compose Turkish response
            answer = _compose_turkish_answer(intent, match_data, ensemble)
            log.info(f"   🤖 TRC response composed ({len(answer)} chars)")

            # Display as rich panel
            console.print(Panel(
                answer,
                title=f"[bold]Soru {q_idx}: {question}[/bold]",
                subtitle=f"intent={intent} | confidence=%{confidence*100:.0f} | P2P ensemble",
                border_style="green" if confidence > 0.5 else "yellow",
                padding=(0, 2),
            ))
            console.print()

        # ── QID: Broadcast query intent distributions across P2P ──
        log.info("\n📊 Broadcasting query intent distributions across P2P network...")
        qid_messages_sent = 0
        for node in self.nodes:
            for mid in list(node.query_intents.keys()):
                payload = node.get_query_intent_payload(mid)
                if payload:
                    msg = P2PMessage(
                        message_type=MessageType.QUERY_INTENT.value,
                        sender_id=node.node_id,
                        payload=payload,
                    )
                    self.transport.broadcast(node.node_id, msg)
                    qid_messages_sent += 1

        # Peers receive and merge
        qid_records_merged = 0
        for node in self.nodes:
            messages = self.transport.get_pending(node.node_id)
            for msg in messages:
                if msg.message_type == MessageType.QUERY_INTENT.value:
                    qid_records_merged += node.receive_query_intents(msg.payload)

        log.info(f"📡 QID: {qid_messages_sent} broadcasts, {qid_records_merged} records merged across peers")

        # Show aggregated distribution for lead node
        for mid in lead_node.query_intents:
            dist = lead_node.get_query_intent_distribution(mid)
            top_3 = sorted(dist.items(), key=lambda x: x[1], reverse=True)[:3]
            top_str = ", ".join(f"{k}={v:.2f}" for k, v in top_3)
            log.info(f"   📈 {mid[:8]}: volume={len(lead_node.query_intents[mid])}, top=[{top_str}]")

    # ── Helpers ──────────────────────────────────────────

    def _simulate_result(self, home_prob: float, rng: random.Random, match_data: dict | None = None) -> str:
        """
        Determine match result.
        Uses actual result from real data if available, otherwise simulates.
        """
        actual_ft = match_data.get("_actual_ft") if match_data else None
        if actual_ft and len(actual_ft) == 2:
            h, a = actual_ft
            if h > a:
                return "H"
            elif h == a:
                return "D"
            else:
                return "A"
        # Fallback: simulate
        r = rng.random()
        draw_prob = 0.25
        if r < home_prob:
            return "H"
        elif r < home_prob + draw_prob:
            return "D"
        else:
            return "A"


# ── Scaling Test (20+ peers) ─────────────────────────────────────


def run_scaling_test(target_nodes: int = 25):
    """
    Stress test: create a network with target_nodes peers.
    Run 30 match rounds and measure consensus quality, message volume,
    reputation convergence, and data retention across all peers.
    """
    from rich.console import Console
    from rich.table import Table
    console = Console(force_terminal=True)

    console.rule(f"[bold cyan]📐 SCALING TEST — {target_nodes} PEERS[/bold cyan]", style="cyan")
    start = time.time()

    sim = P2PSimulation()
    sim.node_count = target_nodes
    sim._create_nodes()

    # Inject 10% biased nodes (Sybil test at scale)
    sybil_count = max(1, target_nodes // 10)
    for node in sim.nodes[-sybil_count:]:
        node.model_bias = random.uniform(0.15, 0.35)
    log.info(f"⚠️  {sybil_count} Sybil nodes injected")

    # Phase 1: Scrape data and propagate via P2P retention
    log.info("\n📦 Phase 1: Data ingestion & P2P propagation")
    scraper = sim.nodes[0]
    for match_key, data in SIMULATED_SCRAPED_DATA.items():
        rec = scraper.ingest_scraped_data("match", data)
        if rec:
            msg = P2PMessage(
                message_type=MessageType.SCRAPE_DATA.value,
                sender_id=scraper.node_id,
                payload={
                    "data_hash": rec.data_hash, "data_type": rec.data_type,
                    "payload": rec.payload, "source_node_id": rec.source_node_id,
                },
            )
            sim.transport.broadcast(scraper.node_id, msg)

    # All peers receive data
    for node in sim.nodes:
        if node.node_id == scraper.node_id:
            continue
        for msg in sim.transport.get_pending(node.node_id):
            if msg.message_type == MessageType.SCRAPE_DATA.value:
                record = ScrapedRecord(
                    data_hash=msg.payload["data_hash"],
                    source_node_id=msg.payload["source_node_id"],
                    data_type=msg.payload["data_type"],
                    payload=msg.payload["payload"],
                )
                node.receive_scraped_data(record)

    # Verify data retention: all nodes should have the data
    data_coverage = sum(1 for n in sim.nodes if n.data_store.size == scraper.data_store.size)
    log.info(f"📊 Data coverage: {data_coverage}/{target_nodes} nodes have full data ({scraper.data_store.size} records)")

    # Phase 2: Run 30 match analysis rounds
    rng = random.Random(42)
    n_rounds = 30
    total_messages = 0
    ensemble_diffs = []  # track how much ensembles differ from local

    log.info(f"\n⚽ Phase 2: {n_rounds} match rounds across {target_nodes} peers")
    for m in range(n_rounds):
        match_id = f"scale_match_{m}"
        true_prob = rng.uniform(0.20, 0.70)

        # Produce & broadcast
        for node in sim.nodes:
            a = node.produce_analysis(match_id, base_home_prob=true_prob)
            msg = P2PMessage(
                message_type=MessageType.ANALYSIS.value,
                sender_id=node.node_id,
                payload=a.to_dict(),
            )
            sim.transport.broadcast(node.node_id, msg)
            total_messages += len(sim.nodes) - 1

        # Receive
        for node in sim.nodes:
            for msg in sim.transport.get_pending(node.node_id):
                if msg.message_type == MessageType.ANALYSIS.value:
                    pa = PeerAnalysis(
                        analysis_id=msg.payload["analysis_id"],
                        node_id=msg.sender_id,
                        match_id=msg.payload["match_id"],
                        home_win_prob=msg.payload["distribution"]["home_win"],
                        draw_prob=msg.payload["distribution"]["draw"],
                        away_win_prob=msg.payload["distribution"]["away_win"],
                        confidence=msg.payload["confidence"],
                    )
                    node.receive_peer_analysis(pa)

        # Ensemble
        for node in sim.nodes:
            ens = node.compute_ensemble(match_id)
            local = node.analyses[match_id]
            if ens:
                diff = abs(ens.home_win_prob - local.home_win_prob)
                ensemble_diffs.append(diff)

        # Validate
        r = rng.random()
        actual = "H" if r < true_prob else ("D" if r < true_prob + 0.25 else "A")
        for node in sim.nodes:
            node.validate_outcome(match_id, actual)

    # Phase 3: Results
    console.rule("[bold cyan]📊 Scaling Test Results[/bold cyan]", style="cyan")

    summary = compute_network_summary(sim.nodes)
    avg_diff = sum(ensemble_diffs) / max(1, len(ensemble_diffs))

    table = Table(title=f"📐 Scaling Test: {target_nodes} Peers × {n_rounds} Rounds", show_lines=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")
    table.add_row("Total peers", str(target_nodes))
    table.add_row("Sybil peers", str(sybil_count))
    table.add_row("Match rounds", str(n_rounds))
    table.add_row("Total messages", f"{total_messages:,}")
    table.add_row("Msgs/round", f"{total_messages / n_rounds:.0f}")
    table.add_row("Avg accuracy", f"{summary.avg_accuracy:.1%}")
    table.add_row("Avg ensemble shift", f"{avg_diff:.3f}")
    table.add_row("Data coverage", f"{data_coverage}/{target_nodes}")
    table.add_row("Leaders", str(summary.leader_count))
    table.add_row("High trust", str(summary.high_count))
    table.add_row("Medium trust", str(summary.medium_count))
    table.add_row("Low trust", str(summary.low_count))
    table.add_row("New", str(summary.new_count))
    console.print(table)

    # Reputation matrix (top 10 nodes to keep readable)
    display_nodes = sim.nodes[:min(10, len(sim.nodes))]
    print_reputation_matrix(display_nodes)

    elapsed = time.time() - start
    console.print(f"\n✅ [bold green]Scaling test complete! ({elapsed:.1f}s)[/bold green]\n")
    return sim


# ── Churn Test (dynamic join/leave) ─────────────────────────────


def run_churn_test(initial_nodes: int = 10, peak_nodes: int = 25, n_rounds: int = 40):
    """
    Test dynamic peer churn: peers join and leave simultaneously during
    active match analysis rounds.

    Schedule:
      Rounds  1-10:  Start with initial_nodes, ramp up to peak_nodes (join phase)
      Rounds 11-20:  Stay at peak, some random churn (small join + leave)
      Rounds 21-30:  Ramp down to initial_nodes (leave phase)
      Rounds 31-40:  Stable at initial_nodes, measure recovery
    """
    from rich.console import Console
    from rich.table import Table
    console = Console(force_terminal=True)

    console.rule(
        f"[bold cyan]🔄 CHURN TEST — {initial_nodes}→{peak_nodes}→{initial_nodes} PEERS[/bold cyan]",
        style="cyan",
    )
    start = time.time()

    sim = P2PSimulation()
    sim.node_count = initial_nodes
    sim._create_nodes()

    # Seed data into the network
    scraper = sim.nodes[0]
    for match_key, data in SIMULATED_SCRAPED_DATA.items():
        rec = scraper.ingest_scraped_data("match", data)
        if rec:
            msg = P2PMessage(
                message_type=MessageType.SCRAPE_DATA.value,
                sender_id=scraper.node_id,
                payload={
                    "data_hash": rec.data_hash, "data_type": rec.data_type,
                    "payload": rec.payload, "source_node_id": rec.source_node_id,
                },
            )
            sim.transport.broadcast(scraper.node_id, msg)
    for node in sim.nodes:
        if node.node_id == scraper.node_id:
            continue
        for msg in sim.transport.get_pending(node.node_id):
            if msg.message_type == MessageType.SCRAPE_DATA.value:
                record = ScrapedRecord(
                    data_hash=msg.payload["data_hash"],
                    source_node_id=msg.payload["source_node_id"],
                    data_type=msg.payload["data_type"],
                    payload=msg.payload["payload"],
                )
                node.receive_scraped_data(record)

    rng = random.Random(777)
    round_log = []  # (round, node_count, accuracy, event)
    nodes_to_add_per_round = max(1, (peak_nodes - initial_nodes) // 10)
    nodes_to_remove_per_round = max(1, (peak_nodes - initial_nodes) // 10)

    for r in range(1, n_rounds + 1):
        event = ""

        # ── Churn schedule ──
        if r <= 10:
            # Ramp up
            for _ in range(nodes_to_add_per_round):
                if len(sim.nodes) < peak_nodes:
                    sim.add_node()
                    event = "JOIN"
        elif r <= 20:
            # Random churn at peak
            if rng.random() < 0.3 and len(sim.nodes) > initial_nodes:
                sim.remove_node()
                event = "LEAVE"
            if rng.random() < 0.3 and len(sim.nodes) < peak_nodes + 3:
                sim.add_node()
                event = event + "+JOIN" if event else "JOIN"
        elif r <= 30:
            # Ramp down
            for _ in range(nodes_to_remove_per_round):
                if len(sim.nodes) > initial_nodes:
                    sim.remove_node()
                    event = "LEAVE"
        else:
            # Stable recovery
            event = "STABLE"

        # ── Run one match round ──
        match_id = f"churn_match_{r}"
        true_prob = rng.uniform(0.25, 0.65)

        for node in sim.nodes:
            a = node.produce_analysis(match_id, base_home_prob=true_prob)
            msg = P2PMessage(
                message_type=MessageType.ANALYSIS.value,
                sender_id=node.node_id,
                payload=a.to_dict(),
            )
            sim.transport.broadcast(node.node_id, msg)

        for node in sim.nodes:
            for msg in sim.transport.get_pending(node.node_id):
                if msg.message_type == MessageType.ANALYSIS.value:
                    pa = PeerAnalysis(
                        analysis_id=msg.payload["analysis_id"],
                        node_id=msg.sender_id,
                        match_id=msg.payload["match_id"],
                        home_win_prob=msg.payload["distribution"]["home_win"],
                        draw_prob=msg.payload["distribution"]["draw"],
                        away_win_prob=msg.payload["distribution"]["away_win"],
                        confidence=msg.payload["confidence"],
                    )
                    node.receive_peer_analysis(pa)

        for node in sim.nodes:
            node.compute_ensemble(match_id)

        actual = "H" if rng.random() < true_prob else ("D" if rng.random() < 0.35 else "A")
        for node in sim.nodes:
            node.validate_outcome(match_id, actual)

        # Track
        summary = compute_network_summary(sim.nodes)
        data_coverage = sum(1 for n in sim.nodes if n.data_store.size > 0)
        round_log.append({
            "round": r, "nodes": len(sim.nodes),
            "accuracy": summary.avg_accuracy,
            "data_coverage": data_coverage,
            "event": event or "—",
        })

        if r % 5 == 0 or event:
            log.info(
                f"Round {r:2d}: {len(sim.nodes):2d} nodes | "
                f"acc={summary.avg_accuracy:.1%} | "
                f"data={data_coverage}/{len(sim.nodes)} | {event or '—'}"
            )

    # ── Churn Results ──
    console.rule("[bold cyan]📊 Churn Test Results[/bold cyan]", style="cyan")

    table = Table(title="🔄 Churn Test Timeline", show_lines=True)
    table.add_column("Rnd", justify="right", style="dim")
    table.add_column("Nodes", justify="right")
    table.add_column("Accuracy", justify="right")
    table.add_column("Data Cov", justify="right")
    table.add_column("Event", style="yellow")

    for entry in round_log:
        style = ""
        if "JOIN" in entry["event"]:
            style = "green"
        elif "LEAVE" in entry["event"]:
            style = "red"
        table.add_row(
            str(entry["round"]),
            str(entry["nodes"]),
            f"{entry['accuracy']:.1%}",
            f"{entry['data_coverage']}/{entry['nodes']}",
            entry["event"],
            style=style,
        )
    console.print(table)

    # Summary stats
    final_summary = compute_network_summary(sim.nodes)
    peak_count = max(e["nodes"] for e in round_log)
    min_count = min(e["nodes"] for e in round_log)
    stable_acc = [e["accuracy"] for e in round_log if e["round"] > 30]
    avg_stable_acc = sum(stable_acc) / max(1, len(stable_acc))

    summary_table = Table(title="📊 Churn Test Summary", show_lines=True)
    summary_table.add_column("Metric", style="cyan")
    summary_table.add_column("Value", justify="right")
    summary_table.add_row("Initial nodes", str(initial_nodes))
    summary_table.add_row("Peak nodes", str(peak_count))
    summary_table.add_row("Min nodes", str(min_count))
    summary_table.add_row("Final nodes", str(len(sim.nodes)))
    summary_table.add_row("Total rounds", str(n_rounds))
    summary_table.add_row("Nodes removed (total)", str(len(sim._removed_nodes)))
    summary_table.add_row("Final avg accuracy", f"{final_summary.avg_accuracy:.1%}")
    summary_table.add_row("Stable-phase accuracy", f"{avg_stable_acc:.1%}")
    summary_table.add_row("Data retention", f"{sum(1 for n in sim.nodes if n.data_store.size > 0)}/{len(sim.nodes)}")
    console.print(summary_table)

    elapsed = time.time() - start
    console.print(f"\n✅ [bold green]Churn test complete! ({elapsed:.1f}s)[/bold green]\n")
    return sim


if __name__ == "__main__":
    if "--scale-test" in sys.argv:
        count = 25
        for arg in sys.argv:
            if arg.startswith("--nodes="):
                count = int(arg.split("=")[1])
        run_scaling_test(target_nodes=count)
    elif "--churn-test" in sys.argv:
        run_churn_test()
    else:
        sim = P2PSimulation()
        sim.run()
