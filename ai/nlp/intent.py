"""Phase 10 §10.4 — fastText intent classifier with Platt calibration.

Provides :class:`IntentClassifier` which:

* Verifies the model file SHA256 against ``cfg.nlp_intent_model_sha256``
  (when set; empty string disables verification for dev/pre-train).
* Enforces the ``cfg.nlp_intent_model_max_size_mb`` cap (§10.4 DoD: ≤ 20 MB).
* Lazily imports ``fasttext`` so this module is importable even when the
  library is not installed; raises :exc:`IntentModelUnavailable` on first use.
* Exposes :meth:`IntentClassifier.predict_intent` returning
  ``(intent_label, probability)`` for the top-1 intent (raw fastText prob).
* Exposes :meth:`IntentClassifier.predict_intent_distribution` returning
  top-k :class:`IntentScore` entries with both raw and Platt-calibrated
  probabilities (§10.4 Calibration).

The model is **CPU-only**; fastText C++ inference has no GPU path.

Latency targets (§10.4 CI gate, enforced by ``make nlp.intent-bench`` once
a model file exists):

* ``LATENCY_BUDGET_RTX_MS``  — <1 ms per query on RTX-4080m.
* ``LATENCY_BUDGET_AVX2_MS`` — <5 ms per query on AVX-2 desktop CPU.

SHA-pin workflow::

    1. Place the trained model at cfg.nlp_intent_model_path.
    2. Run make nlp.intent-pin — writes SHA256 into chart.json
       compatibility.data_files.intent_model.sha256.
    3. Set NEGELIR_NLP_INTENT_MODEL_SHA256=<sha> in the deployment env.

Calibration workflow::

    1. After training, run the calibration script on the held-out split.
    2. Script writes intent.tr.calibration.json next to intent.tr.bin.
    3. IntentClassifier.load() picks it up automatically.
    4. predict_intent_distribution() returns calibrated_prob via Platt sigmoid.
"""
from __future__ import annotations

import collections
import datetime as _dt
import hashlib
import json
import math
from pathlib import Path
from typing import Deque, Dict, FrozenSet, List, NamedTuple, Optional, Tuple, Union

from nlp.phase10_30 import apply_wh_prior_to_scores

# ---------------------------------------------------------------------------
# Closed intent enum (§10.4)
# ---------------------------------------------------------------------------

#: Absolute path to the single-source enum registry (§10.4).
_INTENT_ENUM_PATH: Path = (
    Path(__file__).parent.parent
    / "swarm" / "sdk" / "schemas" / "_intent_enum.json"
)

#: Expected schema_version in _intent_enum.json; mismatch refuses load.
_INTENT_ENUM_SCHEMA_VERSION: int = 4


def _load_intent_labels() -> FrozenSet[str]:
    """Load and return the closed intent-label set from _intent_enum.json.

    Raises:
        FileNotFoundError: if _intent_enum.json is missing.
        ValueError: if schema_version != 1 or ``enum`` key is absent.
    """
    raw = json.loads(_INTENT_ENUM_PATH.read_text(encoding="utf-8"))
    version = raw.get("schema_version")
    if version != _INTENT_ENUM_SCHEMA_VERSION:
        raise ValueError(
            f"_intent_enum.json schema_version mismatch: "
            f"expected={_INTENT_ENUM_SCHEMA_VERSION}, got={version!r}"
        )
    values = raw.get("enum")
    if not values or not isinstance(values, list):
        raise ValueError(
            "_intent_enum.json missing or empty 'enum' array."
        )
    return frozenset(values)


def _utc_iso() -> str:
    return _dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


#: Closed set of all valid intent labels (§10.4).  fastText ``__label__``
#: prefixes are stripped by :meth:`IntentClassifier.predict_intent` before
#: comparison.  ``data.player_card_risk`` is Phase 21 enrichment-bound and
#: guarded by ``cfg.nlp_enable_player_card_risk`` at runtime.
INTENT_LABELS: FrozenSet[str] = _load_intent_labels()


