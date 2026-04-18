"""
Negelir — Phase 3 training-pipeline report renderer.

Inputs: the typed `StageArtifact` dataclasses produced by `TrainingPipeline`.
Outputs:
  - `<run_dir>/report.txt`  — human-readable
  - `<run_dir>/report.json` — machine-readable, schema-versioned
  - `<report_dir>/latest_<league>.{txt,json}` copies for easy access
  - `<report_dir>/history.jsonl` append-only one-line summary

Verdict logic lives here so thresholds remain in `Config.training_thresholds`
and no caller has to re-derive PASS/FAIL.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone

from common.config import cfg
from common.logger import get_logger

from pipeline.training_artifacts import (
    EnsembleArtifact,
    P2PArtifact,
    ReportArtifact,
    ScrapeArtifact,
    SplitArtifact,
    TrainingArtifact,
    ValidationArtifact,
    VerifyArtifact,
)

log = get_logger("reports.training")

SCHEMA_VERSION = 1


@dataclass
class StageBundle:
    """All stage artifacts collected during a TrainingPipeline run."""

    scrape: ScrapeArtifact
    validate: ValidationArtifact
    split: SplitArtifact
    train: TrainingArtifact
    p2p: P2PArtifact
    ensemble: EnsembleArtifact
    verify: VerifyArtifact


def compute_verdict(bundle: StageBundle, *, failed_stage: str | None = None) -> tuple[str, str]:
    """Return (verdict, failed_stage_name) using thresholds from cfg.

    Verdict:
      PASS           — every hard-stage threshold met, P2P healthy.
      PASS_DEGRADED  — hard stages pass but p2p_status in {degraded, skipped}.
      FAIL           — any hard stage misses its threshold.
    """
    th = cfg.training_thresholds

    if failed_stage:
        return "FAIL", failed_stage

    if bundle.validate.quarantine_rate > float(th["quarantine_max"]):
        return "FAIL", "validate"
    if bundle.split.holdout_match_count < int(th["min_holdout_matches"]):
        return "FAIL", "split"
    if bundle.train.test_acc < float(th["model_acc"]):
        return "FAIL", "train"
    if bundle.verify.overall_acc < float(th["ensemble_acc"]):
        return "FAIL", "verify"

    if bundle.p2p.p2p_status in ("degraded", "skipped"):
        return "PASS_DEGRADED", ""
    if bundle.p2p.nodes_alive < int(th["min_nodes_alive"]):
        return "PASS_DEGRADED", ""

    return "PASS", ""


def _format_pct(x: float) -> str:
    return f"{100.0 * x:.1f}%"


def render_text(bundle: StageBundle, *, run_id: str, league_id: str,
                verdict: str, failed_stage: str) -> str:
    th = cfg.training_thresholds
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    verdict_icon = {"PASS": "✅", "PASS_DEGRADED": "⚠️ ", "FAIL": "❌"}[verdict]

    top_feats = "\n".join(
        f"     {i+1:>2}. {name}: {imp:.4f}"
        for i, (name, imp) in enumerate(bundle.train.top_features[:5])
    ) or "     (none)"

    per_node = bundle.ensemble.per_node_acc
    per_node_line = (
        ", ".join(f"{n}={_format_pct(a)}" for n, a in sorted(per_node.items()))
        if per_node else "(none)"
    )

    per_market = bundle.verify.per_market_acc
    market_lines = "\n".join(
        f"   {name:.<25} {_format_pct(acc)}"
        for name, acc in sorted(per_market.items(), key=lambda kv: -kv[1])[:6]
    ) or "   (no markets evaluated)"

    return f"""\
NEGELIR — FULL SYSTEM TRAINING REPORT
======================================
Run ID:  {run_id}
Date:    {now}
League:  {league_id}
Schema:  v{SCHEMA_VERSION}

1. DATA COLLECTION
   Cache: {bundle.scrape.cache_path or "(unspecified)"}
   Matches loaded: {len(bundle.scrape.matches)}
   Source breakdown: {bundle.scrape.source_breakdown or "(unknown)"}
   Errors during scrape: {len(bundle.scrape.errors)}

2. PROOFREADING & VALIDATION
   Kept: {bundle.validate.kept}
   Quarantined: {bundle.validate.quarantined} ({_format_pct(bundle.validate.quarantine_rate)})
   Cross-source agreement: {_format_pct(bundle.validate.cross_source_agreement)}
   Warnings / Errors: {bundle.validate.warnings} / {bundle.validate.errors}
   Threshold (max quarantine): {_format_pct(float(th['quarantine_max']))}

3. TRAIN/HOLDOUT SPLIT
   Training matches: {bundle.split.train_match_count}
   Holdout matches:  {bundle.split.holdout_match_count}
   Holdout window:   last {bundle.split.holdout_window_weeks} matchweeks

4. MODEL TRAINING
   Model path: {bundle.train.model_path or "(not produced)"}
   Model size: {bundle.train.model_size_mb:.2f} MB
   Test accuracy: {_format_pct(bundle.train.test_acc)}  (threshold: {_format_pct(float(th['model_acc']))})
   Log loss: {bundle.train.log_loss:.4f}
   Features used: {bundle.train.n_features}
   Top features:
{top_feats}

