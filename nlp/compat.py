from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common.config import cfg


class CompatibilityMatrixError(ValueError):
    pass


def _parse_semver(version: str, field: str) -> tuple[int, ...]:
    if not isinstance(version, str) or not version:
        raise CompatibilityMatrixError(f"{field} must be a non-empty semver string")

    segments = version.split('.')
    if not 1 <= len(segments) <= 4:
        raise CompatibilityMatrixError(
            f"{field} must be a semver string like X.Y.Z, got {version!r}"
        )

    parsed: list[int] = []
    for segment in segments:
        if not segment.isdigit():
            raise CompatibilityMatrixError(
                f"{field} must contain only digits separated by '.', got {version!r}"
            )
        parsed.append(int(segment))
    return tuple(parsed)


def _parse_iso8601(timestamp: str, field: str) -> datetime:
    if not isinstance(timestamp, str) or not timestamp:
        raise CompatibilityMatrixError(f"{field} must be a non-empty ISO-8601 UTC string")
    try:
        parsed = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    except ValueError as exc:
        raise CompatibilityMatrixError(
            f"{field} must be ISO-8601 UTC, got {timestamp!r}"
        ) from exc
    if parsed.tzinfo is None:
        raise CompatibilityMatrixError(
            f"{field} must include timezone information, got {timestamp!r}"
        )
    return parsed.astimezone(timezone.utc)


def _compare_semver(a: str, b: str) -> int:
    a_parsed = _parse_semver(a, 'semver')
    b_parsed = _parse_semver(b, 'semver')
    return (a_parsed > b_parsed) - (a_parsed < b_parsed)


def _hash_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        raise CompatibilityMatrixError(f"path not found for hash validation: {path}")
    digest = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(8192), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> Any:
    if not path.exists() or not path.is_file():
        raise CompatibilityMatrixError(f"compatibility matrix not found: {path}")
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise CompatibilityMatrixError(
            f"compatibility matrix JSON parse failed: {path}: {exc}"
        ) from exc


def _validate_matrix_shape(matrix: Any) -> list[dict[str, Any]]:
    if not isinstance(matrix, dict):
        raise CompatibilityMatrixError("compatibility matrix must be a JSON object")
    rows = matrix.get('rows')
    if not isinstance(rows, list):
        raise CompatibilityMatrixError("compatibility matrix must contain a top-level 'rows' array")

    seen_versions: set[str] = set()
    validated_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise CompatibilityMatrixError("compatibility matrix rows must be objects")

        pipeline_version = row.get('pipeline_version')
        if not isinstance(pipeline_version, str) or not pipeline_version:
            raise CompatibilityMatrixError("each compatibility row must include pipeline_version")
        if pipeline_version in seen_versions:
            raise CompatibilityMatrixError(
                f"duplicate pipeline_version in compatibility matrix: {pipeline_version}"
            )
        seen_versions.add(pipeline_version)

        for field in (
            'template_git_sha',
            'lexicon_set_sha',
            'intent_model_sha',
            'crf_model_sha',
            'humanizer_model_sha',
            'calibration_version_min',
            'calibration_version_max',
            'introduced_at_utc',
        ):
            if field not in row or not isinstance(row[field], str):
                raise CompatibilityMatrixError(
                    f"compatibility row missing or invalid field: {field}"
                )

        _parse_semver(row['calibration_version_min'], 'calibration_version_min')
        _parse_semver(row['calibration_version_max'], 'calibration_version_max')
        if _compare_semver(row['calibration_version_min'], row['calibration_version_max']) > 0:
            raise CompatibilityMatrixError(
                'compatibility row calibration_version_min must be <= calibration_version_max'
            )
        _parse_iso8601(row['introduced_at_utc'], 'introduced_at_utc')
        retired_at_utc = row.get('retired_at_utc')
        if retired_at_utc is not None:
            if not isinstance(retired_at_utc, str):
                raise CompatibilityMatrixError('retired_at_utc must be a string')
            _parse_iso8601(retired_at_utc, 'retired_at_utc')

        validated_rows.append(row)
    return validated_rows


def _normalize_path(path: str | Path) -> Path:
    return Path(path).resolve()


