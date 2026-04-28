"""Phase 5.5 — swarm-path backtester.

Replays historical matches through the live swarm chain
(predictors → consensus.v1) and reports per-predictor + swarm
calibration / accuracy / log-loss. This is the CI gate per
ROADMAP §5.3:

  * **Swarm gate.** Swarm log-loss ≤
    ``(1 - cfg.backtest_swarm_floor_pct)`` × best-individual
    predictor log-loss, computed on the trailing window. Skipped
    automatically when ``n_matches < cfg.backtest_min_n`` so a
    sparse seed corpus doesn't flap CI.

The harness loads ``data/<league>_real.json`` files, picks the most
recent ``--weeks`` weeks of matches with FT scores, drives each
match through the four must-status predictors + ``consensus.v1``,
and reports per-predictor + swarm metrics for the 1x2 market. The
JSON report lands in ``data/backtest/<utc-iso>.json`` and a
human-friendly Markdown summary alongside it.

Usage::

    PYTHONPATH=ai python3 -m xops.swarm_backtest --weeks 4
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

# Allow running outside the ai/ docker context.
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "ai"))

from common.config import cfg  # noqa: E402  pylint: disable=wrong-import-position
from swarm.agents.consensus import ConsensusAgent  # noqa: E402
from swarm.agents.payloads import (  # noqa: E402
    PredictFinal,
    PredictRequest,
    PredictVote,
)
from swarm.agents.predictors import (  # noqa: E402
    DixonColesPredictor,
    EloPredictor,
    XgbFormPredictor,
    XgbXgPredictor,
)
from swarm.agents.reactor import InMemoryLedger  # noqa: E402
from swarm.agents.topics import (  # noqa: E402
    PREDICT_FINAL,
    PREDICT_REQUEST,
    PREDICT_VOTE,
)
from swarm.sdk.types import Message  # noqa: E402


# Numerical floor for log-loss so a 0-prob outcome doesn't blow up
# the metric. Same convention as scikit-learn's ``log_loss``.
_LOGLOSS_EPS = 1e-15
_OUTCOMES_1X2 = ("H", "D", "A")
# 10 equal-width reliability bins for ECE — standard choice.
_ECE_BINS = 10


def _load_matches(data_dir: Path) -> list[dict[str, Any]]:
    """Flatten matches across every league file under ``data_dir``."""
    out: list[dict[str, Any]] = []
    for fp in sorted(data_dir.glob("*_real.json")):
        try:
            blob = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for m in blob.get("matches", []):
            score = m.get("score") or {}
            ft = score.get("ft")
            if not (isinstance(ft, list) and len(ft) == 2):
                continue  # skip un-played / cancelled
            try:
                date = datetime.fromisoformat(str(m["date"])).replace(tzinfo=timezone.utc)
            except (KeyError, ValueError):
                continue
            out.append({
                "date": date,
                "league_id": blob.get("league_id", "unknown"),
                "home": m.get("team1", "?"),
                "away": m.get("team2", "?"),
                "home_goals": int(ft[0]),
                "away_goals": int(ft[1]),
            })
    return out


def _outcome(home: int, away: int) -> str:
    if home > away:
        return "H"
    if home < away:
        return "A"
    return "D"


def _log_loss(p_actual: float) -> float:
    """Per-sample log-loss given the probability assigned to the
    realized outcome. Clipped so 0-prob events don't return inf."""
    return -math.log(max(min(p_actual, 1.0), _LOGLOSS_EPS))


def _brier(pmf: dict[str, float], actual: str) -> float:
    """1x2 Brier score: sum of squared errors across outcomes."""
    return sum(
        (pmf.get(o, 0.0) - (1.0 if o == actual else 0.0)) ** 2
        for o in _OUTCOMES_1X2
    )


def _ece(samples: list[tuple[float, bool]]) -> float:
    """Expected calibration error over ``(predicted_prob, was_correct)``.

    Bin by predicted prob (10 bins). Inside each bin: |mean(prob) -
    accuracy|. Weighted by bin size, normalized by total samples.
    """
    if not samples:
        return 0.0
    bins: list[list[tuple[float, bool]]] = [[] for _ in range(_ECE_BINS)]
    for p, hit in samples:
        idx = min(int(p * _ECE_BINS), _ECE_BINS - 1)
        bins[idx].append((p, hit))
    total = len(samples)
    err = 0.0
    for b in bins:
        if not b:
            continue
        mean_p = sum(p for p, _ in b) / len(b)
        acc = sum(1 for _, h in b if h) / len(b)
        err += (len(b) / total) * abs(mean_p - acc)
    return err


def _build_predictors() -> list[Any]:
    return [
        EloPredictor(),
        DixonColesPredictor(),
        XgbFormPredictor(),
        XgbXgPredictor(),
    ]


