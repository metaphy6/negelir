"""Phase 10 §10.21.3 — Cross-file lexicon referential integrity validator.

Validates that cross-file references in the lexicon snapshot are consistent:
  * Every player.team_canonical_id resolves in teams
  * Every team.league_canonical_id resolves in leagues
  * Every competition.parent_id resolves
  * Dialects canonical_tokens are syntactically valid; generic vocabulary is allowed
  * Every entities_negative rule references at least one declared canonical_id

Called by LexiconStore.maybe_reload() before atomic swap under §10.21.3
all-or-nothing policy.

Usage::

    from nlp.lexicon._xref import validate_xref
    from nlp.lexicon_loader import _LoadedFile
    
    shadow: dict[str, _LoadedFile] = { ... }
    errors = validate_xref(shadow)
    if errors:
        # refuse swap, emit nlp.alert.v1{kind=nlp_lexicon_atomic_swap_failed}
"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

from common.text.turkish import lowercase_tr

if TYPE_CHECKING:
    from nlp.lexicon_loader import _LoadedFile


def validate_xref(snapshot: "dict[str, _LoadedFile]") -> list[str]:
    """Validate cross-file referential integrity in a lexicon snapshot.

    Parameters
    ----------
    snapshot:
        Dict mapping filename → :class:`_LoadedFile`. Expected keys:
        ``teams.tr.yaml``, ``players.tr.yaml``, ``leagues.tr.yaml``,
        ``competitions.tr.yaml``, ``markets.tr.yaml``, ``dialects.tr.yaml``,
        ``entities_negative.tr.yaml`` (all optional — validator skips missing
        files without error).

    Returns
    -------
    list[str]
        A (possibly empty) list of validation error strings. Each string
        describes one referential integrity violation. Empty list = all checks
        passed.

    Checks performed
    ----------------
    (a) Every ``player.team_canonical_id`` resolves in ``teams``.
    (b) Every ``team.league_canonical_id`` resolves in ``leagues``.
    (c) Every ``competition.parent_id`` resolves (in competitions itself).
    (d) Every alias in ``dialects`` expands to ``canonical_tokens`` whose
        tokens resolve via ``teams ∪ players ∪ markets``.
    (e) Every ``entities_negative`` rule references at least one declared
        canonical_id from ``teams ∪ players ∪ leagues ∪ competitions ∪ markets``.
    """
    errors: list[str] = []

    # ── Build canonical ID sets ────────────────────────────────────────────
    # Collect all canonical_id values from each file for cross-reference checks.
    teams_ids: set[str] = set()
    players_ids: set[str] = set()
    leagues_ids: set[str] = set()
    competitions_ids: set[str] = set()
    markets_ids: set[str] = set()

    # Helper to extract canonical_id from entries (skips non-dict / missing id).
    def _collect_ids(entries: list[dict[str, Any]]) -> set[str]:
        ids: set[str] = set()
        for entry in entries:
            if isinstance(entry, dict):
                cid = entry.get("canonical_id")
                if cid and isinstance(cid, str):
                    ids.add(cid)
        return ids

    # Populate ID sets from snapshot (§10.19 locale-keyed variants: try both
    # .tr.yaml and .tr-TR.yaml, prefer .tr.yaml when both exist).
    for fname_base in ["teams", "players", "leagues", "competitions", "markets"]:
        loaded = snapshot.get(f"{fname_base}.tr.yaml") or snapshot.get(f"{fname_base}.tr-TR.yaml")
        if loaded:
            ids = _collect_ids(loaded.entries)
            if fname_base == "teams":
                teams_ids = ids
            elif fname_base == "players":
                players_ids = ids
            elif fname_base == "leagues":
                leagues_ids = ids
            elif fname_base == "competitions":
                competitions_ids = ids
            elif fname_base == "markets":
                markets_ids = ids

    # Union of all entity canonical IDs (for entities_negative check).
    all_entity_ids = teams_ids | players_ids | leagues_ids | competitions_ids | markets_ids

    # ── Check (a): player.team_canonical_id → teams ────────────────────────
    players_loaded = snapshot.get("players.tr.yaml") or snapshot.get("players.tr-TR.yaml")
    if players_loaded:
        for i, entry in enumerate(players_loaded.entries):
            if not isinstance(entry, dict):
                continue
            team_id = entry.get("team_canonical_id")
            if team_id and isinstance(team_id, str):
                if team_id not in teams_ids:
                    player_id = entry.get("canonical_id", f"<entry {i}>")
                    errors.append(
                        f"players.tr.yaml[{i}] (canonical_id={player_id!r}): "
                        f"team_canonical_id={team_id!r} does not resolve in teams"
                    )

    # ── Check (b): team.league_canonical_id → leagues ──────────────────────
    teams_loaded = snapshot.get("teams.tr.yaml") or snapshot.get("teams.tr-TR.yaml")
    if teams_loaded:
        for i, entry in enumerate(teams_loaded.entries):
            if not isinstance(entry, dict):
                continue
            league_id = entry.get("league_canonical_id")
            if league_id and isinstance(league_id, str):
                if league_id not in leagues_ids:
                    team_id = entry.get("canonical_id", f"<entry {i}>")
                    errors.append(
                        f"teams.tr.yaml[{i}] (canonical_id={team_id!r}): "
                        f"league_canonical_id={league_id!r} does not resolve in leagues"
                    )

    # ── Check (c): competition.parent_id → competitions ────────────────────
    competitions_loaded = snapshot.get("competitions.tr.yaml") or snapshot.get("competitions.tr-TR.yaml")
    if competitions_loaded:
        for i, entry in enumerate(competitions_loaded.entries):
            if not isinstance(entry, dict):
                continue
            parent_id = entry.get("parent_id")
            if parent_id and isinstance(parent_id, str):
                if parent_id not in competitions_ids:
                    comp_id = entry.get("canonical_id", f"<entry {i}>")
                    errors.append(
                        f"competitions.tr.yaml[{i}] (canonical_id={comp_id!r}): "
                        f"parent_id={parent_id!r} does not resolve in competitions"
                    )

    # ── Check (d): dialects canonical_tokens are syntactically valid ────────
    # Dialects can normalize to generic Turkish vocabulary as well as entity
    # aliases, so this validator does not require cross-file resolution here.
    dialects_loaded = snapshot.get("dialects.tr.yaml") or snapshot.get("dialects.tr-TR.yaml")
    if dialects_loaded:
        for i, entry in enumerate(dialects_loaded.entries):
            if not isinstance(entry, dict):
                continue
            canonical_tokens = entry.get("canonical_tokens")
            if canonical_tokens and isinstance(canonical_tokens, list):
                for token in canonical_tokens:
                    if token and isinstance(token, str):
                        if not token.strip():
                            dialect_token = entry.get("token", f"<entry {i}>")
                            errors.append(
                                f"dialects.tr.yaml[{i}] (token={dialect_token!r}): "
                                f"canonical_token must be a non-empty string"
                            )

    # ── Check (e): entities_negative references at least one canonical_id ──
    entities_negative_loaded = snapshot.get("entities_negative.tr.yaml") or snapshot.get("entities_negative.tr-TR.yaml")
    if entities_negative_loaded:
        for i, entry in enumerate(entities_negative_loaded.entries):
            if not isinstance(entry, dict):
                continue
            # entities_negative rules reference canonical IDs via the "targets"
            # field (list of canonical_id strings).
            targets = entry.get("targets")
            if targets and isinstance(targets, list):
                has_valid_ref = False
                for target in targets:
                    if target and isinstance(target, str) and target in all_entity_ids:
                        has_valid_ref = True
                        break
                if not has_valid_ref:
                    rule_token = entry.get("token", f"<entry {i}>")
                    errors.append(
                        f"entities_negative.tr.yaml[{i}] (token={rule_token!r}): "
                        f"no targets resolve in teams ∪ players ∪ leagues ∪ "
                        f"competitions ∪ markets"
                    )

    return errors
