"""
Deterministic English-level gate for job notifications.

The candidate genuinely does not speak much English, so a listing that demands
fluent English is not actionable for him even when the technical fit is high.
This module is intentionally dependency-free (standard library only) and pure,
in the same spirit as ``services.LocationPolicy.is_notifiable``.

The level is a small, closed vocabulary and the comparison is done on an ordered
enum, never on arbitrary text. Anything missing or outside the vocabulary fails
CLOSED (withheld).

``EnglishLevelLiteral`` is the single source of truth for that vocabulary: the
enum, the ordinal ranking, the AI response schema, the prompt wording, and the
Telegram display labels all derive from ``ENGLISH_LEVELS``. Add a level here
once, and nowhere else.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional, get_args


# Single source of truth for the closed vocabulary, in ascending difficulty
# order. Ordering is the tuple order, so adding a level in the wrong position is
# the only way to break the ceiling comparison.
EnglishLevelLiteral = Literal["none", "basic", "intermediate", "fluent"]
ENGLISH_LEVELS: tuple[str, ...] = get_args(EnglishLevelLiteral)


EnglishLevel = Enum(
    "EnglishLevel",
    {level.upper(): level for level in ENGLISH_LEVELS},
    type=str,
    module=__name__,
)


# Ordinal rank used for the ceiling comparison, derived from ENGLISH_LEVELS so
# the ordering can never drift from the vocabulary. Lower is easier.
_LEVEL_ORDER: dict[EnglishLevel, int] = {
    EnglishLevel(level): index for index, level in enumerate(ENGLISH_LEVELS)
}


def normalize_level(value: object) -> Optional[EnglishLevel]:
    """Resolve a raw value to an ``EnglishLevel``, or ``None`` when unknown."""
    if isinstance(value, EnglishLevel):
        return value
    if value is None:
        return None
    try:
        return EnglishLevel(str(value).strip().lower())
    except ValueError:
        return None


def english_allowed(
    english_required: object,
    max_english_level: object = EnglishLevel.INTERMEDIATE,
) -> bool:
    """
    Pure notification gate for the English requirement.

    Returns ``True`` only when the listing's required level is at or below the
    configured ceiling. A missing or unknown level fails CLOSED (returns
    ``False``) rather than open, so an unclassified listing is never notified by
    mistake.
    """
    required = normalize_level(english_required)
    ceiling = normalize_level(max_english_level)
    if required is None or ceiling is None:
        return False
    return _LEVEL_ORDER[required] <= _LEVEL_ORDER[ceiling]


def is_notifiable_with_stored_english(
    *,
    location_eligible: Optional[bool],
    match_score: Optional[int],
    notified: bool,
    analysis_failed: bool,
    english_required: object,
    min_match_score: int,
    max_english_level: object,
) -> bool:
    """
    Pure predicate: may an already-stored row be released by the English ceiling?

    This exists for one reason: when ``MAX_ENGLISH_LEVEL`` is raised, a row that
    was withheld only because its required English level exceeded the old ceiling
    must become notifiable retroactively. It decides from persisted values only,
    so the caller must resolve it WITHOUT a re-analysis or a re-scrape.

    Returns ``True`` only when the stored row already cleared the location and
    score gates, was never notified, did not fail analysis, and its stored
    English level now passes the current ceiling. Anything unknown still fails
    closed through ``english_allowed``.
    """
    if notified or analysis_failed:
        return False
    if location_eligible is not True:
        return False
    if match_score is None or match_score < min_match_score:
        return False
    return english_allowed(english_required, max_english_level)
