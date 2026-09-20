"""
Deterministic English-level gate for job notifications.

The candidate genuinely does not speak much English, so a listing that demands
fluent English is not actionable for him even when the technical fit is high.
This module is intentionally dependency-free (standard library only) and pure,
in the same spirit as ``services.LocationPolicy.is_notifiable``.

The level is a small, closed vocabulary and the comparison is done on an ordered
enum, never on arbitrary text. Anything missing or outside the vocabulary fails
CLOSED (withheld).
"""

from __future__ import annotations

from enum import Enum
from typing import Optional


class EnglishLevel(str, Enum):
    """Closed vocabulary for the English level a listing requires."""

    NONE = "none"
    BASIC = "basic"
    INTERMEDIATE = "intermediate"
    FLUENT = "fluent"


# Ordinal rank used for the ceiling comparison. Lower is easier.
_LEVEL_ORDER: dict[EnglishLevel, int] = {
    EnglishLevel.NONE: 0,
    EnglishLevel.BASIC: 1,
    EnglishLevel.INTERMEDIATE: 2,
    EnglishLevel.FLUENT: 3,
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