def _run_swarm(
    match: dict[str, Any],
) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    """Drive a single match through predictors + consensus.

    Returns ``(swarm_pmf, per_predictor_pmf)`` for the 1x2 market.
    """
    predictors = _build_predictors()
    consensus = ConsensusAgent(
        expected_predictors=tuple(p.predictor_id for p in predictors),
        ledger=InMemoryLedger(),
        clock_ms=lambda: 0.0,
        min_voters=2,
    )
    req = PredictRequest(
        request_id=f"bt-{match['date'].date().isoformat()}-{match['home']}-{match['away']}",
        match_id=f"{match['league_id']}:{match['home']}-{match['away']}",
        market="1x2",
        league_id=match["league_id"],
        features={"home_advantage": 0.55},
    )
    msg = Message.new(PREDICT_REQUEST, req.as_dict(), producer="backtest")

    per_predictor: dict[str, dict[str, float]] = {}
    swarm_pmf: dict[str, float] | None = None
    for p in predictors:
        for vote_msg in p.handle(msg):
            vote = PredictVote.from_dict(vote_msg.payload)
            per_predictor[vote.predictor_id] = dict(
                vote.distribution["market_outcomes"]
            )
            for final_msg in consensus.handle(vote_msg):
                if final_msg.envelope.topic == PREDICT_FINAL:
                    pf = PredictFinal.from_dict(final_msg.payload)
                    swarm_pmf = pf.distribution["market_outcomes"]
    if swarm_pmf is None:
        raise RuntimeError(f"swarm produced no predict.final for {req.request_id}")
    return swarm_pmf, per_predictor


def _accumulate(
    *,
    pmf: dict[str, float],
    actual: str,
    metrics: dict[str, Any],
) -> None:
    """In-place update of one entity's running metrics."""
    p_actual = float(pmf.get(actual, 0.0))
    predicted = max(_OUTCOMES_1X2, key=lambda o: pmf.get(o, 0.0))
    metrics["n"] += 1
    metrics["log_loss_sum"] += _log_loss(p_actual)
    metrics["brier_sum"] += _brier(pmf, actual)
    if predicted == actual:
        metrics["correct"] += 1
    metrics["per_outcome"][actual][1] += 1
    if predicted == actual:
        metrics["per_outcome"][actual][0] += 1
    # ECE samples on the predicted-class probability.
    metrics["ece_samples"].append((float(pmf.get(predicted, 0.0)), predicted == actual))


def _new_metrics() -> dict[str, Any]:
    return {
        "n": 0,
        "correct": 0,
        "log_loss_sum": 0.0,
        "brier_sum": 0.0,
        "per_outcome": {o: [0, 0] for o in _OUTCOMES_1X2},  # [correct, total]
        "ece_samples": [],
    }


def _finalize(metrics: dict[str, Any]) -> dict[str, Any]:
    n = metrics["n"]
    accuracy = metrics["correct"] / n if n else 0.0
    return {
        "n_matches": n,
        "correct": metrics["correct"],
        "accuracy": accuracy,
        "log_loss": metrics["log_loss_sum"] / n if n else 0.0,
        "brier": metrics["brier_sum"] / n if n else 0.0,
        "ece": _ece(metrics["ece_samples"]),
        "per_outcome": {
            o: {"correct": c, "total": t, "recall": (c / t if t else 0.0)}
            for o, (c, t) in metrics["per_outcome"].items()
        },
    }


def _evaluate(matches: Iterable[dict[str, Any]]) -> dict[str, Any]:
    swarm = _new_metrics()
    per_predictor: dict[str, dict[str, Any]] = {}
    for m in matches:
        actual = _outcome(m["home_goals"], m["away_goals"])
        swarm_pmf, predictor_pmfs = _run_swarm(m)
        _accumulate(pmf=swarm_pmf, actual=actual, metrics=swarm)
        for pid, pmf in predictor_pmfs.items():
            if pid not in per_predictor:
                per_predictor[pid] = _new_metrics()
            _accumulate(pmf=pmf, actual=actual, metrics=per_predictor[pid])

    return {
        "swarm": _finalize(swarm),
        "predictors": {
            pid: _finalize(m) for pid, m in sorted(per_predictor.items())
        },
    }