def load_compatibility_matrix(path: str | Path | None = None) -> dict[str, Any]:
    resolved = _normalize_path(path or cfg.nlp_compatibility_matrix_path)
    matrix = _load_json(resolved)
    validated_rows = _validate_matrix_shape(matrix)
    return {'rows': validated_rows, 'path': str(resolved)}


def _current_row(matrix: dict[str, Any], pipeline_version: str) -> dict[str, Any] | None:
    for row in matrix['rows']:
        if row['pipeline_version'] == pipeline_version:
            return row
    return None


def _lexicon_snapshot_sha() -> str:
    lexicon_dir = Path(getattr(cfg, 'nlp_lexicon_dir', 'ai/nlp/lexicon'))
    if getattr(cfg, 'nlp_canary_pod', False):
        lexicon_dir = lexicon_dir.with_name(lexicon_dir.name + '.canary')
    if not lexicon_dir.exists() or not lexicon_dir.is_dir():
        return ''

    digest = hashlib.sha256()
    for path in sorted(lexicon_dir.rglob('*.yaml')):
        if not path.is_file():
            continue
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _load_humanizer_chart_sha() -> str | None:
    chart_path = Path(__file__).resolve().parents[2] / 'xops' / 'versioning' / 'chart.json'
    if not chart_path.exists():
        return None
    try:
        chart = json.loads(chart_path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return None
    return (
        chart.get('compatibility', {})
        .get('data_files', {})
        .get('humanizer_llm', {})
        .get('sha256')
    )


def validate_compatibility_matrix(path: str | Path | None = None) -> None:
    matrix = load_compatibility_matrix(path)
    row = _current_row(matrix, cfg.nlp_pipeline_version)
    if row is None:
        raise CompatibilityMatrixError(
            f"NLP pipeline version {cfg.nlp_pipeline_version!r} is not found in compatibility matrix"
        )

    if row["template_git_sha"] and row["template_git_sha"] != cfg.nlp_template_git_sha:
        raise CompatibilityMatrixError(
            "template git SHA mismatch between compatibility matrix and current config"
        )

    if row["lexicon_set_sha"] and cfg.nlp_lexicon_source == "file":
        lexicon_sha = _lexicon_snapshot_sha()
        if lexicon_sha and lexicon_sha != row["lexicon_set_sha"]:
            raise CompatibilityMatrixError(
                "lexicon snapshot SHA mismatch between compatibility matrix and local lexicon files"
            )

    if row["intent_model_sha"] and cfg.nlp_intent_model_path:
        intent_path = Path(cfg.nlp_intent_model_path)
        if intent_path.exists() and _hash_file(intent_path) != row["intent_model_sha"]:
            raise CompatibilityMatrixError(
                "intent model SHA mismatch between compatibility matrix and deployed model"
            )

    if row["crf_model_sha"] and cfg.nlp_entity_crf_model_path:
        crf_path = Path(cfg.nlp_entity_crf_model_path)
        if crf_path.exists() and _hash_file(crf_path) != row["crf_model_sha"]:
            raise CompatibilityMatrixError(
                "entity CRF model SHA mismatch between compatibility matrix and deployed model"
            )

    humanizer_chart_sha = _load_humanizer_chart_sha()
    if humanizer_chart_sha is not None and row["humanizer_model_sha"]:
        if row["humanizer_model_sha"] != humanizer_chart_sha:
            raise CompatibilityMatrixError(
                "humanizer model SHA mismatch between compatibility matrix and chart.json"
            )

    if cfg.nlp_intent_calibration_path:
        calibration_path = Path(cfg.nlp_intent_calibration_path)
        if calibration_path.exists():
            calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
            calibration_version = calibration.get("version")
            if not isinstance(calibration_version, str):
                raise CompatibilityMatrixError(
                    "intent calibration file must contain a string 'version'"
                )
            if _compare_semver(calibration_version, row["calibration_version_min"]) < 0:
                raise CompatibilityMatrixError(
                    "intent calibration version is below compatibility matrix range"
                )
            if _compare_semver(calibration_version, row["calibration_version_max"]) > 0:
                raise CompatibilityMatrixError(
                    "intent calibration version is above compatibility matrix range"
                )

