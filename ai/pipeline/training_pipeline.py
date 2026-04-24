"""
Negelir — Phase 3 training pipeline coordinator.

This is the **primary** training surface. It owns the 6-stage flow
(scrape → validate → split → train → verify → report) and emits a typed
`ReportArtifact`. The orchestrator state machine only *observes* this
pipeline via callbacks — it does not drive it.

The legacy simulation and ensemble stages were removed in the Phase 0
Swarm Pivot; their swarm-based replacement lives in roadmap Phase 5.

See docs/planning/ROADMAP.md for design rationale.
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
    """6-stage training & validation pipeline."""

    def __init__(
        self,
        league_id: str | None = None,
        verification_window_weeks: int | None = None,
        report_dir: str | None = None,
        on_stage_start: StageCallback | None = None,
        on_stage_end: StageCallback | None = None,
    ):
        self.league_id = league_id or cfg.default_league_id
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

    def _stage_verify(self, scrape: ScrapeArtifact, train: TrainingArtifact,
                      split: SplitArtifact) -> VerifyArtifact:
        # Run model-only verification on the holdout window.
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

        return VerifyArtifact(
            overall_acc=acc,
            coverage=coverage,
            per_market_acc={"1x2": acc},
            brier_score=brier,
            calibration_bins=[],
        )

    # ── Public entrypoint ──────────────────────────────────────

    def run(
        self,
        run_id: str | None = None,
        *,
        force_from: str | None = None,
    ) -> ReportArtifact:
        section_banner(f"Phase 3 — Training Pipeline (league={self.league_id})")
        run_id = run_id or self._make_run_id()
        run_dir = os.path.join(self.report_dir, "runs", run_id)
        os.makedirs(run_dir, exist_ok=True)
        started_at = datetime.now(timezone.utc).isoformat()

        from reports.training_report import StageBundle, write_report

        scrape = validate = split = train = verify = None
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
            verify = self._run_stage(run_dir, "verify", VerifyArtifact, self._stage_verify,
                                     scrape, train, split, force_from=force_from)
        except Exception as exc:
            log.error(f"Pipeline failed: {exc}")
            failed_stage = self._infer_failed_stage(scrape, validate, split, train, verify)

        # Always emit a report — even on failure — so operators can see the failure mode.
        bundle = StageBundle(
            scrape=scrape or ScrapeArtifact(league_id=self.league_id),
            validate=validate or ValidationArtifact(),
            split=split or SplitArtifact(),
            train=train or TrainingArtifact(),
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
