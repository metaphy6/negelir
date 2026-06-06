"""Phase 10 §10.25.5 — operator-driven intent model retraining helper."""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
import tempfile
from pathlib import Path
from typing import Iterable

import common.config as _cm
from swarm.agents.nlp.training.eligibility import (
    filter_shadow_rows_for_intent_training,
    write_training_manifest,
)


class IntentTrainError(RuntimeError):
    """Raised when the intent retrain command cannot build a candidate model."""


def _load_shadow_rows(shadow_path: Path) -> list[tuple[str, str]]:
    if not shadow_path.exists():
        raise IntentTrainError(
            f"Intent training shadow corpus not found: {shadow_path}"
        )

    shadow_payloads: list[dict[str, object]] = []
    with shadow_path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise IntentTrainError(
                    f"Invalid JSON on line {line_no} of {shadow_path}: {exc}"
                ) from exc
            if isinstance(payload, dict):
                shadow_payloads.append(payload)

    cfg = _current_cfg()
    eval_manifest_path = (
        Path(cfg.nlp_intent_train_eval_manifest_path)
        if cfg.nlp_intent_train_eval_manifest_path
        else None
    )
    selected_payloads, excluded_counts, eval_set_checksum = filter_shadow_rows_for_intent_training(
        shadow_payloads,
        eval_manifest_path=eval_manifest_path,
        max_rows_per_subject_bucket=cfg.nlp_intent_train_max_rows_per_subject_bucket,
    )
    train_run_id = _utc_iso().replace("-", "").replace(":", "").replace("Z", "")
    write_training_manifest(
        train_run_id=train_run_id,
        shadow_path=shadow_path,
        selected_count=len(selected_payloads),
        excluded_counts=excluded_counts,
        eval_set_checksum=eval_set_checksum,
    )

    rows: list[tuple[str, str]] = []
    for payload in selected_payloads:
        text = payload.get("text") or payload.get("input_text") or payload.get("sentence")
        intent = payload.get("intent") or payload.get("label") or payload.get("intent_label")
        if not isinstance(text, str) or not isinstance(intent, str):
            continue
        text = text.strip().replace("\n", " ")
        intent = intent.strip()
        if not text or not intent:
            continue
        rows.append((text, intent))

    if not rows:
        raise IntentTrainError(
            f"Shadow training corpus contains no valid rows: {shadow_path}"
        )
    return rows


def _write_fasttext_training_file(rows: Iterable[tuple[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for text, intent in rows:
            label = intent if intent.startswith("__label__") else f"__label__{intent}"
            fh.write(f"{label} {text}\n")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _platt_sigmoid(raw_prob: float, A: float, B: float) -> float:
    """Apply the Platt sigmoid used for intent recalibration."""
    val = A * raw_prob + B
    if val < -500.0:
        return 0.0
    return 1.0 / (1.0 + math.exp(-val))


def _fit_platt_parameters(xs: list[float], ys: list[int]) -> tuple[float, float]:
    if not xs:
        return 1.0, 0.0

    positive = sum(ys)
    negative = len(ys) - positive
    if positive == 0 or negative == 0:
        return 1.0, 0.0

    A = 0.0
    B = math.log((positive + 1) / (negative + 1))
    for _ in range(20):
        gA = 0.0
        gB = 0.0
        HAA = 0.0
        HAB = 0.0
        HBB = 0.0
        for x, y in zip(xs, ys):
            val = A * x + B
            p = 1.0 / (1.0 + math.exp(-val))
            d = p - y
            gA += d * x
            gB += d
            w = p * (1.0 - p)
            HAA += w * x * x
            HAB += w * x
            HBB += w
        det = HAA * HBB - HAB * HAB
        if det <= 0.0:
            break
        dA = (gA * HBB - gB * HAB) / det
        dB = (gB * HAA - gA * HAB) / det
        A -= dA
        B -= dB
        if abs(dA) < 1e-6 and abs(dB) < 1e-6:
            break
    return float(A), float(B)


def _candidate_calibration_path(candidate_path: Path) -> Path:
    name = candidate_path.name
    if name.endswith(".candidate"):
        return candidate_path.with_name(name + ".calibration.json")
    return candidate_path.with_name(name + ".candidate.calibration.json")


def _write_candidate_calibration(model: object, rows: list[tuple[str, str]], candidate_path: Path) -> None:
    cfg = _current_cfg()
    calibration_path = _candidate_calibration_path(candidate_path)
    calibration_path.parent.mkdir(parents=True, exist_ok=True)

    intents = sorted({intent for _, intent in rows})
    predictions: list[tuple[str, str, float]] = []
    for text, actual_intent in rows:
        labels, probs = model.predict(text, k=1)
        predicted_intent = labels[0].replace("__label__", "")
        probability = float(probs[0])
        predictions.append((actual_intent, predicted_intent, probability))

    calibrations: dict[str, dict[str, float]] = {}
    for intent in intents:
        xs: list[float] = []
        ys: list[int] = []
        for actual_intent, predicted_intent, probability in predictions:
            xs.append(probability if predicted_intent == intent else 0.0)
            ys.append(1 if actual_intent == intent else 0)
        A, B = _fit_platt_parameters(xs, ys)
        calibrations[intent] = {"A": A, "B": B}

    cfg = _current_cfg()
    data = {
        "schema_version": 1,
        "calibration_version": str(cfg.nlp_intent_model_version or "0.0.0").strip() or "0.0.0",
        "generated_at_utc": _utc_iso(),
        "method": "platt",
        "intents": calibrations,
    }
    calibration_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _utc_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _current_cfg():
    return _cm.cfg


def default_shadow_path() -> Path:
    cfg = _current_cfg()
    return Path(cfg.nlp_intent_train_shadow_path)


def default_candidate_path() -> Path:
    cfg = _current_cfg()
    base = Path(cfg.nlp_intent_model_path).name
    return Path(cfg.nlp_intent_model_path).with_name(f"{base}.candidate")


def train_intent_candidate(
    shadow_path: Path | None = None,
    candidate_path: Path | None = None,
    epoch: int = 5,
    lr: float = 0.5,
    word_ngrams: int = 2,
    min_count: int = 1,
    dim: int = 32,
) -> Path:
    default_path = default_shadow_path()
    shadow_path = Path(shadow_path or default_path)
    if shadow_path.resolve() != default_path.resolve():
        raise IntentTrainError(
            "Intent training may only use the configured shadow corpus path "
            "(cfg.nlp_intent_train_shadow_path); custom uploads are not allowed."
        )
    candidate_path = Path(candidate_path or default_candidate_path())

    rows = _load_shadow_rows(shadow_path)
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as temp_file:
        temp_path = Path(temp_file.name)
        _write_fasttext_training_file(rows, temp_path)

    try:
        try:
            import fasttext  # type: ignore[import]
        except ImportError as exc:
            raise IntentTrainError(
                "fasttext library is not installed. Install it via ai/requirements.txt."
            ) from exc

        model = fasttext.train_supervised(
            input=str(temp_path),
            epoch=epoch,
            lr=lr,
            wordNgrams=word_ngrams,
            minCount=min_count,
            dim=dim,
            thread=1,
        )
        model.save_model(str(candidate_path))
        _write_candidate_calibration(model, rows, candidate_path)
    except Exception as exc:
        raise IntentTrainError(
            f"Intent training failed: {exc}"
        ) from exc
    finally:
        temp_path.unlink(missing_ok=True)

    sha = _sha256_file(candidate_path)
    candidate_path.with_suffix(candidate_path.suffix + ".sha256").write_text(sha + "\n", encoding="utf-8")
    return candidate_path
