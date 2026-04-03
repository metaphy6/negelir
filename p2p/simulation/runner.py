"""
Negelir P2P — Full network simulation runner.
Per roadmap §7: nodes produce analyses, share them, build reputations,
and the network collectively improves.

Includes:
  - Simulated web scraping with performance metrics
  - AI pipeline (TQU → GBDT → TRC) running across all nodes
  - Turkish question-answer demonstration through P2P network
  - Reputation-weighted ensemble results
"""

import hashlib
import os
import random
import sys
import time

from node.peer import PeerNode, PeerAnalysis, get_p2p_logger
from protocol.messages import P2PMessage, MessageType
from protocol.transport import SimulatedTransport
from reputation.tracker import compute_network_summary, print_reputation_matrix

log = get_p2p_logger("simulation")


# ── Simulated scraping data (per roadmap §4.2) ──────────
# Represents data that would be scraped from Turkish football sites
SIMULATED_SCRAPED_DATA = {
    "Galatasaray-Fenerbahçe": {
        "home_team": "Galatasaray", "away_team": "Fenerbahçe",
        "match_date": "2026-04-05", "league": "Süper Lig", "week": 30,
        "home_form": [3, 3, 1, 3, 0],  # W=3, D=1, L=0
        "away_form": [3, 1, 0, 3, 3],
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
        "home_form": [3, 0, 3, 1, 3],
        "away_form": [1, 3, 0, 3, 1],
        "h2h_last5": {"home_wins": 2, "away_wins": 2, "draws": 1, "avg_goals": 3.0},
        "home_elo": 1650, "away_elo": 1590,
        "home_avg_scored": 1.6, "away_avg_scored": 1.3,
        "home_avg_conceded": 1.0, "away_avg_conceded": 1.2,
        "sentiment_home": 0.60, "sentiment_away": 0.45,
        "stats": {"possession_h": 52, "possession_a": 48, "shots_on_h": 5, "shots_on_a": 5,
                  "corners_h": 6, "corners_a": 6, "fouls_h": 12, "fouls_a": 13},
    },
    "Başakşehir-Antalyaspor": {
        "home_team": "Başakşehir", "away_team": "Antalyaspor",
        "match_date": "2026-04-06", "league": "Süper Lig", "week": 30,
        "home_form": [3, 1, 3, 3, 1],
        "away_form": [0, 1, 0, 3, 0],
        "h2h_last5": {"home_wins": 3, "away_wins": 0, "draws": 2, "avg_goals": 2.2},
        "home_elo": 1600, "away_elo": 1440,
        "home_avg_scored": 1.5, "away_avg_scored": 0.9,
        "home_avg_conceded": 0.8, "away_avg_conceded": 1.6,
        "sentiment_home": 0.58, "sentiment_away": 0.25,
        "stats": {"possession_h": 58, "possession_a": 42, "shots_on_h": 7, "shots_on_a": 3,
                  "corners_h": 8, "corners_a": 3, "fouls_h": 11, "fouls_a": 18},
    },
}

