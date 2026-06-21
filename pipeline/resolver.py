"""
Negelir — Match resolver.
Phase 2: Maps user questions to specific upcoming fixtures.
"""

import re
from datetime import datetime, timedelta

from common.logger import get_logger

log = get_logger("pipeline.resolver")


class MatchResolver:
    """Resolve user team/time references to a specific fixture."""

    def resolve(self, team_ids: list[int], time_ref: str | None,
                fixtures: list, results: list | None = None) -> object | None:
        """
        Find the fixture matching the user's query.

        Args:
            team_ids: mackolik team IDs from entity extraction
            time_ref: "today", "tomorrow", "this_week", or None
            fixtures: list of Fixture objects (upcoming matches)
            results: list of Result objects (past matches) for form queries

        Returns:
            Fixture object or None if no match found.
        """
        if not team_ids:
            return None

        # Filter fixtures involving any of the referenced teams
        candidates = []
        for f in fixtures:
            if f.home_id in team_ids or f.away_id in team_ids:
                candidates.append(f)

        if not candidates:
            log.debug(f"No fixtures found for team_ids={team_ids}")
            return None

        # Apply time filter if provided
        if time_ref:
            filtered = self._filter_by_time(candidates, time_ref)
            if filtered:
                candidates = filtered

        # Return nearest future fixture
        candidates.sort(key=lambda f: f.date)
        selected = candidates[0]
        log.info(f"Resolved fixture: {selected.home_id} vs {selected.away_id} ({selected.date})")
        return selected

    def resolve_recent_result(self, team_ids: list[int],
                              results: list) -> object | None:
        """Find the most recent result for a team (for form/h2h queries)."""
        if not team_ids or not results:
            return None

        candidates = [r for r in results
                      if r.home_id in team_ids or r.away_id in team_ids]
        if not candidates:
            return None

        candidates.sort(key=lambda r: r.date, reverse=True)
        return candidates[0]

    @staticmethod
    def _filter_by_time(fixtures: list, time_ref: str) -> list:
        """Filter fixtures by temporal reference."""
        now = datetime.now()

        if time_ref == "today":
            today_str = now.strftime("%d/%m")
            return [f for f in fixtures if f.date.startswith(today_str)]

        elif time_ref == "tomorrow":
            tomorrow = now + timedelta(days=1)
            tomorrow_str = tomorrow.strftime("%d/%m")
            return [f for f in fixtures if f.date.startswith(tomorrow_str)]

        elif time_ref == "this_week":
            # Current week: today through Sunday
            days_until_sunday = 6 - now.weekday()
            end = now + timedelta(days=max(days_until_sunday, 1))
            week_dates = set()
            for d in range(days_until_sunday + 1):
                dt = now + timedelta(days=d)
                week_dates.add(dt.strftime("%d/%m"))
            return [f for f in fixtures
                    if any(f.date.startswith(d) for d in week_dates)]

        return fixtures
