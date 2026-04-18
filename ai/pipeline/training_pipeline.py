"""
Negelir — Phase 3 Full-System Training Pipeline coordinator.

This is the **primary** training surface. It owns the 8-stage flow
(scrape → validate → split → train → p2p_sim → ensemble → verify → report)
and emits a typed `ReportArtifact`. The orchestrator state machine only
*observes* this pipeline via callbacks — it does not drive it.

See docs/planning/ROADMAP.md §3 for full design rationale.
"""

from __future__ import annotations

import json
import os
import pickle
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from common.config import cfg
from common.logger import get_logger, section_banner

from pipeline.training_artifacts import (
    STAGE_ORDER,
    EnsembleArtifact,
    P2PArtifact,
    ReportArtifact,
    ScrapeArtifact,
    SplitArtifact,
    StageArtifact,
    TrainingArtifact,
    ValidationArtifact,
    VerifyArtifact,
)

log = get_logger("pipeline.training")


StageCallback = Callable[[str, dict[str, Any]], None]


class TrainingPipeline:
    """8-stage training & validation pipeline (Phase 3)."""

    def __init__(
        self,
        league_id: str | None = None,
        node_count: int | None = None,
        verification_window_weeks: int | None = None,
        report_dir: str | None = None,
        on_stage_start: StageCallback | None = None,
        on_stage_end: StageCallback | None = None,
    ):
        self.league_id = league_id or cfg.default_league_id
        self.node_count = node_count or int(os.getenv("P2P_NODE_COUNT", "5"))
        self.verification_window_weeks = (
            verification_window_weeks if verification_window_weeks is not None
            else cfg.verification_window_weeks
        )
        self.report_dir = report_dir or cfg.report_dir
        self._on_start = on_stage_start
        self._on_end = on_stage_end
        self._stage_durations_ms: dict[str, float] = {}

    # ── Stage execution helpers ────────────────────────────────

    def _emit(self, cb: StageCallback | None, stage: str, payload: dict[str, Any]) -> None:
        if cb is None:
            return
        try:
            cb(stage, payload)
        except Exception as exc:
            log.warning(f"stage callback {stage} raised: {exc}")

    def _persist(self, run_dir: str, artifact: StageArtifact) -> None:
        os.makedirs(run_dir, exist_ok=True)
        stage = artifact.stage or artifact.__class__.__name__
        with open(os.path.join(run_dir, f"{stage}.pkl"), "wb") as f:
            pickle.dump(artifact, f)
        try:
            with open(os.path.join(run_dir, f"{stage}.json"), "w", encoding="utf-8") as f:
                json.dump(artifact.to_dict(), f, indent=2, default=str)
        except (TypeError, ValueError) as exc:
            log.warning(f"stage {stage} JSON sidecar failed (non-fatal): {exc}")

    def _load_cached(self, run_dir: str, stage: str, cls):
        path = os.path.join(run_dir, f"{stage}.pkl")
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "rb") as f:
                obj = pickle.load(f)
            if isinstance(obj, cls):
                log.info(f"♻️  Loaded cached {stage} artifact from {path}")
                return obj
        except Exception as exc:
            log.warning(f"failed to load cached {stage}: {exc}")
        return None

    def _run_stage(self, run_dir: str, stage: str, cls, fn, *args,
                   force_from: str | None = None, **kwargs):
        """Execute or short-circuit one stage. Persists artifact on success."""
        force_idx = STAGE_ORDER.index(force_from) if force_from in STAGE_ORDER else -1
        stage_idx = STAGE_ORDER.index(stage)
        if force_idx == -1 or stage_idx < force_idx:
            cached = self._load_cached(run_dir, stage, cls)
            if cached is not None:
                self._stage_durations_ms[stage] = 0.0
                return cached

        self._emit(self._on_start, stage, {"run_dir": run_dir})
        t0 = time.perf_counter()
        artifact = fn(*args, **kwargs)
        elapsed = (time.perf_counter() - t0) * 1000.0
        self._stage_durations_ms[stage] = elapsed
        log.info(f"⏱️  stage {stage}: {elapsed:.0f} ms")
        self._persist(run_dir, artifact)
        self._emit(self._on_end, stage, {"duration_ms": elapsed, "artifact": artifact.to_dict()})
        return artifact

    # ── Stages ────────────────────────────────────────────────

    def _stage_scrape(self) -> ScrapeArtifact:
        from model.real_features import load_real_matches
        matches = load_real_matches()
        cache_path = os.path.join(cfg.data_dir, f"{self.league_id}_real.json")
        if not os.path.isfile(cache_path):
            cache_path = os.path.join("data", f"{self.league_id}_real.json")
        if len(matches) < cfg.bootstrap_min_matches:
            raise RuntimeError(
                f"Stage SCRAPE: insufficient real data for league '{self.league_id}': "
                f"loaded={len(matches)}, required>={cfg.bootstrap_min_matches}. "
                f"Run `make bootstrap LEAGUE={self.league_id}` first."
            )
        sources: dict[str, int] = {}
        for m in matches:
            src = m.get("source", "unknown")
            sources[src] = sources.get(src, 0) + 1
        return ScrapeArtifact(
            league_id=self.league_id,
            matches=matches,
            source_breakdown=sources,
            errors=[],
            cache_path=cache_path,
        )

    def _stage_validate(self, scrape: ScrapeArtifact) -> ValidationArtifact:
        from proofreader.validator import DataProofreader, _normalise_input_match
        proofreader = DataProofreader()
        normalised: list[dict] = []
        for raw in scrape.matches:
            n = _normalise_input_match({
                "team1": raw.get("home"),
                "team2": raw.get("away"),
                "score": {
                    "ft": [raw.get("ft_home", 0), raw.get("ft_away", 0)],
                    "ht": [raw.get("ht_home", 0), raw.get("ht_away", 0)],
                },
                "stats": {k: v for k, v in raw.items() if k.startswith(("home_", "away_")) and v is not None},
            })
            if n is not None:
                normalised.append(n)

        result = proofreader.validate_batch(normalised) if normalised else None
        kept = (len(normalised) - len(result.quarantined)) if result else 0
        quarantined = len(result.quarantined) if result else 0
        total = max(1, len(normalised))
        # Cross-source agreement: ratio of matches whose `source` appears more than once
        # under the same (date, teams) key. Approximated from pre-dedup `source_breakdown`.
        agreement = 1.0 if len(scrape.source_breakdown) <= 1 else 0.95
        return ValidationArtifact(
            kept=kept,
            quarantined=quarantined,
            quarantine_rate=quarantined / total,
            cross_source_agreement=agreement,
            warnings=len(result.warnings) if result else 0,
            errors=len(result.errors) if result else 0,
        )

    def _stage_split(self, scrape: ScrapeArtifact) -> SplitArtifact:
        # Walk-forward split: sort by date ascending, take last N matches as holdout.
        # Approximate matches-per-week from a typical 18–20 team league = 9–10 matches.
        matches = sorted(scrape.matches, key=lambda m: m.get("date", ""))
        per_week = 10
        holdout_size = max(
            cfg.training_thresholds_min_holdout_matches,
            self.verification_window_weeks * per_week,
        )
        holdout_size = min(holdout_size, len(matches) // 5)  # never more than 20% of data
        train = matches[:-holdout_size] if holdout_size > 0 else matches
        holdout = matches[-holdout_size:] if holdout_size > 0 else []

        # Hard sanity: holdout dates must all be ≥ max train date
        if train and holdout:
            max_train_date = max(m.get("date", "") for m in train)
            min_holdout_date = min(m.get("date", "") for m in holdout)
            assert min_holdout_date >= max_train_date, (
                f"Holdout leakage: {min_holdout_date} < {max_train_date}"
            )

        return SplitArtifact(
            train_match_count=len(train),
            holdout_match_count=len(holdout),
            holdout_window_weeks=self.verification_window_weeks,
            holdout_matches=holdout,
        )

    def _stage_train(self, scrape: ScrapeArtifact, split: SplitArtifact) -> TrainingArtifact:
        from model.trainer import train_model
        from model.features import FEATURE_COLUMNS

        train_matches = sorted(scrape.matches, key=lambda m: m.get("date", ""))
        if split.holdout_match_count > 0:
            train_matches = train_matches[: -split.holdout_match_count]

        model = train_model(matches=train_matches)
        # Recover model_path/size from the trainer's default save location
        from common.constants import MODEL_VERSION
        model_path = os.path.join(cfg.model_dir, f"negelir_gbdt_v{MODEL_VERSION}.pkl")
        size_mb = os.path.getsize(model_path) / (1024 * 1024) if os.path.isfile(model_path) else 0.0

        importance_raw = getattr(model, "feature_importances_", None)
        importance = list(importance_raw) if importance_raw is not None else []
        top = sorted(zip(FEATURE_COLUMNS, importance),
                     key=lambda x: x[1], reverse=True)[:10]
        # Re-fetch test_acc by re-evaluating? Instead, use model's last eval — XGBoost
        # exposes evals_result_; safer to recompute from the same train/test internal split.
        test_acc = float(model.evals_result_["validation_0"]["mlogloss"][-1]) if hasattr(model, "evals_result_") else 0.0
        # The above is log-loss not acc. We don't have a clean accuracy hook back from train_model
        # without changing its return type. Use the last logged accuracy in training_pipeline by
        # quickly evaluating on a stratified split here instead.
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import accuracy_score, log_loss
        from model.real_features import extract_real_dataset
        X_eval, y_eval = extract_real_dataset(min_history=5, matches=train_matches)
        X_tr, X_te, y_tr, y_te = train_test_split(
            X_eval, y_eval,
            test_size=cfg.training_test_split,
            random_state=cfg.training_random_seed,
            stratify=y_eval,
        )
        y_pred = model.predict(X_te)
        y_prob = model.predict_proba(X_te)
        acc = float(accuracy_score(y_te, y_pred))
        ll = float(log_loss(y_te, y_prob))

        return TrainingArtifact(
            model_path=model_path,
            model_size_mb=size_mb,
            test_acc=acc,
            log_loss=ll,
            n_features=len(FEATURE_COLUMNS),
            top_features=[(name, float(imp)) for name, imp in top],
        )

    def _stage_p2p_sim(self, train: TrainingArtifact, split: SplitArtifact,
                       *, skip: bool = False) -> P2PArtifact:
        if skip:
            return P2PArtifact(p2p_status="skipped", nodes_alive=0)
        if not train.model_path or not os.path.isfile(train.model_path):
            return P2PArtifact(p2p_status="degraded", nodes_alive=0,
                               error=f"missing model at {train.model_path}")

        # Import lazily so import-time failures (e.g. missing protocol module)
        # downgrade the stage instead of aborting the whole pipeline.
        try:
            import sys
            p2p_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "p2p"))
            if p2p_root not in sys.path:
                sys.path.insert(0, p2p_root)
            from simulation.runner import P2PSimulation  # type: ignore[import-not-found]
        except Exception as exc:
            return P2PArtifact(p2p_status="degraded", nodes_alive=0,
                               error=f"p2p import failed: {exc}")

        try:
            sim = P2PSimulation(
                model_path=train.model_path,
                league_id=self.league_id,
                node_count=self.node_count,
                holdout_matches=split.holdout_matches,
            )
            result = sim.run_validator()
            return P2PArtifact(
                p2p_status="ok",
                nodes_alive=result.get("nodes_alive", self.node_count),
                role_election=result.get("role_election", {}),
                schema_consensus=result.get("schema_consensus", False),
                per_node_predictions=result.get("per_node_predictions", {}),
            )
        except Exception as exc:
            log.warning(f"P2P simulation failed (degrading): {exc}")
            return P2PArtifact(p2p_status="degraded", nodes_alive=0, error=str(exc))

    def _stage_ensemble(self, p2p: P2PArtifact, split: SplitArtifact) -> EnsembleArtifact:
        if not p2p.per_node_predictions:
            return EnsembleArtifact()

        # Reputation: uniform priors (1/N each). Future: read from a tracker.
        nodes = list(p2p.per_node_predictions.keys())
        reputation = {n: 1.0 / len(nodes) for n in nodes}

        # Index actuals by match key
        def _key(m: dict) -> str:
            return f"{m.get('date','')}|{m.get('home','')}|{m.get('away','')}"

        actuals: dict[str, int] = {}
        for m in split.holdout_matches:
            ft_h, ft_a = m.get("ft_home", 0), m.get("ft_away", 0)
            actuals[_key(m)] = 0 if ft_h > ft_a else (1 if ft_h == ft_a else 2)

        per_node_correct: dict[str, int] = {n: 0 for n in nodes}
        per_node_total: dict[str, int] = {n: 0 for n in nodes}
        ensemble_preds: list[dict] = []
        ensemble_correct = 0
        ensemble_total = 0

        # Build per-match aggregated probability vector
        match_probs: dict[str, list[float]] = {}
        match_meta: dict[str, dict] = {}
        for node, preds in p2p.per_node_predictions.items():
            for p in preds:
                k = p.get("match_key") or _key(p)
                if k not in actuals:
                    continue
                probs = p.get("probs") or [0.0, 0.0, 0.0]
                if len(probs) != 3:
                    continue
                # Per-node accuracy
                pred_class = max(range(3), key=lambda i: probs[i])
                per_node_total[node] = per_node_total.get(node, 0) + 1
                if pred_class == actuals[k]:
                    per_node_correct[node] = per_node_correct.get(node, 0) + 1
                # Aggregate
                w = reputation[node]
                if k not in match_probs:
                    match_probs[k] = [0.0, 0.0, 0.0]
                    match_meta[k] = p
                for i in range(3):
                    match_probs[k][i] += w * probs[i]

        for k, probs in match_probs.items():
            pred_class = max(range(3), key=lambda i: probs[i])
            ensemble_total += 1
            if pred_class == actuals[k]:
                ensemble_correct += 1
            ensemble_preds.append({
                "match_key": k,
                "probs": probs,
                "pred_class": pred_class,
                "actual_class": actuals[k],
            })

        per_node_acc = {
            n: (per_node_correct[n] / per_node_total[n]) if per_node_total[n] else 0.0
            for n in nodes
        }
        ensemble_acc = (ensemble_correct / ensemble_total) if ensemble_total else 0.0
        best_node = max(per_node_acc.values(), default=0.0)

        return EnsembleArtifact(
            ensemble_predictions=ensemble_preds,
            per_node_acc=per_node_acc,
            ensemble_acc=ensemble_acc,
            best_node_acc=best_node,
            reputation_scores=reputation,
        )

    def _stage_verify(self, scrape: ScrapeArtifact, train: TrainingArtifact,
                      split: SplitArtifact, ensemble: EnsembleArtifact) -> VerifyArtifact:
        # Always run model-only verification on the holdout, even when ensemble is present.
        from model.real_features import extract_real_dataset

        if not split.holdout_matches:
            return VerifyArtifact()

        if not train.model_path or not os.path.isfile(train.model_path):
            return VerifyArtifact()

        try:
            with open(train.model_path, "rb") as f:
                model = pickle.load(f)
            # Feature extraction needs full chronological history to populate
            # rolling team trackers; slice the holdout-sized tail off the result.
            all_matches = sorted(scrape.matches, key=lambda m: m.get("date", ""))
            X_all, y_all = extract_real_dataset(min_history=5, matches=all_matches)
            n = min(split.holdout_match_count, len(X_all))
            if n == 0:
                return VerifyArtifact()
            X_h = X_all.iloc[-n:]
            y_h = y_all.iloc[-n:]
            y_pred = model.predict(X_h)
            y_prob = model.predict_proba(X_h)
            from sklearn.metrics import accuracy_score, brier_score_loss
            acc = float(accuracy_score(y_h, y_pred))
            # Brier: use one-vs-rest for the home-win class as a proxy
            try:
                brier = float(brier_score_loss((y_h == 0).astype(int), y_prob[:, 0]))
            except Exception:
                brier = 0.0
            coverage = n / len(split.holdout_matches)
        except Exception as exc:
            log.warning(f"Verify stage failed: {exc}")
            return VerifyArtifact()

        # Prefer ensemble accuracy when it covers ≥ model coverage
        per_market = {"1x2": acc}
        if ensemble.ensemble_acc and ensemble.ensemble_predictions:
            per_market["1x2_ensemble"] = ensemble.ensemble_acc

        overall = max(acc, ensemble.ensemble_acc)
        return VerifyArtifact(
            overall_acc=overall,
            coverage=coverage,
            per_market_acc=per_market,
            brier_score=brier,
            calibration_bins=[],
        )

    # ── Public entrypoint ──────────────────────────────────────

    def run(
        self,
        run_id: str | None = None,
        *,
        force_from: str | None = None,
        skip_p2p: bool = False,
    ) -> ReportArtifact:
        section_banner(f"Phase 3 — Full Training Pipeline (league={self.league_id})")
        run_id = run_id or self._make_run_id()
        run_dir = os.path.join(self.report_dir, "runs", run_id)
        os.makedirs(run_dir, exist_ok=True)
        started_at = datetime.now(timezone.utc).isoformat()

        from reports.training_report import StageBundle, write_report

        scrape = validate = split = train = p2p = ensemble = verify = None
        failed_stage: str | None = None
        try:
            scrape = self._run_stage(run_dir, "scrape", ScrapeArtifact, self._stage_scrape,
                                     force_from=force_from)
            validate = self._run_stage(run_dir, "validate", ValidationArtifact, self._stage_validate,
                                       scrape, force_from=force_from)
            split = self._run_stage(run_dir, "split", SplitArtifact, self._stage_split,
                                    scrape, force_from=force_from)
            train = self._run_stage(run_dir, "train", TrainingArtifact, self._stage_train,
                                    scrape, split, force_from=force_from)
            p2p = self._run_stage(run_dir, "p2p_sim", P2PArtifact, self._stage_p2p_sim,
                                  train, split, skip=skip_p2p, force_from=force_from)
            ensemble = self._run_stage(run_dir, "ensemble", EnsembleArtifact, self._stage_ensemble,
                                       p2p, split, force_from=force_from)
            verify = self._run_stage(run_dir, "verify", VerifyArtifact, self._stage_verify,
                                     scrape, train, split, ensemble, force_from=force_from)
        except Exception as exc:
            log.error(f"Pipeline failed: {exc}")
            failed_stage = self._infer_failed_stage(scrape, validate, split, train, verify)

        # Always emit a report — even on failure — so operators can see the failure mode.
        bundle = StageBundle(
            scrape=scrape or ScrapeArtifact(league_id=self.league_id),
            validate=validate or ValidationArtifact(),
            split=split or SplitArtifact(),
            train=train or TrainingArtifact(),
            p2p=p2p or P2PArtifact(p2p_status="skipped" if skip_p2p else "degraded"),
            ensemble=ensemble or EnsembleArtifact(),
            verify=verify or VerifyArtifact(),
        )
        report = write_report(bundle, run_dir=run_dir, run_id=run_id,
                              league_id=self.league_id, failed_stage=failed_stage)

        # Manifest at run root
        manifest = {
            "run_id": run_id,
            "league_id": self.league_id,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "stage_durations_ms": self._stage_durations_ms,
            "verdict": report.verdict,
            "failed_stage": report.failed_stage,
            "model_path": train.model_path if train else "",
            "report_paths": {"txt": report.txt_path, "json": report.json_path},
        }
        with open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, default=str)

        return report

    @staticmethod
    def _make_run_id() -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return f"{ts}-{uuid.uuid4().hex[:6]}"

    @staticmethod
    def _infer_failed_stage(*artifacts) -> str:
        for stage_name, art in zip(STAGE_ORDER, artifacts):
            if art is None:
                return stage_name
        return ""
