"""Phase 10 §10.32.10 — Inline self-correction and stutter handling."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import yaml

from ai.common.text.turkish import lowercase_tr

_DEFAULT_INLINE_SELF_CORRECTION_MARKERS_PATH: Path = (
    Path(__file__).parent / "lang_tr" / "correction" / "inline_correction_markers.tr.yaml"
)
_SCHEMA_VERSION = 1


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ValueError(f"{path.name}: expected a YAML mapping at top level")
    version = int(raw.get("_meta", {}).get("schema_version", 0))
    if version != _SCHEMA_VERSION:
        raise ValueError(
            f"{path.name}: expected schema_version={_SCHEMA_VERSION}, got {version}"
        )
    return raw


def load_inline_self_correction_markers(path: Path | None = None) -> dict[str, tuple[tuple[str, ...], ...]]:
    actual_path = path or _DEFAULT_INLINE_SELF_CORRECTION_MARKERS_PATH
    raw = _load_yaml(actual_path)

    result: dict[str, tuple[tuple[str, ...], ...]] = {}
    for kind, entries in raw.items():
        if kind == "_meta":
            continue
        if not isinstance(entries, list):
            continue
        phrases: list[tuple[str, ...]] = []
        for entry in entries:
            if not isinstance(entry, str):
                continue
            text = lowercase_tr(entry.strip())
            if not text:
                continue
            phrases.append(tuple(text.split()))
        if phrases:
            result[kind] = tuple(phrases)
    return result


def _is_stutter_repeat(left: str, right: str) -> bool:
    left_norm = lowercase_tr(left.strip())
    right_norm = lowercase_tr(right.strip())
    if len(left_norm) < 3 or len(right_norm) <= len(left_norm):
        return False
    if not right_norm.startswith(left_norm):
        return False
    return True


def _match_phrase(tokens: list[str], index: int, phrase: tuple[str, ...]) -> bool:
    if index + len(phrase) > len(tokens):
        return False
    return all(lowercase_tr(tokens[index + offset]) == part for offset, part in enumerate(phrase))


def apply_inline_self_correction(
    tokens: list[str],
    markers: dict[str, tuple[tuple[str, ...], ...]],
    event_sink: Callable[[dict[str, object]], None],
) -> list[str]:
    if not markers or not tokens:
        return tokens

    verbal_markers = markers.get("verbal_self_correction", ())
    output: list[str] = []
    idx = 0
    while idx < len(tokens):
        if idx + 1 < len(tokens) and _is_stutter_repeat(tokens[idx], tokens[idx + 1]):
            event_sink({
                "kind": "inline_self_correction_applied",
                "strategy": "stutter_repeat",
                "original": tokens[idx],
                "replacement": tokens[idx + 1],
            })
            idx += 1
            continue

        matched_marker = False
        for marker_phrase in verbal_markers:
            if _match_phrase(tokens, idx, marker_phrase):
                right_index = idx + len(marker_phrase)
                if right_index < len(tokens) and output:
                    previous_token = output[-1]
                    next_token = tokens[right_index]
                    if _is_stutter_repeat(previous_token, next_token):
                        output.pop()
                        event_sink({
                            "kind": "inline_self_correction_applied",
                            "strategy": "verbal_self_correction",
                            "original": previous_token,
                            "replacement": next_token,
                        })
                        idx = right_index
                        matched_marker = True
                        break
                if right_index < len(tokens) and not output:
                    event_sink({
                        "kind": "inline_self_correction_applied",
                        "strategy": "verbal_self_correction",
                        "marker": " ".join(marker_phrase),
                    })
                    idx = right_index
                    matched_marker = True
                    break
                break
        if matched_marker:
            continue

        output.append(tokens[idx])
        idx += 1

    return output
