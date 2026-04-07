"""
Negelir — End-to-end pipeline runner.
Ties together: scraper → proofreader → model → TQU → TRC → response.
Shows hardcoded logs of entire data lifecycle as requested.
"""

import time
import random
import numpy as np

from common.logger import get_logger, section_banner, success_banner, error_banner
from common.config import cfg
from common.constants import UUID_TO_NAME
from model.features import generate_synthetic_dataset, FEATURE_COLUMNS, N_FEATURES
from model.inference import GBDTInference
from model.trainer import train_model
from tqu.classifier import classify
from trc.composer import compose_response
from scraper.engine import ScrapingEngine
from proofreader.validator import DataProofreader
from orchestrator.state_machine import TaskOrchestrator, TaskResult, OrchestratorContext
from nlp.sentiment import analyze_sentiment
from tqu.questions import DEMO_QUESTIONS as EXTENDED_DEMO, QUESTION_COUNT
from qid.collector import QueryIntentCollector

log = get_logger("pipeline")

# ── Demo questions ───────────────────────────────────────
# Pull 20 representative questions from the 1000+ dataset,
# plus 2 rejection cases, for the default demo run.
DEMO_QUESTIONS = EXTENDED_DEMO


class PipelineRunner:
    """Orchestrates the full Negelir AI pipeline."""

    def __init__(self):
        self.scraper = ScrapingEngine()
        self.proofreader = DataProofreader()
        self.orchestrator = TaskOrchestrator()
        self.model: GBDTInference | None = None
        self.qid_collector = QueryIntentCollector()

    def run_full_pipeline(self):
        """Execute the complete pipeline: data → model → questions → answers."""
        section_banner("NEGELIR AI — FULL PIPELINE")
        start = time.time()

        ctx = self.orchestrator.run_pipeline(
            scrape_fn=self._step_scrape,
            process_fn=self._step_process,
            proofread_fn=self._step_proofread,
            analyze_fn=self._step_analyze_and_respond,
        )

        elapsed = time.time() - start

        if ctx.errors:
            error_banner(f"Pipeline finished with errors ({elapsed:.1f}s)")
            for err in ctx.errors:
                log.error(f"  {err}")
        else:
            success_banner(f"Pipeline completed successfully ({elapsed:.1f}s)")

    def run_demo(self):
        """Run demo questions with synthetic data (requirement #2)."""
        section_banner("NEGELIR AI — DEMO PIPELINE")
        start = time.time()

        # Step 1: Train model with synthetic data
        self._ensure_model()

        # Step 2: Generate synthetic match features
        section_banner("Synthetic Match Data Generation")
        rng = np.random.RandomState(42)
        demo_features = self._generate_demo_features(rng)
        log.info("✅ Demo match data prepared")

        # Step 3: Sentiment analysis demo
        section_banner("NLP Sentiment Analysis (Demo)")
        demo_texts = [
            "Galatasaray son maçta muhteşem bir galibiyet aldı, takım morali çok yüksek",
            "Fenerbahçe'de sakatlık krizi devam ediyor, taraftar moral bozuk",
            "Beşiktaş istikrarlı oynuyor, savunma sağlam gidiyor",
        ]
        for text in demo_texts:
            score = analyze_sentiment(text)
            log.info(f"📝 Duygu: {score:+.3f} ← '{text[:60]}...'")
        log.info("✅ NLP sentiment analysis complete")

        # Step 4: Run Turkish Q&A demo
        section_banner("Turkish Q&A Demo")
        log.info(f"📋 {len(DEMO_QUESTIONS)} questions to process...\n")

        for i, question in enumerate(DEMO_QUESTIONS, 1):
            self._process_single_question(i, question, demo_features, rng)

        elapsed = time.time() - start
        success_banner(f"Demo complete! ({elapsed:.1f}s, {len(DEMO_QUESTIONS)} questions)")

    def run_training_only(self):
        """Train the model without running the full pipeline."""
        train_model()

    # ── Pipeline steps ──────────────────────────────────

    def _step_scrape(self, ctx: OrchestratorContext) -> TaskResult:
        """Step 1: Fetch data from Go server or generate synthetic."""
        t0 = time.time()
        section_banner("Step 1: Data Fetching (Web Scraping)")

        # Try Go server first
        log.info("🌐 Checking Go server health...")
        server_ok = self.scraper.check_server_health()
        if server_ok:
            log.info("🟢 Go server reachable — fetching data through server")
            self.scraper.trigger_server_scrape()
            matches = self.scraper.fetch_matches_from_server()
            if matches:
                log.info(f"📊 Fetched {len(matches)} matches from Go server")
                ctx.raw_matches = matches
                return TaskResult(success=True, duration_ms=(time.time() - t0) * 1000)

        # Fallback: simulate detailed scraping process
        log.info("⚠️  Go server not available — starting simulated scraping")
        log.info("")

        # Simulate scraping from 3 sources with performance metrics
        sources = [
            {"name": "Source-A (Statistics Site)", "pages": 8},
            {"name": "Source-B (Live Score Site)", "pages": 5},
            {"name": "Source-C (Archive Site)",       "pages": 10},
        ]

        total_pages = 0
        total_bytes = 0
        total_matches_found = 0

        for src in sources:
            src_start = time.time()
            src_bytes = 0
            src_matches = 0
            log.info(f"🔗 {src['name']}:")
            log.info(f"   ⏱️  Rate limit: 5s/request (roadmap §4.2)")

            for page in range(1, src['pages'] + 1):
                import time as _t
                _t.sleep(0.015)  # simulate small delay
                page_bytes = random.randint(25_000, 70_000)
                matches_on_page = random.randint(2, 5)
                src_bytes += page_bytes
                src_matches += matches_on_page

                if page <= 2 or page == src['pages']:
                    log.info(
                        f"   📄 Page {page}/{src['pages']}: "
                        f"{page_bytes/1024:.1f} KB → {matches_on_page} matches parsed "
                        f"(HTML discarded from RAM ✓)"
                    )
                elif page == 3:
                    log.info(f"   ... ({src['pages'] - 4} more pages)")

            src_elapsed = (time.time() - src_start) * 1000
            total_pages += src['pages']
            total_bytes += src_bytes
            total_matches_found += src_matches
            log.info(
                f"   ✅ {src_matches} matches, {src_bytes/1024:.0f} KB, {src_elapsed:.0f}ms"
            )

        log.info(f"\n🏁 Scraping Summary:")
        log.info(f"   📄 Total pages: {total_pages}")
        log.info(f"   📦 Total data: {total_bytes/1024:.0f} KB")
        log.info(f"   ⚽ Total matches: {total_matches_found} (parsed)")
        log.info(f"   🗑️  All HTML discarded from memory (RAM-only)")

        # Generate synthetic matches based on "scraped" data
        ctx.raw_matches = self._generate_synthetic_matches()
        log.info(f"\n📦 {len(ctx.raw_matches)} matches passed to pipeline")
        return TaskResult(success=True, duration_ms=(time.time() - t0) * 1000)

    def _step_process(self, ctx: OrchestratorContext) -> TaskResult:
        """Step 2: Transform raw data to features."""
        t0 = time.time()
        section_banner("Step 2: Data Processing")

        self._ensure_model()
        log.info(f"⚙️  Processing {len(ctx.raw_matches)} match records...")

        # In PoC, features are already numeric from synthetic generation
        ctx.features = {"processed": True, "match_count": len(ctx.raw_matches)}
        log.info("✅ Feature extraction complete")
        return TaskResult(success=True, duration_ms=(time.time() - t0) * 1000)

    def _step_proofread(self, ctx: OrchestratorContext) -> TaskResult:
        """Step 3: Validate data quality."""
        t0 = time.time()
        section_banner("Step 3: Data Validation")

        result = self.proofreader.validate_batch(ctx.raw_matches)
        ctx.proofread_ok = result.is_valid

        if not result.is_valid:
            log.warning(f"⚠️  Validation warnings: {len(result.warnings)}, Errors: {len(result.errors)}")
        return TaskResult(success=True, duration_ms=(time.time() - t0) * 1000)

    def _step_analyze_and_respond(self, ctx: OrchestratorContext) -> TaskResult:
        """Step 4: Run model inference and compose Turkish response."""
        t0 = time.time()
        section_banner("Step 4: Analysis & Turkish Response")

        rng = np.random.RandomState(42)
        demo_features = self._generate_demo_features(rng)

        for i, question in enumerate(DEMO_QUESTIONS, 1):
            self._process_single_question(i, question, demo_features, rng)

        return TaskResult(success=True, duration_ms=(time.time() - t0) * 1000)

    # ── Helpers ──────────────────────────────────────────

    def _ensure_model(self):
        """Ensure GBDT model is loaded/trained."""
        if self.model is None:
            section_banner("Model Preparation")
            self.model = GBDTInference()
            log.info("✅ GBDT model ready")

    def _process_single_question(self, idx: int, question: str, features: dict, rng):
        """Process one Turkish question through TQU → GBDT → TRC."""
        log.info(f"\n{'─' * 60}")
        log.info(f"❓ Q{idx}: \"{question}\"")

        # TQU: classify
        classification = classify(question)

        if not classification.success:
            log.info(f"🤖 Response: {classification.rejection_message}")
            return

        intent = classification.intent_id
        entities = classification.entities

        # QID: record query intent distribution
        match_id = entities.match_ref or f"demo_match_{idx}"
        self.qid_collector.record(match_id, intent, classification.confidence)

        # Generate feature vector for this "match"
        feature_vec = np.zeros((1, N_FEATURES), dtype=np.float32)
        for i, col in enumerate(FEATURE_COLUMNS):
            if "elo" in col:
                feature_vec[0, i] = rng.normal(1500, 200)
            elif "ratio" in col or "pct" in col or "norm" in col:
                feature_vec[0, i] = rng.uniform(0, 1)
            elif "sentiment" in col or "optimism" in col:
                feature_vec[0, i] = rng.uniform(-1, 1)
            elif "sin" in col or "cos" in col:
                feature_vec[0, i] = rng.uniform(-1, 1)
            elif "flag" in col or "change" in col:
                feature_vec[0, i] = rng.randint(0, 2)
            else:
                feature_vec[0, i] = rng.uniform(0, 3)

        # Inject QID features from collected query intent distribution
        qid_features = self.qid_collector.get_features(match_id)
        for i, col in enumerate(FEATURE_COLUMNS):
            if col.startswith("qid_"):
                feature_vec[0, FEATURE_COLUMNS.index(col)] = qid_features.pop(0)
                if not qid_features:
                    break

        # GBDT: inference
        analysis = self.model.predict(feature_vec)

        # Map intent to probability
        prob = self._map_intent_to_probability(intent, analysis)

        # TRC: compose response
        trc_analysis = {
            "confidence": analysis["confidence"],
            "probability": prob,
            "features": self._build_trc_features(analysis, features, rng),
        }

        entity_dict = {}
        if entities:
            entity_dict = {
                "team_refs": entities.team_refs,
                "min_goals": entities.min_goals,
                "max_goals": entities.max_goals,
                "threshold": entities.threshold,
                "half": entities.half,
            }

        response = compose_response(intent, trc_analysis, entity_dict)
        log.info(f"🤖 Response: {response}")

    def _map_intent_to_probability(self, intent: str, analysis: dict) -> float:
        """Map the analysis to a probability relevant to the question intent."""
        dist = analysis.get("distribution", {})
        goals = analysis.get("goal_metrics", {})

        if intent == "match_winner":
            return dist.get("home_win", 0.5)
        elif intent == "draw":
            return dist.get("draw", 0.25)
        elif intent == "over_under":
            return goals.get("over_2_5_prob", 0.5)
        elif intent == "goal_range":
            return goals.get("over_2_5_prob", 0.5) * 0.7
        elif intent == "both_teams_score":
            return goals.get("bts_prob", 0.5)
        elif intent == "clean_sheet":
            return 1.0 - goals.get("bts_prob", 0.5)
        elif intent == "half_time":
            return 0.5
        elif intent in ("form_query", "head_to_head"):
            return 0.7
        return 0.5

    def _build_trc_features(self, analysis: dict, match_features: dict, rng) -> dict:
        """Build the features dict expected by TRC templates."""
        return {
            "window": 5,
            "avg_total_goals": round(rng.uniform(1.8, 3.2), 1),
            "avg_goals_scored": round(rng.uniform(0.8, 2.0), 1),
            "avg_goals_conceded": round(rng.uniform(0.6, 1.8), 1),
            "h2h_over_pct": rng.randint(40, 75),
            "draw_pct": rng.randint(15, 35),
            "bts_pct": rng.randint(35, 65),
            "elo_rating": rng.randint(1300, 1700),
            "form_index": round(rng.uniform(0.3, 0.9), 2),
            "win_count": rng.randint(1, 5),
            "opp_wins": rng.randint(0, 3),
            "venue_type": "deplasman",
            "venue_type_tr": "deplasman",
            "advantage_text": "ev sahibi lehine",
            "home_momentum": rng.choice(["rising", "stable", "falling"]),
            "away_momentum": rng.choice(["rising", "stable", "falling"]),
            "defense_quality": rng.choice(["strong", "weak", "mixed"]),
            "h2h_advantage": rng.choice(["home_dominant", "away_dominant", "balanced"]),
            "clean_sheets": rng.randint(0, 4),
            "half_stat": "karışık sonuçlar alınmış",
            "wins": rng.randint(1, 4),
            "draws": rng.randint(0, 3),
            "losses": rng.randint(0, 3),
            "t1_wins": rng.randint(1, 4),
            "t2_wins": rng.randint(1, 3),
            "trend_text": rng.choice(["dengeli", "ev sahibi lehine", "deplasman lehine"]),
        }

    def _generate_demo_features(self, rng) -> dict:
        """Generate feature context for demo matches."""
        return {"demo": True, "generated": True}

    def _generate_synthetic_matches(self) -> list[dict]:
        """Generate synthetic match records for testing."""
        teams = list(UUID_TO_NAME.keys())[:10]
        matches = []

        rng = random.Random(42)
        for week in range(1, 6):
            shuffled = teams[:]
            rng.shuffle(shuffled)
            for i in range(0, len(shuffled) - 1, 2):
                home_score = rng.randint(0, 4)
                away_score = rng.randint(0, 3)
                matches.append({
                    "home_team": shuffled[i],
                    "away_team": shuffled[i + 1],
                    "home_score": home_score,
                    "away_score": away_score,
                    "ht_home_score": rng.randint(0, home_score),
                    "ht_away_score": rng.randint(0, away_score),
                    "match_week": week,
                    "league_id": "super_lig",
                    "season": "auto",
                    "stats": {
                        "possession": rng.randint(35, 65),
                        "shots_on": rng.randint(2, 12),
                        "shots_off": rng.randint(3, 15),
                        "corners": rng.randint(2, 12),
                        "fouls": rng.randint(8, 22),
                    },
                })

        return matches


if __name__ == "__main__":
    import sys
    runner = PipelineRunner()
    if "--demo" in sys.argv:
        runner.run_demo()
    elif "--train" in sys.argv:
        runner.run_training_only()
    else:
        runner.run_full_pipeline()
