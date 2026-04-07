"""
Negelir — Season state machine.
Phase 2: Replaces hardcoded CURRENT_SEASON with live detection.
"""

from enum import Enum

from common.logger import get_logger

log = get_logger("common.season")


class SeasonState(Enum):
    PRE_SEASON = "pre_season"      # fixtures exist but none played
    IN_SEASON = "in_season"        # some played, some upcoming
    POST_SEASON = "post_season"    # all played, no upcoming
    OFF_SEASON = "off_season"      # no fixture data for next season yet


def detect_season(seasons: dict[str, int],
                  fetch_season_fn) -> tuple[str | None, SeasonState, int | None]:
    """
    Detect the current season state from live data.

    Args:
        seasons: {label: season_id} from MackolikClient.discover_seasons()
        fetch_season_fn: callable(season_id) -> SeasonData

    Returns:
        (season_label, state, season_id) or (None, OFF_SEASON, None)
    """
    if not seasons:
        log.warning("No seasons discovered — OFF_SEASON")
        return (None, SeasonState.OFF_SEASON, None)

    sorted_seasons = sorted(seasons.items(), reverse=True)

    for label, season_id in sorted_seasons:
        data = fetch_season_fn(season_id)

        has_fixtures = len(data.fixtures) > 0
        has_results = len(data.results) > 0

        if has_fixtures and has_results:
            log.info(f"Season {label}: IN_SEASON ({len(data.results)} played, "
                     f"{len(data.fixtures)} upcoming)")
            return (label, SeasonState.IN_SEASON, season_id)

        if has_fixtures and not has_results:
            log.info(f"Season {label}: PRE_SEASON ({len(data.fixtures)} fixtures, 0 results)")
            return (label, SeasonState.PRE_SEASON, season_id)

        if has_results and not has_fixtures:
            # Season complete — check if a newer season exists
            idx = sorted_seasons.index((label, season_id))
            if idx == 0:
                # This is the most recent season and it's complete
                log.info(f"Season {label}: POST_SEASON (all {len(data.results)} played)")
                return (label, SeasonState.POST_SEASON, season_id)
            # There's a newer season, skip this completed one
            continue

    log.warning("No active season found — OFF_SEASON")
    return (None, SeasonState.OFF_SEASON, None)
