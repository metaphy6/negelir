from __future__ import annotations

import pathlib as _pathlib
from dataclasses import dataclass
from typing import Callable

try:
    import yaml as _yaml  # type: ignore[import]
    _YAML_AVAILABLE = True
except ImportError:  # pragma: no cover
    _YAML_AVAILABLE = False

from ai.common.text.turkish import lowercase_tr

_PRODUCTIVE_SUFFIXES_PATH: _pathlib.Path = (
    _pathlib.Path(__file__).parent  # ai/nlp/morph/
    .parent                          # ai/nlp/
    / "lang_tr"
    / "productive_suffixes.tr.yaml"
)

_PRODUCTIVE_PEEL_NO_FIRE_PATH: _pathlib.Path = (
    _pathlib.Path(__file__).parent
    .parent
    / "lang_tr"
    / "productive_peel_no_fire.tr.yaml"
)

_SUFFIX_CANDIDATE_CACHE: "list[tuple[str, str]] | None" = None
_NO_FIRE_CACHE: "set[str] | None" = None


@dataclass(frozen=True)
class ProductivePeelResult:
    """Result of a productive suffix peel attempt."""

    original_token: str
    stripped_token: str
    peeled_suffixes: tuple[str, ...]
    success: bool

    @property
    def audit(self) -> dict[str, object]:
        return {
            "original_token": self.original_token,
            "stripped_token": self.stripped_token,
            "peeled_suffixes": list(self.peeled_suffixes),
            "success": self.success,
        }


def _load_productive_suffixes(path: _pathlib.Path | None = None) -> list[dict[str, object]]:
    global _SUFFIX_CANDIDATE_CACHE
    if path is None and _SUFFIX_CANDIDATE_CACHE is not None:
        return []
    effective = path or _PRODUCTIVE_SUFFIXES_PATH
    if not _YAML_AVAILABLE or not effective.exists():
        return []
    with open(effective, "r", encoding="utf-8") as fh:
        data = _yaml.safe_load(fh) or {}
    return data.get("productive_suffixes", [])


def load_productive_suffix_families(path: _pathlib.Path | None = None) -> list[dict[str, object]]:
    """Load the productive suffix family definitions from YAML."""
    return _load_productive_suffixes(path)


def load_productive_peel_no_fire_allowlist(path: _pathlib.Path | None = None) -> set[str]:
    global _NO_FIRE_CACHE
    if path is None and _NO_FIRE_CACHE is not None:
        return _NO_FIRE_CACHE
    effective = path or _PRODUCTIVE_PEEL_NO_FIRE_PATH
    if not _YAML_AVAILABLE or not effective.exists():
        allowlist: set[str] = set()
    else:
        with open(effective, "r", encoding="utf-8") as fh:
            data = _yaml.safe_load(fh) or {}
        raw = data.get("entries", [])
        allowlist = {
            lowercase_tr(str(item).strip())
            for item in raw
            if isinstance(item, str) and item.strip()
        }
    if path is None:
        _NO_FIRE_CACHE = allowlist
    return allowlist


def _build_suffix_candidates(
    families: list[dict[str, object]],
) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    for family in families:
        name = str(family.get("id", ""))
        for form in family.get("forms", []):
            if not isinstance(form, str):
                continue
            candidates.append((form, name))
    # Longest-first prevents partial peel of a longer matching suffix.
    candidates.sort(key=lambda item: len(item[0]), reverse=True)
    return candidates


def _normalize_for_peel(token: str) -> str:
    return lowercase_tr(token).replace("'", "")


def peel_productive_suffixes(
    token: str,
    *,
    can_resolve: Callable[[str], bool],
    max_depth: int = 3,
    min_residue_resolution: bool = True,
    _families: list[dict[str, object]] | None = None,
    _no_fire_allowlist: set[str] | None = None,
) -> ProductivePeelResult:
    """Iteratively peel productive derivational suffixes from the token.

    The token is only rewritten when the remaining residue resolves to a
    canonical reference.  This prevents false-positive peeling on common
    nouns such as "birlik".
    """
    if not token:
        return ProductivePeelResult(token, token, (), False)

    normalized_token = _normalize_for_peel(token)
    if _no_fire_allowlist is None:
        _no_fire_allowlist = load_productive_peel_no_fire_allowlist()
    if normalized_token in _no_fire_allowlist:
        return ProductivePeelResult(token, token, (), False)

    families = _families if _families is not None else load_productive_suffix_families()
    suffix_candidates = _build_suffix_candidates(families)

    def _recursive_peel(current_token: str, depth: int) -> ProductivePeelResult | None:
        if depth == 0 or not current_token:
            return None
        if current_token in _no_fire_allowlist:
            return None
        for suffix, _family in suffix_candidates:
            if not current_token.endswith(suffix):
                continue
            residue = current_token[: len(current_token) - len(suffix)]
            if min_residue_resolution and not can_resolve(residue):
                nested = _recursive_peel(residue, depth - 1)
                if nested is not None and nested.success:
                    return ProductivePeelResult(
                        original_token=token,
                        stripped_token=nested.stripped_token,
                        peeled_suffixes=(suffix,) + nested.peeled_suffixes,
                        success=True,
                    )
                continue
            if can_resolve(residue):
                return ProductivePeelResult(
                    original_token=token,
                    stripped_token=residue,
                    peeled_suffixes=(suffix,),
                    success=True,
                )
            nested = _recursive_peel(residue, depth - 1)
            if nested is not None and nested.success:
                return ProductivePeelResult(
                    original_token=token,
                    stripped_token=nested.stripped_token,
                    peeled_suffixes=(suffix,) + nested.peeled_suffixes,
                    success=True,
                )
        return None

    result = _recursive_peel(normalized_token, max_depth)
    if result is None:
        return ProductivePeelResult(token, _normalize_for_peel(token), (), False)
    return result
