"""
Negelir — Locale loader.
Loads team maps, keywords, and compliance lists from external YAML config.
Per Gemini §4 Phase 2: extract hardcoded Turkish strings for i18n readiness.
"""

import os
from pathlib import Path

import yaml

from .logger import get_logger

log = get_logger(__name__)

_LOCALE_DIR = Path(__file__).parent
_DEFAULT_LOCALE = "tr"


def _locale_id() -> str:
    return os.getenv("NEGELIR_LOCALE", _DEFAULT_LOCALE)


def load_locale(locale: str | None = None) -> dict:
    """Load a locale YAML file and return the parsed dict."""
    locale = locale or _locale_id()
    path = _LOCALE_DIR / f"locale_{locale}.yaml"
    if not path.exists():
        log.warning("Locale file %s not found, falling back to %s", path, _DEFAULT_LOCALE)
        path = _LOCALE_DIR / f"locale_{_DEFAULT_LOCALE}.yaml"
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    log.info("Loaded locale '%s' from %s", locale, path.name)
    return data


def build_team_map(data: dict) -> dict[str, str]:
    """Build alias→uuid mapping from locale teams section."""
    team_map: dict[str, str] = {}
    for uuid, info in data.get("teams", {}).items():
        for alias in info.get("aliases", []):
            team_map[alias] = uuid
    return team_map


def build_uuid_to_name(data: dict) -> dict[str, str]:
    """Build uuid→display_name reverse map from locale teams section."""
    return {
        uuid: info["display_name"]
        for uuid, info in data.get("teams", {}).items()
        if "display_name" in info
    }


def build_derbies(data: dict) -> set[frozenset[str]]:
    """Build set of frozenset(display_name, display_name) from YAML derbies section."""
    teams = data.get("teams", {})
    result: set[frozenset[str]] = set()
    for pair in data.get("derbies", []):
        if len(pair) == 2:
            a = teams.get(pair[0], {}).get("display_name")
            b = teams.get(pair[1], {}).get("display_name")
            if a and b:
                result.add(frozenset((a, b)))
    return result


def build_derby_pairs(data: dict) -> list[tuple[str, str]]:
    """Build ordered list of (display_name, display_name) derby pairs."""
    teams = data.get("teams", {})
    result: list[tuple[str, str]] = []
    for pair in data.get("derbies", []):
        if len(pair) == 2:
            a = teams.get(pair[0], {}).get("display_name")
            b = teams.get(pair[1], {}).get("display_name")
            if a and b:
                result.append((a, b))
    return result


def build_team_strength(data: dict) -> dict[str, tuple[float, float]]:
    """Build display_name → (attack, defense) map from YAML strength section."""
    result: dict[str, tuple[float, float]] = {}
    for _uuid, info in data.get("teams", {}).items():
        name = info.get("display_name")
        strength = info.get("strength")
        if name and strength:
            result[name] = (strength.get("attack", 1.0), strength.get("defense", 1.0))
    return result


def build_source_alias_map(data: dict) -> dict[str, str]:
    """Build source_alias → canonical display_name map for scraper normalisation."""
    result: dict[str, str] = {}
    for _uuid, info in data.get("teams", {}).items():
        name = info.get("display_name")
        if not name:
            continue
        # The display name itself is always canonical
        result[name] = name
        # Add all external source aliases
        for _source, alias in info.get("source_aliases", {}).items():
            result[alias] = name
    return result


def build_team_names(data: dict) -> list[str]:
    """Build sorted list of all team display names."""
    return sorted(
        info["display_name"]
        for info in data.get("teams", {}).values()
        if "display_name" in info
    )


def build_mackolik_id_map(data: dict) -> dict[int, str]:
    """Build mackolik_id → display_name map for arsiv.mackolik.com team resolution."""
    result: dict[int, str] = {}
    for _uuid, info in data.get("teams", {}).items():
        name = info.get("display_name")
        mid = info.get("mackolik_id")
        if name and mid is not None:
            result[int(mid)] = name
    return result