# ── Turkish questions sent through P2P pipeline ──────────
# Extended set mapped to simulated match data (3 matches × ~7 questions each)
P2P_DEMO_QUESTIONS = [
    # Galatasaray-Fenerbahçe
    ("Galatasaray-Fenerbahçe", "Galatasaray bu maçı kazanır mı?"),
    ("Galatasaray-Fenerbahçe", "Bu maçta 2.5 üstü gol olur mu?"),
    ("Galatasaray-Fenerbahçe", "İki takım da gol atar mı?"),
    ("Galatasaray-Fenerbahçe", "Fenerbahçe galip gelir mi?"),
    ("Galatasaray-Fenerbahçe", "Bu maç berabere biter mi?"),
    ("Galatasaray-Fenerbahçe", "İlk yarıda gol olur mu?"),
    ("Galatasaray-Fenerbahçe", "Galatasaray kalesini gol yemeden korur mu?"),
    # Beşiktaş-Trabzonspor
    ("Beşiktaş-Trabzonspor", "Beşiktaş kazanır mı?"),
    ("Beşiktaş-Trabzonspor", "Bu maç berabere biter mi?"),
    ("Beşiktaş-Trabzonspor", "Bu maçta 3.5 üstü gol olur mu?"),
    ("Beşiktaş-Trabzonspor", "Trabzonspor galip gelebilir mi?"),
    ("Beşiktaş-Trabzonspor", "İki takım da gol atar mı?"),
    ("Beşiktaş-Trabzonspor", "İlk yarı nasıl biter?"),
    ("Beşiktaş-Trabzonspor", "Bu maçta kaç gol atılır?"),
    # Başakşehir-Antalyaspor
    ("Başakşehir-Antalyaspor", "Başakşehir kalesini gol yemeden korur mu?"),
    ("Başakşehir-Antalyaspor", "Maçta kaç gol atılır?"),
    ("Başakşehir-Antalyaspor", "Başakşehir bu maçı kazanır mı?"),
    ("Başakşehir-Antalyaspor", "Alt mı olur üst mü?"),
    ("Başakşehir-Antalyaspor", "Beraberlik olur mu sizce?"),
    ("Başakşehir-Antalyaspor", "Antalyaspor rakibini yenebilir mi?"),
    ("Başakşehir-Antalyaspor", "Her iki takım da gol bulur mu?"),
]

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
    """

    def __init__(self):
        self.node_count = int(os.getenv("P2P_NODE_COUNT", "5"))
        self.match_count = int(os.getenv("P2P_SIMULATION_MATCHES", "10"))
        self.nodes: list[PeerNode] = []
        self.transport = SimulatedTransport()

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
        console.print(f"\n✅ [bold green]Simulation complete! ({elapsed:.1f}s)[/bold green]\n")

    # ── Phase A: Node Creation ──────────────────────────

    def _create_nodes(self):
        """Create simulated P2P nodes."""
        log.info(f"📡 Creating {self.node_count} nodes...")

        for i in range(self.node_count):
            node_id = hashlib.sha256(f"node_{i}_negelir".encode()).hexdigest()[:16]
            node = PeerNode(node_id=node_id, port=9000 + i)
            self.nodes.append(node)
            self.transport.register_node(node_id)
            log.info(f"   🖥️  Node {i + 1}: {node_id[:8]} (port: {9000 + i})")

        # Inject one Sybil-like bad node for reputation testing
        if len(self.nodes) >= 2:
            self.nodes[-1].model_bias = 0.3
            log.info(f"   ⚠️  Node {self.nodes[-1].node_id[:8]}: deliberate bias (Sybil test)")

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

            self._run_single_match_round(match_idx, home, away, match_id, true_home_prob, rng, results)

        # Additional matches for reputation building
        for extra_idx, (home, away) in enumerate(extra_teams):
            match_idx = len(match_list) + extra_idx
            match_id = hashlib.sha256(f"{home}:{away}:{match_idx}".encode()).hexdigest()[:16]
            true_home_prob = rng.uniform(0.25, 0.65)

            self._run_single_match_round(match_idx, home, away, match_id, true_home_prob, rng, results)

        return results

    def _run_single_match_round(self, match_idx, home, away, match_id, true_home_prob, rng, results):
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
        actual_result = self._simulate_result(true_home_prob, rng)
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

            # Step 3: Get P2P ensemble from lead node
            match_id = hashlib.sha256(
                f"{match_data['home_team']}:{match_data['away_team']}:0".encode()
            ).hexdigest()[:16]

            ensemble = lead_node.compute_ensemble(match_id)
            if not ensemble:
                # Produce fresh analysis if no ensemble exists
                ensemble = lead_node.produce_analysis(match_id, base_home_prob=0.55)

            # Step 4: TRC — Compose Turkish response
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

    # ── Helpers ──────────────────────────────────────────

    def _simulate_result(self, home_prob: float, rng: random.Random) -> str:
        """Simulate a match result based on true probabilities."""
        r = rng.random()
        draw_prob = 0.25
        if r < home_prob:
            return "H"
        elif r < home_prob + draw_prob:
            return "D"
        else:
            return "A"


if __name__ == "__main__":
    sim = P2PSimulation()
    sim.run()