# ---------------------------------------------------------------------------
# Public exceptions
# ---------------------------------------------------------------------------


class IntentModelError(RuntimeError):
    """Base for all intent-classifier errors."""


class IntentModelNotFoundError(IntentModelError):
    """Model file does not exist at the configured path."""


class IntentModelSHAMismatch(IntentModelError):
    """SHA256 of the model file does not match the pinned value."""


class IntentModelTooLarge(IntentModelError):
    """Model file exceeds the allowed size cap."""


class IntentModelUnavailable(IntentModelError):
    """fasttext library is not installed."""


class IntentCalibrationLoadError(IntentModelError):
    """Calibration file exists but is malformed or schema_version mismatch."""


# ---------------------------------------------------------------------------
# Calibration types (§10.4 Calibration)
# ---------------------------------------------------------------------------

#: Per-intent Platt-scaling parameters (A, B).
#: calibrated_prob = sigmoid(A * raw_prob + B) = 1 / (1 + exp(-(A*p + B)))
_PlattParams = Tuple[float, float]

#: calibration_params[intent_label] = (A, B)
_CalibrationParams = Dict[str, _PlattParams]

#: Expected schema_version in the calibration JSON.
_CALIBRATION_SCHEMA_VERSION: int = 1


class IntentScore(NamedTuple):
    """Top-k intent classification result with calibrated probability.

    Attributes:
        label:              Intent label (stripped of fastText ``__label__`` prefix).
        raw_prob:           Raw fastText softmax probability.
        calibrated_prob:    Platt-calibrated probability; equals ``raw_prob``
                            when calibration file is absent.
        raw_logit:          Estimated logit before WH prior adjustment.
        raw_logit_after_wh_prior: Estimated logit after WH prior adjustment.
    """

    label: str
    raw_prob: float
    calibrated_prob: float
    raw_logit: float | None = None
    raw_logit_after_wh_prior: float | None = None

    def __iter__(self):
        return iter((self.label, self.raw_prob, self.calibrated_prob))


class IntentAbstention(NamedTuple):
    """Returned by :meth:`IntentClassifier.classify` when the top-1 calibrated
    probability is below ``cfg.nlp_min_intent_conf`` (§10.4 Abstention threshold).

    The caller must prompt "Did you mean?" using *suggestions* — never guess
    silently.

    Attributes:
        suggestions: Top-k :class:`IntentScore` entries (descending raw_prob).
        top_conf:    Calibrated probability of the top-1 intent; always below
                     the configured minimum confidence floor.
    """

    suggestions: List[IntentScore]
    top_conf: float


# ---------------------------------------------------------------------------
# Constants (phase 10 §10.4 DoD + latency gate documentation)
# ---------------------------------------------------------------------------

#: Phase 10 §10.4 DoD: model must be ≤ 20 MB on disk.
MAX_MODEL_SIZE_MB: int = 20

#: CI latency budget: <1 ms per query on RTX-4080m (§10.4).
LATENCY_BUDGET_RTX_MS: float = 1.0

