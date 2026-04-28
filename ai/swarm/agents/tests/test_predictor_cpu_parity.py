"""Phase 5 / Phase 11 — `cpu_only` parity tests for the must-status
predictor roster.

ROADMAP §5.5 DoD ("Phase 11 parity"): every predictor has a `cpu_only`
parity test asserting CPU vs chosen-device prediction equality within
``ε = 1e-6`` log-loss over the seed corpus, and each bundle stays
within ``cfg.predictor_max_vram_mb`` on GPU.

The four must-status predictors (`elo`, `dixon_coles`, `xgb_form`,
`xgb_xg`) are pure Python / numpy / hand-tuned logistic today — no
GPU code path exists yet. The Phase 11 contract is therefore to
**guard** that:

  * The predictor is fully deterministic — same input vector twice
    yields bit-identical PMFs (no hidden RNG, no wall-clock features
    inside ``predict()`` other than the explicit ``produced_at``
    string passed to ``handle()``).
  * Forcing CPU-only execution (``CUDA_VISIBLE_DEVICES=""``) does not
    change the output by more than ``ε`` per-outcome — Phase 11 will
    swap CPU vs GPU here once a GPU code path lands.
  * The predictor's in-memory footprint stays well under the VRAM cap
    so multiple replicas fit on a single GPU.

The tests are marked ``cpu_only`` so a future Phase 11 device-aware
runner can opt in/out, but they run by default in CI to catch
regressions early.
"""
from __future__ import annotations

import importlib
import os
from typing import Any

import pytest

from common.config import cfg
from swarm.agents.payloads import PredictRequest
from swarm.agents.predictors import (
    DixonColesPredictor,
    EloPredictor,
    PredictorContext,
    XgbFormPredictor,
    XgbXgPredictor,
)


# Per-outcome equality tolerance. Tighter than the §5.5 log-loss ε
# because we compare raw PMF entries, not aggregated log-loss.
_PARITY_EPS = 1e-9
# Markets the must-quartet all support.
_MARKETS = ("1x2", "ah", "ou_2_5", "btts")


def _features() -> dict[str, Any]:
    """Realistic feature dict that exercises every predictor's branches."""
    return {
        "home_advantage": 0.55,
        "home_elo": 1620.0,
        "away_elo": 1505.0,
        "home_xg": 1.62,
        "away_xg": 1.04,
        "dixon_coles_rho": -0.10,
        "home_form_5": 2.2,
        "away_form_5": 1.6,
        "home_gd_5": 4.0,
        "away_gd_5": -2.0,
        "home_xg_per_match": 1.7,
        "away_xg_per_match": 1.05,
        "home_shot_quality": 0.12,
        "away_shot_quality": 0.09,
    }


def _ctx(market: str) -> PredictorContext:
    return PredictorContext(
        request=PredictRequest(
            request_id=f"parity-{market}",
            match_id="TR1:Galatasaray-Fenerbahce",
            market=market,
            league_id="TR1",
            features=_features(),
        ),
        features=_features(),
    )


def _all_predictors():
    return [
        EloPredictor(),
        DixonColesPredictor(),
        XgbFormPredictor(),
        XgbXgPredictor(),
    ]


@pytest.mark.cpu_only
@pytest.mark.parametrize(
    "predictor",
    _all_predictors(),
    ids=lambda p: p.predictor_id,
)
@pytest.mark.parametrize("market", _MARKETS)
def test_predictor_is_deterministic(predictor, market: str) -> None:
    """Same context twice → bit-identical PMFs.

    Catches accidental introduction of RNG or wall-clock dependence
    inside ``predict()``. This is the precondition for the Phase 11
    CPU-vs-device parity test (otherwise nothing would ever match).
    """
    pmf_a, conf_a = predictor.predict(_ctx(market))
    pmf_b, conf_b = predictor.predict(_ctx(market))
    assert conf_a == conf_b, (
        f"{predictor.predictor_id} confidence drifts on replay: "
        f"{conf_a} vs {conf_b}"
    )
    outcomes_a = pmf_a["market_outcomes"]
    outcomes_b = pmf_b["market_outcomes"]
    assert set(outcomes_a) == set(outcomes_b)
    for k in outcomes_a:
        assert abs(outcomes_a[k] - outcomes_b[k]) <= _PARITY_EPS, (
            f"{predictor.predictor_id} non-deterministic on outcome {k}: "
            f"{outcomes_a[k]} vs {outcomes_b[k]}"
        )
    grid_a = pmf_a.get("score_grid")
    grid_b = pmf_b.get("score_grid")
    assert (grid_a is None) == (grid_b is None)
    if grid_a is not None:
        rows = len(grid_a)
        cols = len(grid_a[0])
        for i in range(rows):
            for j in range(cols):
                assert abs(grid_a[i][j] - grid_b[i][j]) <= _PARITY_EPS


@pytest.mark.cpu_only
@pytest.mark.parametrize(
    "predictor",
    _all_predictors(),
    ids=lambda p: p.predictor_id,
)
def test_predictor_forced_cpu_matches_default(
    monkeypatch: pytest.MonkeyPatch, predictor
) -> None:
    """Forcing ``CUDA_VISIBLE_DEVICES=""`` and reloading must not
    change the output (the must-quartet has no GPU code path yet —
    this guard ensures a future GPU branch ships with a parity proof).
    """
    baseline_pmf, _ = predictor.predict(_ctx("1x2"))

    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
    # Re-instantiate from a fresh module import so any module-level
    # device probe re-runs in the CPU-only environment.
    module = importlib.import_module(type(predictor).__module__)
    importlib.reload(module)
    cls = getattr(module, type(predictor).__name__)
    cpu_predictor = cls()
    cpu_pmf, _ = cpu_predictor.predict(_ctx("1x2"))

    for outcome in baseline_pmf["market_outcomes"]:
        delta = abs(
            baseline_pmf["market_outcomes"][outcome]
            - cpu_pmf["market_outcomes"][outcome]
        )
        assert delta <= _PARITY_EPS, (
            f"{predictor.predictor_id}: CPU-only branch differs from "
            f"default on outcome {outcome} by {delta}"
        )


@pytest.mark.cpu_only
@pytest.mark.parametrize(
    "predictor",
    _all_predictors(),
    ids=lambda p: p.predictor_id,
)
def test_predictor_bundle_under_vram_cap(predictor) -> None:
    """In-memory predictor instance stays well under
    `cfg.predictor_max_vram_mb`. The must-quartet has no resident GPU
    bundle (booster slots are ``None`` until §5.4 trainer wires them);
    this test guards that no future change accidentally pulls a
    multi-MB resource into the constructor.

    Uses ``sys.getsizeof`` on the instance dict — coarse, but enough
    to catch a 100 MB regression.
    """
    import sys

    cap_bytes = cfg.predictor_max_vram_mb * 1024 * 1024
    instance_bytes = sys.getsizeof(predictor) + sum(
        sys.getsizeof(v) for v in vars(predictor).values()
    )
    assert instance_bytes < cap_bytes, (
        f"{predictor.predictor_id} in-memory size {instance_bytes} bytes "
        f"exceeds predictor_max_vram_mb cap {cap_bytes} bytes"
    )
