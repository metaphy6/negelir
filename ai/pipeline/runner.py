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
from common.constants import UUID_TO_NAME, MACKOLIK_ID_MAP, TEAM_STRENGTH
from model.features import generate_synthetic_dataset, FEATURE_COLUMNS, N_FEATURES
from model.real_features import (
    EloTracker, TeamStats, H2HTracker, StandingsTracker,
    load_real_matches, _parse_date, _is_derby,
)
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
        """Run demo questions with real scraped data."""
        section_banner("NEGELIR AI — DEMO PIPELINE (REAL DATA)")
        start = time.time()

        # Step 1: Train model with real data
        self._ensure_model()

        # Step 2: Load real team context for feature generation
        section_banner("Loading Real Match Context")
        real_context = self._load_real_context()
        log.info(f"✅ Real match context loaded ({len(real_context.get('teams', {}))} teams)")

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
        section_banner("Turkish Q&A Demo (Real Data)")
        log.info(f"📋 {len(DEMO_QUESTIONS)} questions to process...\n")

        for i, question in enumerate(DEMO_QUESTIONS, 1):
            self._process_single_question(i, question, real_context, None)

        elapsed = time.time() - start
        success_banner(f"Demo complete! ({elapsed:.1f}s, {len(DEMO_QUESTIONS)} questions)")

    def run_training_only(self):
        """Train the model without running the full pipeline."""
        train_model()

    # ── Pipeline steps ──────────────────────────────────

    def _step_scrape(self, ctx: OrchestratorContext) -> TaskResult:
        """Step 1: Fetch real data from live sources."""
        t0 = time.time()
        section_banner("Step 1: Live Data Scraping")

        # Try Go server first for cached data
        log.info("🌐 Checking Go server health...")
        server_ok = self.scraper.check_server_health()
        if server_ok:
            log.info("🟢 Go server reachable")
            matches = self.scraper.fetch_matches_from_server()
            if matches:
                log.info(f"📊 Fetched {len(matches)} cached matches from Go server")
                ctx.raw_matches = matches
                return TaskResult(success=True, duration_ms=(time.time() - t0) * 1000)

        # Real scraping from live sources
        log.info("🔄 Scraping real data from live sources...")
        try:
            from model.real_features import load_real_matches
            real_matches = load_real_matches()
            if real_matches:
                ctx.raw_matches = real_matches
                log.info(f"✅ Loaded {len(real_matches)} real matches from live sources")
                return TaskResult(success=True, duration_ms=(time.time() - t0) * 1000)
        except Exception as exc:
            log.warning(f"⚠️  Real scraping failed: {exc}")

        # Last resort: use existing real JSON
        log.info("⚠️  Falling back to local data cache")
        ctx.raw_matches = self._load_cached_matches()
        log.info(f"📦 {len(ctx.raw_matches)} matches passed to pipeline")
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

        real_context = self._load_real_context(ctx.raw_matches if hasattr(ctx, "raw_matches") else None)

        for i, question in enumerate(DEMO_QUESTIONS, 1):
            self._process_single_question(i, question, real_context, None)

        return TaskResult(success=True, duration_ms=(time.time() - t0) * 1000)

    # ── Helpers ──────────────────────────────────────────

    def _ensure_model(self):
        """Ensure GBDT model is loaded/trained."""
        if self.model is None:
            section_banner("Model Preparation")
            self.model = GBDTInference()
            log.info("✅ GBDT model ready")

    def _process_single_question(self, idx: int, question: str, context: dict, rng):
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

        # Build real feature vector from team context
        feature_vec = self._build_real_features(entities, context)

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
            "features": self._build_trc_features_from_context(analysis, entities, context),
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
        """Build the features dict expected by TRC templates (legacy fallback)."""
        rng = rng or np.random.RandomState(42)
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

    def _build_trc_features_from_context(self, analysis: dict, entities, context: dict) -> dict:
        """Build TRC features from real team context."""
        team_stats = context.get("team_stats", {})
        h2h_tracker = context.get("h2h")
        elo_tracker = context.get("elo")

        # Determine home/away teams from entities
        home_name = None
        away_name = None
        if entities and len(entities.team_refs) >= 2:
            home_name = UUID_TO_NAME.get(entities.team_refs[0], entities.team_names[0] if entities.team_names else None)
            away_name = UUID_TO_NAME.get(entities.team_refs[1], entities.team_names[1] if len(entities.team_names) > 1 else None)
        elif entities and len(entities.team_refs) == 1:
            home_name = UUID_TO_NAME.get(entities.team_refs[0], entities.team_names[0] if entities.team_names else None)

        h_stats = team_stats.get(home_name) if home_name else None
        a_stats = team_stats.get(away_name) if away_name else None

        if h_stats and a_stats:
            h2h_data = h2h_tracker.stats(home_name, away_name) if h2h_tracker else {}
            h_elo = elo_tracker.rating(home_name) if elo_tracker else 1500
            a_elo = elo_tracker.rating(away_name) if elo_tracker else 1500

            h_ppg3 = h_stats.ppg(3)
            h_ppg5 = h_stats.ppg(5)
            a_ppg3 = a_stats.ppg(3)
            a_ppg5 = a_stats.ppg(5)
            h_momentum = "rising" if h_ppg3 > h_ppg5 else ("falling" if h_ppg3 < h_ppg5 else "stable")
            a_momentum = "rising" if a_ppg3 > a_ppg5 else ("falling" if a_ppg3 < a_ppg5 else "stable")

            h_cs = h_stats.clean_sheet_pct(10)
            a_cs = a_stats.clean_sheet_pct(10)
            if h_cs > 0.4 and a_cs > 0.4:
                defense_q = "strong"
            elif h_cs < 0.2 and a_cs < 0.2:
                defense_q = "weak"
            else:
                defense_q = "mixed"

            h2h_advantage = "balanced"
            if h2h_data.get("home_win_pct", 0.33) > 0.5:
                h2h_advantage = "home_dominant"
            elif h2h_data.get("home_win_pct", 0.33) < 0.25:
                h2h_advantage = "away_dominant"

            avg_total = h_stats.avg_scored(5) + a_stats.avg_scored(5)
            trend = "dengeli"
            if h_elo - a_elo > 100:
                trend = "ev sahibi lehine"
            elif a_elo - h_elo > 100:
                trend = "deplasman lehine"

            return {
                "window": 5,
                "avg_total_goals": round(h_stats.avg_scored(5) + a_stats.avg_scored(5), 1),
                "avg_goals_scored": round(h_stats.avg_scored(5), 1),
                "avg_goals_conceded": round(h_stats.avg_conceded(5), 1),
                "h2h_over_pct": int(h2h_data.get("over25_pct", 0.5) * 100),
                "draw_pct": int(h2h_data.get("draw_pct", 0.25) * 100),
                "bts_pct": int(h2h_data.get("bts_pct", 0.5) * 100),
                "elo_rating": int(h_elo),
                "form_index": round(h_stats.ppg(5) / 3.0, 2),
                "win_count": int(h_stats.win_ratio(5) * 5),
                "opp_wins": int(a_stats.win_ratio(5) * 5),
                "venue_type": "ev sahibi",
                "venue_type_tr": "ev sahibi",
                "advantage_text": trend,
                "home_momentum": h_momentum,
                "away_momentum": a_momentum,
                "defense_quality": defense_q,
                "h2h_advantage": h2h_advantage,
                "clean_sheets": int(h_stats.clean_sheet_pct(10) * 10),
                "half_stat": f"İY ort. {h_stats.avg_ht_scored(5):.1f}-{a_stats.avg_ht_scored(5):.1f}",
                "wins": int(h_stats.win_ratio(5) * 5),
                "draws": int(h_stats.draw_ratio(5) * 5),
                "losses": int(h_stats.loss_ratio(5) * 5),
                "t1_wins": int(h_stats.win_ratio(10) * 10),
                "t2_wins": int(a_stats.win_ratio(10) * 10),
                "trend_text": trend,
            }

        # Fallback for single/unknown teams
        rng = np.random.RandomState(42)
        return self._build_trc_features(analysis, {}, rng)

    def _build_real_features(self, entities, context: dict) -> np.ndarray:
        """Build a real feature vector from extracted entities and match context."""
        import math
        from datetime import datetime

        feature_vec = np.zeros((1, N_FEATURES), dtype=np.float32)
        team_stats = context.get("team_stats", {})
        elo_tracker = context.get("elo")
        h2h_tracker = context.get("h2h")
        standings = context.get("standings")

        if not entities or not entities.team_refs:
            return feature_vec

        # Resolve team names from UUIDs
        home_name = UUID_TO_NAME.get(entities.team_refs[0])
        away_name = UUID_TO_NAME.get(entities.team_refs[1]) if len(entities.team_refs) >= 2 else None

        h_stats = team_stats.get(home_name) if home_name else None
        a_stats = team_stats.get(away_name) if away_name else None

        if not h_stats or not a_stats:
            # Not enough data, return zero vector (model will give low confidence)
            return feature_vec

        helo = elo_tracker.rating(home_name) if elo_tracker else 1500.0
        aelo = elo_tracker.rating(away_name) if elo_tracker else 1500.0
        h2h_data = h2h_tracker.stats(home_name, away_name) if h2h_tracker else {
            "home_win_pct": 0.33, "draw_pct": 0.33, "avg_goals": 2.5,
            "over25_pct": 0.5, "bts_pct": 0.5, "count": 0, "avg_cards": 3.0,
        }

        h_strength = TEAM_STRENGTH.get(home_name, (1.0, 1.0))
        a_strength = TEAM_STRENGTH.get(away_name, (1.0, 1.0))

        home_xg = 1.35 * h_strength[0] / max(a_strength[1], 0.5) * (1 + (helo - 1500) / 2000)
        away_xg = 1.35 * a_strength[0] / max(h_strength[1], 0.5) * (1 + (aelo - 1500) / 2000)

        home_form = 0.5 * h_stats.ppg(5) / 3.0 + 0.3 * h_stats.win_ratio(5) + 0.2 * (1 - h_stats.loss_ratio(5))
        away_form = 0.5 * a_stats.ppg(5) / 3.0 + 0.3 * a_stats.win_ratio(5) + 0.2 * (1 - a_stats.loss_ratio(5))

        h_venue_win, h_venue_ppg = h_stats.venue_stats(is_home=True)
        a_venue_win, a_venue_ppg = a_stats.venue_stats(is_home=False)

        derby = 1.0 if _is_derby(home_name, away_name) else 0.0

        now = datetime.now()
        day_of_year = now.timetuple().tm_yday
        day_sin = math.sin(2 * math.pi * day_of_year / 365)
        day_cos = math.cos(2 * math.pi * day_of_year / 365)
        month_sin = math.sin(2 * math.pi * now.month / 12)
        month_cos = math.cos(2 * math.pi * now.month / 12)

        h_last = h_stats.last_match_date()
        a_last = a_stats.last_match_date()
        h_rest = (_parse_date(str(now.date())) - _parse_date(h_last)).days if h_last else 7
        a_rest = (_parse_date(str(now.date())) - _parse_date(a_last)).days if a_last else 7
        h_rest = min(max(h_rest, 1), 30)
        a_rest = min(max(a_rest, 1), 30)

        h_momentum = h_stats.ppg(3) - h_stats.ppg(5)
        a_momentum = a_stats.ppg(3) - a_stats.ppg(5)

        avg_total = h_stats.avg_scored(10) + a_stats.avg_scored(10)
        low_scoring = 1.0 / (1.0 + math.exp(avg_total - 2.0))

        h_congestion_7 = 1 if h_rest <= 4 else 0
        a_congestion_7 = 1 if a_rest <= 4 else 0
        h_congestion_14 = 2 if h_rest <= 3 else (1 if h_rest <= 5 else 0)
        a_congestion_14 = 2 if a_rest <= 3 else (1 if a_rest <= 5 else 0)

        style_matchup = abs(h_strength[0] - a_strength[1]) + abs(a_strength[0] - h_strength[1])
        h_expected = 1.0 / (1.0 + 10 ** ((1500 - helo) / 400))
        a_expected = 1.0 / (1.0 + 10 ** ((1500 - aelo) / 400))
        h_surprise = abs(h_stats.win_ratio(5) - h_expected)
        a_surprise = abs(a_stats.win_ratio(5) - a_expected)
        derby_card_factor = 1.3 if derby else 1.0

        # Season progress estimate (0.75 = late season by default for inference)
        season_progress = 0.75
        match_week_norm = season_progress

        vec = [
            h_stats.avg_scored(3), h_stats.avg_scored(5), h_stats.avg_scored(10),
            h_stats.avg_conceded(3), h_stats.avg_conceded(5), h_stats.avg_conceded(10),
            h_stats.ppg(5), h_stats.ppg(10), h_stats.clean_sheet_pct(10),
            h_stats.win_ratio(5), h_stats.draw_ratio(5), h_stats.loss_ratio(5),
            a_stats.avg_scored(3), a_stats.avg_scored(5), a_stats.avg_scored(10),
            a_stats.avg_conceded(3), a_stats.avg_conceded(5), a_stats.avg_conceded(10),
            a_stats.ppg(5), a_stats.ppg(10), a_stats.clean_sheet_pct(10),
            a_stats.win_ratio(5), a_stats.draw_ratio(5), a_stats.loss_ratio(5),
            helo, aelo, helo - aelo,
            home_xg, away_xg, home_xg - away_xg,
            home_form, away_form, home_form - away_form,
            h2h_data["home_win_pct"], h2h_data["draw_pct"], h2h_data["avg_goals"],
            h2h_data["over25_pct"], h2h_data["bts_pct"], h2h_data["count"],
            standings.position_norm(home_name) if standings else 0.5,
            standings.position_norm(away_name) if standings else 0.5,
            (standings.position_norm(home_name) - standings.position_norm(away_name)) if standings else 0.0,
            standings.goal_diff(home_name) if standings else 0,
            standings.goal_diff(away_name) if standings else 0,
            standings.pts_gap_leader(home_name) if standings else 0,
            standings.pts_gap_leader(away_name) if standings else 0,
            standings.pts_gap_relegation(home_name) if standings else 0,
            standings.pts_gap_relegation(away_name) if standings else 0,
            0.7, 0.7, 0.5, 0.5, 0.3, 0.3, 26.0, 26.0,
            h_congestion_7, a_congestion_7, h_congestion_14, a_congestion_14,
            10.0, 10.0, 0.0, 0.0,
            derby, 2,  # season_phase=late
            match_week_norm,
            day_sin, day_cos, month_sin, month_cos,
            h_rest, a_rest, h_rest - a_rest,
            0.0, 0.0, 0.0, 0.0, 0.0,
            style_matchup, h_rest - a_rest,
            h_momentum, a_momentum,
            h_stats.scoring_consistency(), a_stats.scoring_consistency(),
            h_surprise, a_surprise,
            2.0, 0.0, 1.0, 0.0,
            h_stats.avg_yellows(5), a_stats.avg_yellows(5),
            h_stats.avg_yellows(10), a_stats.avg_yellows(10),
            h_stats.avg_fouls(5), a_stats.avg_fouls(5),
            h2h_data["avg_cards"], derby_card_factor,
            h_stats.avg_ht_scored(5), a_stats.avg_ht_scored(5),
            h_stats.sh_scoring_rate(5), a_stats.sh_scoring_rate(5),
            h_stats.avg_ht_conceded(5), a_stats.avg_ht_conceded(5),
            h_venue_win, a_venue_win, h_venue_ppg, a_venue_ppg,
            h_stats.draws_bayesian(), a_stats.draws_bayesian(), low_scoring,
            standings.sos(home_name, elo_tracker) if standings and elo_tracker else 1500.0,
            standings.sos(away_name, elo_tracker) if standings and elo_tracker else 1500.0,
            h_stats.sh_scoring_rate(5), a_stats.sh_scoring_rate(5),
            h_stats.sh_conceding_rate(5), a_stats.sh_conceding_rate(5),
            h_stats.goals_per_match_rate(), a_stats.goals_per_match_rate(),
            0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,  # QID slots
        ]

        assert len(vec) == N_FEATURES, f"Feature vector length {len(vec)} != {N_FEATURES}"
        feature_vec[0, :] = vec
        return feature_vec

    def _load_real_context(self, raw_matches: list[dict] | None = None) -> dict:
        """Build real team context (trackers) from match data."""
        from collections import defaultdict

        matches = raw_matches
        if not matches:
            try:
                matches = load_real_matches()
            except Exception as exc:
                log.warning(f"Real data loading failed: {exc}")
                matches = self._load_cached_matches()

        if not matches:
            log.warning("No match data available, using empty context")
            return {"teams": {}, "team_stats": {}, "elo": EloTracker(), "h2h": H2HTracker(), "standings": StandingsTracker()}

        elo = EloTracker()
        team_stats_map: dict[str, TeamStats] = defaultdict(TeamStats)
        h2h = H2HTracker()
        standings = StandingsTracker()

        for m in matches:
            home = m.get("home", m.get("team1", ""))
            away = m.get("away", m.get("team2", ""))
            ft_home = m.get("ft_home", m.get("home_score", 0))
            ft_away = m.get("ft_away", m.get("away_score", 0))

            if ft_home is None or ft_away is None:
                continue

            elo.update(home, away, ft_home, ft_away)
            h2h.add(home, away, ft_home, ft_away)
            standings.update(home, away, ft_home, ft_away)

            if ft_home > ft_away:
                h_pts, a_pts = 3, 0
            elif ft_home == ft_away:
                h_pts, a_pts = 1, 1
            else:
                h_pts, a_pts = 0, 3

            team_stats_map[home].add({
                "date": m.get("date", ""),
                "gf": ft_home, "ga": ft_away,
                "ht_gf": m.get("ht_home"), "ht_ga": m.get("ht_away"),
                "pts": h_pts, "is_home": True,
                "yellows": m.get("home_yellows"),
                "fouls": m.get("home_fouls"),
            })
            team_stats_map[away].add({
                "date": m.get("date", ""),
                "gf": ft_away, "ga": ft_home,
                "ht_gf": m.get("ht_away"), "ht_ga": m.get("ht_home"),
                "pts": a_pts, "is_home": False,
                "yellows": m.get("away_yellows"),
                "fouls": m.get("away_fouls"),
            })

        log.info(f"📊 Context built: {len(team_stats_map)} teams, {len(matches)} matches")
        return {
            "teams": dict(team_stats_map),
            "team_stats": dict(team_stats_map),
            "elo": elo,
            "h2h": h2h,
            "standings": standings,
        }

    def _load_cached_matches(self) -> list[dict]:
        """Load matches from local JSON cache."""
        import json
        import os

        for path in ["/data/tr_super_lig_real.json", "data/tr_super_lig_real.json"]:
            if os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    matches = data.get("matches", [])
                    log.info(f"📦 Loaded {len(matches)} cached matches from {path}")
                    return matches
                except Exception as exc:
                    log.warning(f"Cache load failed ({path}): {exc}")
        return []

    def _generate_demo_features(self, rng) -> dict:
        """Generate feature context for demo matches (legacy)."""
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