5. P2P SIMULATION
   Status: {bundle.p2p.p2p_status}
   Nodes alive: {bundle.p2p.nodes_alive}  (threshold: {int(th['min_nodes_alive'])})
   Schema consensus: {"✓" if bundle.p2p.schema_consensus else "✗"}
   Role election entries: {len(bundle.p2p.role_election)}
   {f"Error: {bundle.p2p.error}" if bundle.p2p.error else ""}

6. ENSEMBLE PREDICTIONS
   Predicted matches: {len(bundle.ensemble.ensemble_predictions)}
   Per-node accuracy: {per_node_line}
   Best single node: {_format_pct(bundle.ensemble.best_node_acc)}
   Ensemble accuracy: {_format_pct(bundle.ensemble.ensemble_acc)}

7. VERIFICATION VS HOLDOUT OUTCOMES
   Overall accuracy: {_format_pct(bundle.verify.overall_acc)}  (threshold: {_format_pct(float(th['ensemble_acc']))})
   Coverage: {_format_pct(bundle.verify.coverage)}
   Brier score: {bundle.verify.brier_score:.4f}
   Per-market breakdown:
{market_lines}

8. VERDICT
   {verdict_icon} {verdict}{f" — failed stage: {failed_stage}" if failed_stage else ""}
"""


def render_json(bundle: StageBundle, *, run_id: str, league_id: str,
                verdict: str, failed_stage: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "league_id": league_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verdict": verdict,
        "failed_stage": failed_stage,
        "thresholds": cfg.training_thresholds,
        "stages": {
            "scrape": {
                "cache_path": bundle.scrape.cache_path,
                "matches_loaded": len(bundle.scrape.matches),
                "source_breakdown": bundle.scrape.source_breakdown,
                "errors": bundle.scrape.errors,
            },
            "validate": bundle.validate.to_dict(),
            "split": {
                "train_match_count": bundle.split.train_match_count,
                "holdout_match_count": bundle.split.holdout_match_count,
                "holdout_window_weeks": bundle.split.holdout_window_weeks,
            },
            "train": bundle.train.to_dict(),
            "p2p": {k: v for k, v in bundle.p2p.to_dict().items() if k != "per_node_predictions"},
            "ensemble": {
                "ensemble_acc": bundle.ensemble.ensemble_acc,
                "best_node_acc": bundle.ensemble.best_node_acc,
                "per_node_acc": bundle.ensemble.per_node_acc,
                "reputation_scores": bundle.ensemble.reputation_scores,
                "predicted_matches": len(bundle.ensemble.ensemble_predictions),
            },
            "verify": bundle.verify.to_dict(),
        },
    }


def write_report(bundle: StageBundle, *, run_dir: str, run_id: str,
                 league_id: str, failed_stage: str | None = None) -> ReportArtifact:
    """Render TXT + JSON, copy `latest_<league>.*`, and append history.jsonl."""
    verdict, failed = compute_verdict(bundle, failed_stage=failed_stage)

    os.makedirs(run_dir, exist_ok=True)
    txt_path = os.path.join(run_dir, "report.txt")
    json_path = os.path.join(run_dir, "report.json")

    txt = render_text(bundle, run_id=run_id, league_id=league_id,
                      verdict=verdict, failed_stage=failed)
    payload = render_json(bundle, run_id=run_id, league_id=league_id,
                          verdict=verdict, failed_stage=failed)

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(txt)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)

    # latest_<league>.* copies (not symlinks — Windows-safe)
    report_root = os.path.dirname(os.path.dirname(run_dir))  # report_dir/runs/<id> → report_dir
    if report_root and os.path.isdir(report_root):
        for ext, src in (("txt", txt_path), ("json", json_path)):
            dst = os.path.join(report_root, f"latest_{league_id}.{ext}")
            try:
                shutil.copyfile(src, dst)
            except OSError as exc:
                log.warning(f"Could not write {dst}: {exc}")

        # Append one-line trend record
        history_path = os.path.join(report_root, "history.jsonl")
        line = {
            "run_id": run_id,
            "league": league_id,
            "finished_at": payload["generated_at"],
            "verdict": verdict,
            "failed_stage": failed,
            "model_acc": bundle.train.test_acc,
            "ensemble_acc": bundle.verify.overall_acc,
            "quarantine_rate": bundle.validate.quarantine_rate,
            "p2p_status": bundle.p2p.p2p_status,
        }
        try:
            with open(history_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(line, default=str) + "\n")
        except OSError as exc:
            log.warning(f"Could not append history.jsonl: {exc}")

    log.info(f"📝 Report written: {txt_path}")
    log.info(f"📊 Verdict: {verdict}{f' (failed: {failed})' if failed else ''}")

    return ReportArtifact(
        schema_version=SCHEMA_VERSION,
        run_id=run_id,
        league_id=league_id,
        verdict=verdict,
        failed_stage=failed,
        txt_path=txt_path,
        json_path=json_path,
        p2p_status=bundle.p2p.p2p_status,
    )
