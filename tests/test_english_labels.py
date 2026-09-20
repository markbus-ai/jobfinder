"""
The Telegram label map must cover every level of the closed vocabulary.

The map is keyed by level and asserted complete at import time, so adding a level
without a label fails loudly instead of silently dropping the label.
"""

from services.EnglishPolicy import ENGLISH_LEVELS


def test_english_level_display_labels_cover_the_closed_vocabulary():
    from main import ENGLISH_LEVEL_LABELS

    assert set(ENGLISH_LEVEL_LABELS) == set(ENGLISH_LEVELS)
    assert all(ENGLISH_LEVEL_LABELS.values())
