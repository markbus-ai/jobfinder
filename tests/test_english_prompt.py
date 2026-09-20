"""
The English instruction sent to the model must never map silence to null.

The real corpus is overwhelmingly silent about English (98.8% of listings), and a
null answer is withheld fail-closed in code, so a "use null when silent"
instruction would keep every otherwise-good match out of the pipeline. These
tests lock the field description and rule 11 to one shared definition of
'fluent' and to 'intermediate' for silence.
"""

import re

from services.EnglishPolicy import ENGLISH_LEVELS
from services.GroqService import (
    _ENGLISH_LEVEL_MEANINGS,
    _ENGLISH_REQUIRED_DESCRIPTION,
    _ENGLISH_SILENCE_RULE,
    _FLUENT_DEFINITION,
    ENGLISH_LEVEL_PROMPT,
)


def test_field_description_instructs_intermediate_for_silence():
    lowered = _ENGLISH_REQUIRED_DESCRIPTION.lower()
    assert "default to 'intermediate'" in lowered
    assert "silence" in lowered
    assert "most listings say nothing about english" in lowered


_NULL_NEGATIONS = ("never", "not", "nothing", "no ")


def test_field_description_never_instructs_null_for_silence():
    # Regression for the contradiction that kept the pipeline empty: the field
    # description must never tell the model to answer null when the listing is
    # silent. Every clause that mentions null must be a prohibition.
    clauses = [
        part.strip()
        for part in re.split(r"[.;:]", _ENGLISH_REQUIRED_DESCRIPTION)
        if "null" in part.lower()
    ]
    assert clauses, "the field description must address null explicitly"
    for clause in clauses:
        assert any(neg in clause.lower() for neg in _NULL_NEGATIONS), clause
    for forbidden in (
        "use null when the listing is silent",
        "null when the listing says nothing",
    ):
        assert forbidden not in _ENGLISH_REQUIRED_DESCRIPTION.lower()


def test_fluent_definition_is_shared_and_excludes_listing_language():
    # One definition used verbatim in both places, so they cannot diverge.
    assert _FLUENT_DEFINITION in _ENGLISH_REQUIRED_DESCRIPTION
    assert _FLUENT_DEFINITION in ENGLISH_LEVEL_PROMPT
    # A listing merely written in English is at most 'intermediate'.
    assert "written in english" in _FLUENT_DEFINITION.lower()
    assert "at most 'intermediate'" in _FLUENT_DEFINITION.lower()
    # The old "whole listing being in English" fluent trigger must stay gone.
    assert "whole listing being in english" not in ENGLISH_LEVEL_PROMPT.lower()
    assert "whole listing being in english" not in _ENGLISH_REQUIRED_DESCRIPTION.lower()


def test_rule_11_and_field_description_agree_on_silence():
    assert _ENGLISH_SILENCE_RULE in _ENGLISH_REQUIRED_DESCRIPTION
    assert _ENGLISH_SILENCE_RULE in ENGLISH_LEVEL_PROMPT


def test_english_level_meanings_cover_the_closed_vocabulary():
    # A new level must not be added without a meaning: the dict is keyed by level
    # and asserted complete at import time.
    assert set(_ENGLISH_LEVEL_MEANINGS) == set(ENGLISH_LEVELS)
