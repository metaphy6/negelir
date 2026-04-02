"""
Negelir TQU — Entity extraction from sanitized Turkish text.
Extracts team references, goal numbers, match references.
Per roadmap §5.1 TQU Step 4.
"""

import re
from dataclasses import dataclass, field

from common.constants import TEAM_MAP
from common.logger import get_logger

log = get_logger("tqu.entities")

_GOAL_RANGE_RE = re.compile(r"(\d+)\s*[-–]\s*(\d+)")
_GOAL_THRESHOLD_RE = re.compile(r"(\d+)\s*'?\s*(ten|dan|den|tan)?\s*(fazla|çok|üstü|üzeri|az|altı|altında)")
_NUMBER_RE = re.compile(r"\b(\d+)\b")


@dataclass
class ExtractedEntities:
    team_refs: list[str] = field(default_factory=list)       # team UUIDs
    team_names: list[str] = field(default_factory=list)       # display names
    min_goals: int | None = None
    max_goals: int | None = None
    threshold: float = 2.5                                    # default over/under
    half: int | None = None                                   # 1 or 2
    match_ref: str | None = None


def extract_entities(text: str) -> ExtractedEntities:
    """Extract structured entities from sanitized Turkish text."""
    entities = ExtractedEntities()

    # ── Team names ──
    text_lower = text.lower()
    for name, uuid in TEAM_MAP.items():
        if name in text_lower and uuid not in entities.team_refs:
            entities.team_refs.append(uuid)
            entities.team_names.append(name.title())
            log.debug(f"Team found: {name} → {uuid}")

    # ── Goal range (e.g. "4-6 gol") ──
    range_match = _GOAL_RANGE_RE.search(text)
    if range_match:
        entities.min_goals = int(range_match.group(1))
        entities.max_goals = int(range_match.group(2))
        # Validate range (roadmap §5.6.2: goals 0-20)
        entities.min_goals = max(0, min(entities.min_goals, 20))
        entities.max_goals = max(0, min(entities.max_goals, 20))
        log.debug(f"Goal range: {entities.min_goals}-{entities.max_goals}")

    # ── Goal threshold (e.g. "3'ten fazla") ──
    threshold_match = _GOAL_THRESHOLD_RE.search(text)
    if threshold_match:
        val = int(threshold_match.group(1))
        direction = threshold_match.group(3) if threshold_match.group(3) else "fazla"
        if direction in ("fazla", "çok", "üstü", "üzeri"):
            entities.threshold = float(val) - 0.5  # "3'ten fazla" → 2.5 threshold
        elif direction in ("az", "altı", "altında"):
            entities.threshold = float(val) + 0.5
        log.debug(f"Goal threshold: {entities.threshold}")

    # ── Half reference ──
    if re.search(r"(ilk|birinci|1\.?)\s*(yarı|yari)", text, re.I):
        entities.half = 1
    elif re.search(r"(ikinci|2\.?)\s*(yarı|yari)", text, re.I):
        entities.half = 2

    # ── Over/under threshold from explicit numbers ──
    if "üst" in text_lower or "ust" in text_lower or "alt" in text_lower:
        nums = _NUMBER_RE.findall(text)
        if nums:
            entities.threshold = float(nums[0]) + 0.5 if float(nums[0]) == int(float(nums[0])) else float(nums[0])

    return entities
