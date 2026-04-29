"""Pre-Phase-6 audit P1 regression: time-based train/test split.

`train_model` was random-splitting AFTER rolling-window feature
extraction, which causes temporal leakage on per-team rolling
stats (test match's features are computed from priors that end up
in the train set; train matches later in the season carry rolling
stats encoding the test match's outcome).

These tests do not retrain the GBDT — they only assert the
splitting contract by spying on the trainer's split logic via the
public `train_model` entry point with a synthetic match list.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest


class _FakeXGB:
    """Module-level so pickle.dump can serialise the trained model."""

    feature_importances_: list[float] = []

    def __init__(self, **kw) -> None:
        self._kw = kw

    def fit(self, X, y, **kw):
        # Spy hooks set externally before/after the fit call.
        if hasattr(_FakeXGB, "_capture_train"):
            _FakeXGB._capture_train(X, y)
        return self

    def predict(self, X):
        if hasattr(_FakeXGB, "_capture_test"):
            _FakeXGB._capture_test(X)
        return [0] * len(X)

    def predict_proba(self, X):
        return [[1.0, 0.0, 0.0]] * len(X)


def _synthetic_matches(n: int = 600) -> list[dict]:
    """Build a chronologically-shuffled match list spanning ~3 seasons.

    Two teams each play home + away alternating; we repeat enough
    times to satisfy `min_history=5`. Dates are 1 day apart.
    """
    teams = ["GS", "FB", "BJK", "TS", "GO", "AK"]
    base = date(2024, 1, 1)
    matches: list[dict] = []
    for i in range(n):
        h = teams[i % len(teams)]
        a = teams[(i + 1) % len(teams)]
        matches.append({
            "date": (base + timedelta(days=i)).isoformat(),
            "home": h,
            "away": a,
            "ft_home": (i * 7) % 4,
            "ft_away": (i * 11) % 4,
        })
    # Intentionally shuffle to prove the trainer sorts internally.
    matches = matches[::3] + matches[1::3] + matches[2::3]
    return matches


def test_trainer_sorts_matches_chronologically_before_split(tmp_path, monkeypatch) -> None:
    """The trainer must impose a chronological order on `raw_matches`
    before extracting features. Without this, even our sequential
    tail slice would be meaningless.
    """
    import model.trainer as trainer_mod
    from model.real_features import _parse_date

    captured: dict = {}

    def fake_extract(*, min_history: int = 5, matches=None):
        # Snapshot whatever order trainer hands us.
        captured["matches"] = list(matches or [])
        idx = list(range(30))
        X = pd.DataFrame({col: [0.0] * len(idx) for col in trainer_mod.FEATURE_COLUMNS})
        y = pd.Series([i % 3 for i in idx], name="result_class")
        return X, y

    monkeypatch.setattr(
        "model.real_features.extract_real_dataset", fake_extract
    )
    monkeypatch.setattr(trainer_mod.cfg, "training_min_matches", 5)
    monkeypatch.setattr(trainer_mod.cfg, "training_test_split", 0.2)
    monkeypatch.setattr(trainer_mod.cfg, "training_noise_pct", 0.0)
    _FakeXGB.feature_importances_ = [0.0] * len(trainer_mod.FEATURE_COLUMNS)
    monkeypatch.setattr(trainer_mod.xgb, "XGBClassifier", _FakeXGB)
    monkeypatch.setattr(trainer_mod.pickle, "dump", lambda *a, **k: None)

    save_path = tmp_path / "model.pkl"
    save_path.write_bytes(b"")  # so getsize is well-defined
    trainer_mod.train_model(save_path=str(save_path), matches=_synthetic_matches(60))

    delivered = captured["matches"]
    assert delivered, "trainer never invoked extract_real_dataset"
    parsed_dates = [_parse_date(m["date"]) for m in delivered]
    assert parsed_dates == sorted(parsed_dates), (
        "trainer must sort raw_matches by date before feature extraction"
    )


def test_trainer_uses_sequential_tail_split(tmp_path, monkeypatch) -> None:
    """Captured (X_train, X_test) must satisfy `len(train) == n - n_test`
    and the test rows must be contiguous tail rows of the full X.
    """
    import model.trainer as trainer_mod

    seen: dict = {}

    def fake_extract(*, min_history: int = 5, matches=None):
        n = 50
        X = pd.DataFrame(
            {col: list(range(n)) for col in trainer_mod.FEATURE_COLUMNS}
        )
        y = pd.Series([i % 3 for i in range(n)], name="result_class")
        return X, y

    _FakeXGB._capture_train = staticmethod(
        lambda X, y: seen.update({"X_train": X.copy()})
    )
    _FakeXGB._capture_test = staticmethod(
        lambda X: seen.update({"X_test": X.copy()})
    )
    _FakeXGB.feature_importances_ = [0.0] * len(trainer_mod.FEATURE_COLUMNS)

    monkeypatch.setattr(
        "model.real_features.extract_real_dataset", fake_extract
    )
    monkeypatch.setattr(trainer_mod.xgb, "XGBClassifier", _FakeXGB)
    monkeypatch.setattr(trainer_mod.cfg, "training_min_matches", 5)
    monkeypatch.setattr(trainer_mod.cfg, "training_test_split", 0.2)
    monkeypatch.setattr(trainer_mod.cfg, "training_noise_pct", 0.0)
    monkeypatch.setattr(trainer_mod.pickle, "dump", lambda *a, **k: None)

    save_path = tmp_path / "m.pkl"
    save_path.write_bytes(b"")
    try:
        trainer_mod.train_model(
            save_path=str(save_path),
            matches=_synthetic_matches(40),
        )
    finally:
        for attr in ("_capture_train", "_capture_test"):
            if hasattr(_FakeXGB, attr):
                delattr(_FakeXGB, attr)

    n_train = len(seen["X_train"])
    n_test = len(seen["X_test"])
    assert n_train + n_test == 50
    assert n_test == 10  # 0.2 * 50
    first_col = trainer_mod.FEATURE_COLUMNS[0]
    assert list(seen["X_train"][first_col])[-1] == 39
    assert list(seen["X_test"][first_col])[0] == 40


def test_trainer_rejects_test_split_outside_unit_interval(tmp_path, monkeypatch) -> None:
    import model.trainer as trainer_mod

    def fake_extract(*, min_history: int = 5, matches=None):
        X = pd.DataFrame({col: [0.0] * 20 for col in trainer_mod.FEATURE_COLUMNS})
        y = pd.Series([i % 3 for i in range(20)])
        return X, y

    monkeypatch.setattr(
        "model.real_features.extract_real_dataset", fake_extract
    )
    monkeypatch.setattr(trainer_mod.cfg, "training_min_matches", 5)
    monkeypatch.setattr(trainer_mod.cfg, "training_test_split", 1.5)

    with pytest.raises(ValueError, match="training_test_split"):
        trainer_mod.train_model(
            save_path=str(tmp_path / "m.pkl"),
            matches=_synthetic_matches(30),
        )