def _evaluate_gate(
    swarm_log_loss: float,
    predictor_log_losses: dict[str, float],
    *,
    n_matches: int,
    floor_pct: float,
    min_n: int,
) -> tuple[bool, str]:
    """ROADMAP §5.3 gate. Returns ``(passed, message)``."""
    if n_matches < min_n:
        return True, (
            f"gate skipped: n_matches={n_matches} < backtest_min_n={min_n}"
        )
    if not predictor_log_losses:
        return False, "gate failed: no predictor log-losses to compare against"
    best_individual = min(predictor_log_losses.values())
    threshold = (1.0 - floor_pct) * best_individual
    if swarm_log_loss <= threshold:
        return True, (
            f"gate passed: swarm log-loss {swarm_log_loss:.4f} ≤ "
            f"{threshold:.4f} = (1 - {floor_pct:.4f}) × best_individual "
            f"{best_individual:.4f}"
        )
    return False, (
        f"gate failed: swarm log-loss {swarm_log_loss:.4f} > "
        f"{threshold:.4f} = (1 - {floor_pct:.4f}) × best_individual "
        f"{best_individual:.4f}"
    )


def _write_reports(report: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = out_dir / f"{ts}.json"
    md_path = out_dir / f"{ts}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    swarm = report["swarm"]
    md = [
        f"# Swarm backtest — {ts}",
        "",
        f"- Window: **{report['window_start']} → {report['window_end']}** ({report['weeks']} weeks)",
        f"- Matches scored: **{swarm['n_matches']}**",
        f"- Floor (`backtest_swarm_floor_pct`): **{report['floor_pct']:.4f}**",
        f"- Min-N (`backtest_min_n`): **{report['min_n']}**",
        f"- Gate: **{'PASS' if report['gate_passed'] else 'FAIL'}** — {report['gate_message']}",
        "",
        "## Swarm metrics (1x2)",
        "",
        "| Accuracy | Log-loss | Brier | ECE |",
        "|---|---|---|---|",
        f"| {swarm['accuracy']:.4f} | {swarm['log_loss']:.4f} | "
        f"{swarm['brier']:.4f} | {swarm['ece']:.4f} |",
        "",
        "## Per-predictor metrics (1x2)",
        "",
        "| Predictor | N | Accuracy | Log-loss | Brier | ECE |",
        "|---|---|---|---|---|---|",
    ]
    for pid, m in report["predictors"].items():
        md.append(
            f"| `{pid}` | {m['n_matches']} | {m['accuracy']:.4f} | "
            f"{m['log_loss']:.4f} | {m['brier']:.4f} | {m['ece']:.4f} |"
        )
    md.extend([
        "",
        "## Per-outcome recall (swarm)",
        "",
        "| Outcome | Correct | Total | Recall |",
        "|---|---|---|---|",
    ])
    for o, stats in swarm["per_outcome"].items():
        md.append(
            f"| {o} | {stats['correct']} | {stats['total']} | {stats['recall']:.4f} |"
        )
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="swarm_backtest")
    parser.add_argument("--weeks", type=int, default=cfg.backtest_window_weeks)
    parser.add_argument("--data-dir", type=Path, default=_REPO_ROOT / "data")
    parser.add_argument("--out-dir", type=Path, default=_REPO_ROOT / "data" / "backtest")
    parser.add_argument(
        "--max-matches",
        type=int,
        default=200,
        help="Hard cap so CI runs stay quick (default 200)",
    )
    args = parser.parse_args(argv)

    matches = _load_matches(args.data_dir)
    if not matches:
        print("[swarm_backtest] no matches with FT scores found", file=sys.stderr)
        return 2

    matches.sort(key=lambda m: m["date"], reverse=True)
    cutoff = matches[0]["date"] - timedelta(weeks=args.weeks)
    window = [m for m in matches if m["date"] >= cutoff][: args.max_matches]
    if not window:
        print("[swarm_backtest] window empty", file=sys.stderr)
        return 2

    metrics = _evaluate(window)
    swarm = metrics["swarm"]
    predictor_log_losses = {
        pid: m["log_loss"] for pid, m in metrics["predictors"].items()
    }
    gate_passed, gate_msg = _evaluate_gate(
        swarm["log_loss"],
        predictor_log_losses,
        n_matches=swarm["n_matches"],
        floor_pct=cfg.backtest_swarm_floor_pct,
        min_n=cfg.backtest_min_n,
    )

    report: dict[str, Any] = {
        **metrics,
        "weeks": args.weeks,
        "floor_pct": cfg.backtest_swarm_floor_pct,
        "min_n": cfg.backtest_min_n,
        "window_start": window[-1]["date"].isoformat(),
        "window_end": window[0]["date"].isoformat(),
        "gate_passed": gate_passed,
        "gate_message": gate_msg,
    }

    json_path, md_path = _write_reports(report, args.out_dir)
    print(f"[swarm_backtest] wrote {json_path}")
    print(f"[swarm_backtest] wrote {md_path}")
    print(
        f"[swarm_backtest] swarm: acc={swarm['accuracy']:.4f} "
        f"log_loss={swarm['log_loss']:.4f} brier={swarm['brier']:.4f} "
        f"ece={swarm['ece']:.4f}"
    )
    print(f"[swarm_backtest] {gate_msg}")

    return 0 if gate_passed else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