#: CI latency budget: <5 ms per query on AVX-2 desktop CPU (§10.4).
LATENCY_BUDGET_AVX2_MS: float = 5.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    """Return hex SHA256 of the file at *path* (streaming, 64 KB chunks)."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _model_size_mb(path: Path) -> float:
    return path.stat().st_size / (1024.0 * 1024.0)


def _load_calibration(
    path: Path,
) -> Tuple[_CalibrationParams, str]:
    """Load per-intent Platt calibration parameters from *path*.

    Returns:
        (params, calibration_version) where params maps intent label →
        (A, B) and calibration_version is the semver string from the file.

    Raises:
        IntentCalibrationLoadError: if the file is malformed, missing a
            required key, or has an unexpected schema_version.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise IntentCalibrationLoadError(
            f"intent calibration file is not valid JSON: {path} ({exc})"
        ) from exc

    version = raw.get("schema_version")
    if version != _CALIBRATION_SCHEMA_VERSION:
        raise IntentCalibrationLoadError(
            f"intent calibration schema_version mismatch: "
            f"expected={_CALIBRATION_SCHEMA_VERSION}, got={version!r} "
            f"(path={path})"
        )

    intents = raw.get("intents")
    if not isinstance(intents, dict):
        raise IntentCalibrationLoadError(
            f"intent calibration missing 'intents' dict (path={path})"
        )

    params: _CalibrationParams = {}
    for label, entry in sorted(intents.items()):
        if not isinstance(entry, dict) or "A" not in entry or "B" not in entry:
            raise IntentCalibrationLoadError(
                f"intent calibration malformed entry for '{label}': "
                f"expected {{\"A\": float, \"B\": float}} (path={path})"
            )
        params[label] = (float(entry["A"]), float(entry["B"]))

    calibration_version = str(raw.get("calibration_version", ""))
    return params, calibration_version


# ---------------------------------------------------------------------------
# IntentDriftGuard (§10.4 Drift guard)
# ---------------------------------------------------------------------------


class IntentDriftGuard:
    """Rolling accuracy tracker for the §10.4 Drift guard.

    Maintains a fixed-size sliding window of correctness booleans.
    When the rolling accuracy (over *window* recent predictions) drops
    below *floor*, :attr:`is_degraded` flips to ``True``; the caller
    must then:

    1. Emit ``nlp.event.v1{kind=intent_classifier_degraded}``.
    2. Route new traffic to template-only fallback (no LLM polish).

    Usage::

        guard = IntentDriftGuard(window=cfg.nlp_intent_drift_window,
                                 floor=cfg.nlp_intent_accuracy_floor)
        flipped = guard.record(correct=True)
        if flipped and guard.is_degraded:
            emit_nlp_event(kind="intent_classifier_degraded")

    :attr:`is_degraded` is ``False`` until *window* samples have been
    collected (guard is agnostic before it has enough data).
    """

    def __init__(self, window: int, floor: float) -> None:
        if window < 1:
            raise ValueError(f"IntentDriftGuard window must be >= 1, got {window}")
        if not (0.0 < floor < 1.0):
            raise ValueError(
                f"IntentDriftGuard floor must be in (0, 1), got {floor}"
            )
        self._window: int = window
        self._floor: float = floor
        self._hits: Deque[bool] = collections.deque(maxlen=window)
        self.is_degraded: bool = False

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def record(self, correct: bool) -> bool:
        """Append one correctness sample and recompute degraded state.

        Returns:
            ``True`` when :attr:`is_degraded` *changed* (i.e., a
            transition just occurred — callers use this to gate the
            ``nlp.event.v1`` emit so it fires at most once per flip).
        """
        self._hits.append(correct)
        if len(self._hits) < self._window:
            # Not enough data yet — stay non-degraded.
            was = self.is_degraded
            self.is_degraded = False
            return was  # was True → now False is still a transition
        accuracy = sum(self._hits) / self._window
        was = self.is_degraded
        self.is_degraded = accuracy < self._floor
        return self.is_degraded != was

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    @property
    def rolling_accuracy(self) -> Optional[float]:
        """Current rolling accuracy; ``None`` when fewer than *window* samples."""
        if len(self._hits) < self._window:
            return None
        return sum(self._hits) / self._window

    @property
    def sample_count(self) -> int:
        """Number of samples recorded so far (≤ *window*)."""
        return len(self._hits)

    @property
    def window(self) -> int:
        """Configured window size."""
        return self._window

    @property
    def floor(self) -> float:
        """Configured accuracy floor."""
        return self._floor


# ---------------------------------------------------------------------------
# IntentClassifier
# ---------------------------------------------------------------------------


class IntentClassifier:
    """Wrapper around a fastText supervised model for Turkish intent classification.

    Usage::

        clf = IntentClassifier.load(cfg)
        label, prob = clf.predict_intent("Galatasaray maci ne zaman?")

    Raises:
        IntentModelNotFoundError  -- model file missing.
        IntentModelSHAMismatch    -- file does not match the pinned SHA256.
        IntentModelTooLarge       -- file exceeds nlp_intent_model_max_size_mb.
        IntentModelUnavailable    -- fasttext library is not installed.
    """

    def __init__(
        self,
        _model: object,
        model_path: Path,
        _calibration: Optional[_CalibrationParams] = None,
        _calibration_version: str = "",
        _drift_guard: Optional[IntentDriftGuard] = None,
        _model_version: str = "",
    ) -> None:
        self._model = _model
        self.model_path = model_path
        #: Per-intent Platt params; None when calibration file is absent.
        self._calibration: Optional[_CalibrationParams] = _calibration
        #: Semver from calibration_version field in the JSON.
        self.calibration_version: str = _calibration_version
        #: Model version string from cfg.nlp_intent_model_version (§10.4 Versioning).
        #: Stamped on every qa.intent.v1 envelope as ``intent_model_version``.
        #: Empty string when running pre-train / dev without a pinned version.
        self.model_version: str = _model_version
        #: Optional drift guard (§10.4 Drift guard).
        self._drift_guard: Optional[IntentDriftGuard] = _drift_guard

    # ------------------------------------------------------------------
    # Degraded state (§10.4 Drift guard)
    # ------------------------------------------------------------------

    @property
    def is_degraded(self) -> bool:
        """``True`` when the attached drift guard has flagged classifier degradation.

        When ``True`` callers must route to template-only fallback and emit
        ``nlp.event.v1{kind=intent_classifier_degraded}`` (§10.4 Drift guard).
        Always ``False`` when no drift guard is attached.
        """
        if self._drift_guard is None:
            return False
        return self._drift_guard.is_degraded

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
        """Resolve the deployed intent model path, including canary pods.

        When ``cfg.nlp_canary_pod`` is true, the canary pod loads the canary
        model file path by appending ".canary" to the configured model file
        name (§10.23.2).
        When ``canary=True``, returns the canary path regardless of pod role.
        """
        base_path = Path(getattr(cfg, "nlp_intent_model_path", "data/models/nlp/intent.tr.bin"))
        if canary or getattr(cfg, "nlp_canary_pod", False):
            return base_path.with_name(base_path.name + ".canary")
        return base_path

    @classmethod
    def load(cls, cfg: object, canary: bool = False) -> "IntentClassifier":
        """Load the intent classifier from the configured path.

        When ``canary=True``, loads the canary model path independently of
        the pod role. This supports §10.23.2 shadow-mode evaluation.
        """
        model_path = cls._resolve_model_path(cfg, canary=canary)
        if not model_path.exists():
            raise IntentModelNotFoundError(
                f"Intent model not found: {model_path}. "
                "Train the model and run `make nlp.intent-pin`."
            )

        # Size cap (§10.4 DoD: <= nlp_intent_model_max_size_mb)
        max_mb = int(getattr(cfg, "nlp_intent_model_max_size_mb", MAX_MODEL_SIZE_MB))
        actual_mb = _model_size_mb(model_path)
        if actual_mb > max_mb:
            raise IntentModelTooLarge(
                f"Intent model exceeds size cap: "
                f"{actual_mb:.2f} MB > {max_mb} MB "
                f"(path={model_path})"
            )

        # SHA256 verification (§10.21.1: sidecar file, config fallback)
        # Try sidecar file first (built by `make nlp.intent-pin`)
        sidecar_path = Path(str(model_path) + ".sha256")
        expected_sha = ""
        sha_source = ""
        
        if sidecar_path.exists():
            try:
                expected_sha = sidecar_path.read_text(encoding="utf-8").strip().split()[0]
                sha_source = f"sidecar:{sidecar_path.name}"
            except (OSError, UnicodeDecodeError, IndexError) as exc:
                # Sidecar exists but unreadable → critical (§10.21.1)
                raise IntentModelSHAMismatch(
                    f"Intent model SHA sidecar exists but is unreadable: "
                    f"{sidecar_path} ({exc}). "
                    "Re-run `make nlp.intent-pin`. "
                    "[nlp.alert.v1{kind=nlp_intent_model_sha_mismatch, severity=critical}]"
                ) from exc
        else:
            # Fall back to config
            expected_sha = str(getattr(cfg, "nlp_intent_model_sha256", "") or "").strip()
            if expected_sha:
                sha_source = "cfg.nlp_intent_model_sha256"
        
        if expected_sha:
            actual_sha = _sha256_file(model_path)
            if actual_sha != expected_sha:
                raise IntentModelSHAMismatch(
                    f"Intent model SHA256 mismatch: "
                    f"expected={expected_sha[:12]}... "
                    f"actual={actual_sha[:12]}... "
                    f"(source={sha_source}, path={model_path}). "
                    "Defends against file corruption and numpy ABI drift. "
                    "Re-run `make nlp.intent-pin` and update the deployment env. "
                    "[nlp.alert.v1{kind=nlp_intent_model_sha_mismatch, severity=critical}]"
                )

        # --- Calibration (§10.4 Calibration) — resolved before fasttext import ---
        # so that a malformed calibration file is caught early (like SHA mismatch).
        cal_path_str = str(
            getattr(cfg, "nlp_intent_calibration_path", "") or ""
        ).strip()
        if cal_path_str:
            cal_path = Path(cal_path_str)
        else:
            # Default: same directory as model, fixed name.
            cal_path = model_path.parent / "intent.tr.calibration.json"

        calibration: Optional[_CalibrationParams] = None
        cal_version: str = ""
        if cal_path.exists():
            # Raises IntentCalibrationLoadError if malformed.
            calibration, cal_version = _load_calibration(cal_path)

        # Version compatibility check — numpy first (§10.21.1: numpy + fastText version pin)
        # Check numpy before importing fasttext
        import numpy
        pinned_numpy = str(getattr(cfg, "nlp_numpy_pin", "") or "").strip()
        if pinned_numpy:
            actual_numpy = numpy.__version__
            if actual_numpy != pinned_numpy:
                raise IntentModelUnavailable(
                    f"NLP dependency version mismatch (§10.21.1): "
                    f"numpy: expected={pinned_numpy}, actual={actual_numpy}. "
                    "Refuse start on drift per CLAUDE.md 'no *-latest' doctrine. "
                    "Update xops/versioning/chart.json py_exact_versions and redeploy. "
                    "[nlp.alert.v1{kind=nlp_dependency_version_mismatch, severity=critical}]"
                )

        # Lazy fasttext import
        try:
            import fasttext  # type: ignore[import]
        except ImportError as exc:
            raise IntentModelUnavailable(
                "fasttext library is not installed. "
                "Install it inside the container (see ai/requirements.txt)."
            ) from exc

        # Version compatibility check — fasttext (§10.21.1)
        pinned_fasttext = str(getattr(cfg, "nlp_fasttext_pin", "") or "").strip()
        if pinned_fasttext:
            actual_fasttext = fasttext.__version__
            if actual_fasttext != pinned_fasttext:
                raise IntentModelUnavailable(
                    f"NLP dependency version mismatch (§10.21.1): "
                    f"fasttext: expected={pinned_fasttext}, actual={actual_fasttext}. "
                    "Refuse start on drift per CLAUDE.md 'no *-latest' doctrine. "
                    "Update xops/versioning/chart.json py_exact_versions and redeploy. "
                    "[nlp.alert.v1{kind=nlp_dependency_version_mismatch, severity=critical}]"
                )

        model_version = str(
            getattr(cfg, "nlp_intent_model_version", "") or ""
        ).strip()

        try:
            model = fasttext.load_model(str(model_path))
        except Exception as exc:
            raise IntentModelUnavailable(
                f"fasttext model load failed: {exc}"
            ) from exc
        return cls(model, model_path, calibration, cal_version, _model_version=model_version)

    @classmethod
    def load_shadow_pair(cls, cfg: object) -> tuple["IntentClassifier", "IntentClassifier"]:
        """Load both the baseline and canary intent models for shadow evaluation."""
        baseline = cls.load(cfg, canary=False)
        canary = cls.load(cfg, canary=True)
        return baseline, canary

    @staticmethod
    def _shadow_input_hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _shadow_should_sample(text: str, sample_rate: float) -> bool:
        if sample_rate <= 0.0:
            return False
        if sample_rate >= 1.0:
            return True
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:8], "big")
        return bucket < int(sample_rate * (1 << 64))

    @staticmethod
    def make_shadow_payload(
        text: str,
        baseline: "IntentClassifier",
        canary: "IntentClassifier",
        request_id: str | None = None,
    ) -> dict[str, object]:
        baseline_intent, baseline_conf = baseline.predict_intent(text)
        canary_intent, canary_conf = canary.predict_intent(text)
        return {
            "input_hash": IntentClassifier._shadow_input_hash(text),
            "request_id": request_id or None,
            "baseline_intent": baseline_intent,
            "baseline_conf": baseline_conf,
            "baseline_model_version": baseline.model_version,
            "canary_intent": canary_intent,
            "canary_conf": canary_conf,
            "canary_model_version": canary.model_version,
            "agreement": baseline_intent == canary_intent,
            "producer": "nlp.intent.v1",
            "emitted_at": _utc_iso(),
        }

    @staticmethod
    def shadow_payload_for_request(
        text: str,
        baseline: "IntentClassifier",
        canary: "IntentClassifier",
        cfg: object,
        request_id: str | None = None,
    ) -> dict[str, object] | None:
        if getattr(cfg, "nlp_intent_shadow_mode", "off") != "on":
            return None
        if not IntentClassifier._shadow_should_sample(text, float(getattr(cfg, "nlp_shadow_sample_rate", 0.01))):
            return None
        return IntentClassifier.make_shadow_payload(text, baseline, canary, request_id=request_id)

    @staticmethod
    def should_route_to_canary(account_id: str | int | None, cfg: object) -> bool:
        """Return True when the account should be routed to the canary model.

        Uses a stable SHA-256 sticky bucket over ``account_id`` and the
        configured rollout percentage / account bucket size (§10.23.2).
        """
        if not account_id:
            return False

        pct = int(getattr(cfg, "nlp_intent_model_canary_pct", 0))
        if pct <= 0:
            return False
        if pct >= 100:
            return True

        bucket_size = int(getattr(cfg, "nlp_canary_account_bucket_size", 1000))
        if bucket_size <= 0:
            return False

        threshold = (pct * bucket_size) // 100
        if threshold <= 0:
            return False

        account_bytes = str(account_id).encode("utf-8")
        bucket = int.from_bytes(hashlib.sha256(account_bytes).digest()[:8], "big") % bucket_size
        return bucket < threshold

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def predict_intent(self, text: str) -> Tuple[str, float]:
        """Return (label, probability) for the top-1 intent.

        The __label__ fastText prefix is stripped; the returned label matches
        the closed intent enum in _intent_enum.json (§10.4).
        """
        labels, probs = self._model.predict(text, k=1)
        label = labels[0].replace("__label__", "")
        return label, float(probs[0])

    # ------------------------------------------------------------------
    # Calibrated distribution (§10.4 Calibration)
    # ------------------------------------------------------------------

    @staticmethod
    def _platt_sigmoid(raw_prob: float, A: float, B: float) -> float:
        """Apply Platt sigmoid: 1 / (1 + exp(-(A * raw_prob + B))).

        Uses ``math.exp`` for precision; clamps to [0, 1].
        """
        val = A * raw_prob + B
        # Avoid overflow for very large negative values.
        if val < -500.0:
            return 0.0
        result = 1.0 / (1.0 + math.exp(-val))
        return max(0.0, min(1.0, result))

    def predict_intent_distribution(
        self, text: str, k: int = 3
    ) -> List[IntentScore]:
        """Return top-k intent scores with calibrated probabilities.

        Each :class:`IntentScore` carries:
        * ``label``          — intent label (``__label__`` prefix stripped).
        * ``raw_prob``       — raw fastText softmax probability.
        * ``calibrated_prob``— Platt-calibrated probability; equals
                               ``raw_prob`` when calibration is absent.

        The list is ordered by descending ``raw_prob`` (fastText order).
        This method is the data source for ``qa.intent.v1``'s
        ``predict.intent_distribution`` field (§10.4 Calibration).

        Args:
            text: Normalized Turkish query text.
            k:    Number of top intents to return (default 3).
        """
        labels, probs = self._model.predict(text, k=k)
        raw_scores: list[dict[str, float | str]] = []
        for raw_label, raw_prob_val in zip(labels, probs):
            label = raw_label.replace("__label__", "")
            raw_p = float(raw_prob_val)
            raw_scores.append({"label": label, "raw_prob": raw_p})

        biased_scores = apply_wh_prior_to_scores(text, raw_scores)
        scores: List[IntentScore] = []
        for entry in biased_scores:
            label = str(entry["label"])
            adjusted_raw = float(entry.get("adjusted_raw_prob", entry["raw_prob"]))
            raw_logit = float(entry.get("raw_logit")) if entry.get("raw_logit") is not None else None
            raw_logit_after_wh = float(entry.get("raw_logit_after_wh_prior")) if entry.get("raw_logit_after_wh_prior") is not None else None
            if self._calibration is not None and label in self._calibration:
                A, B = self._calibration[label]
                cal_p = self._platt_sigmoid(adjusted_raw, A, B)
            else:
                cal_p = adjusted_raw
            scores.append(
                IntentScore(
                    label=label,
                    raw_prob=float(entry["raw_prob"]),
                    calibrated_prob=cal_p,
                    raw_logit=raw_logit,
                    raw_logit_after_wh_prior=raw_logit_after_wh,
                )
            )
        return scores

    # ------------------------------------------------------------------
    # Abstention gate (§10.4 Abstention threshold)
    # ------------------------------------------------------------------

    def classify(
        self,
        text: str,
        min_conf: float,
        k: int = 3,
    ) -> Union[IntentScore, IntentAbstention]:
        """Return a definite :class:`IntentScore` or an :class:`IntentAbstention`.

        When the top-1 calibrated probability is ≥ *min_conf*, returns the
        top-1 :class:`IntentScore` directly.  When it is below the floor,
        returns :class:`IntentAbstention` carrying the top-*k* suggestions so
        the caller can emit a "Did you mean?" response.

        **Never guesses silently** (§10.4 Abstention threshold doctrine).

        Args:
            text:     Normalized Turkish query text.
            min_conf: Minimum calibrated confidence floor (e.g. ``cfg.nlp_min_intent_conf``).
            k:        Number of top-intent suggestions to carry in abstention
                      (default 3 matching the §10.4 spec).
        """
        scores = self.predict_intent_distribution(text, k=k)
        if not scores:
            # No predictions at all — treat as unconditional abstention.
            return IntentAbstention(suggestions=[], top_conf=0.0)
        top = scores[0]
        if top.calibrated_prob >= min_conf:
            return top
        return IntentAbstention(suggestions=scores, top_conf=top.calibrated_prob)

