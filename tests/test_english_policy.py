"""
FIX 4: report the required English level and withhold roles above the ceiling.

The candidate genuinely does not speak much English, so a fluent-English role
must not reach him even at a perfect technical score.
"""

import logging

import pytest
from sqlmodel import Session

from models.JobModels import Job
from services.EnglishPolicy import (
    ENGLISH_LEVELS,
    EnglishLevel,
    english_allowed,
    is_notifiable_with_stored_english,
    normalize_level,
)
from services.GroqService import JobAudit


@pytest.mark.parametrize("level", ["none", "basic", "intermediate"])
def test_default_ceiling_allows_up_to_intermediate(level):
    assert english_allowed(level, "intermediate") is True


def test_default_ceiling_withholds_fluent():
    assert english_allowed("fluent", "intermediate") is False


def test_ceiling_changes_the_outcome():
    assert english_allowed("fluent", "fluent") is True
    assert english_allowed("basic", "none") is False
    assert english_allowed("none", "none") is True


@pytest.mark.parametrize("missing", [None, "", "bogus", "advanced", 123, []])
def test_missing_or_unknown_level_fails_closed(missing):
    assert english_allowed(missing, "fluent") is False


@pytest.mark.parametrize("ceiling", [None, "", "bogus"])
def test_unknown_ceiling_fails_closed(ceiling):
    assert english_allowed("none", ceiling) is False


def test_normalize_level_is_case_insensitive():
    assert normalize_level("FLUENT") is EnglishLevel.FLUENT
    assert normalize_level(EnglishLevel.BASIC) is EnglishLevel.BASIC
    assert normalize_level("nope") is None


def test_jobaudit_defaults_to_none_when_english_is_omitted():
    # W3: a missing field is NOT coerced to 'intermediate' (that would pass the
    # gate). The model is separately instructed to answer 'intermediate' when the
    # listing is silent; if it fails to comply, CODE must fail closed.
    audit = JobAudit(
        match_score=10,
        is_suitable=False,
        missing_skills=[],
        seniority_mismatch=False,
        short_verdict="x",
        recommended_profile="backend",
        key_requirements=[],
    )
    assert audit.english_required is None
    assert audit.english_evidence == ""


# --- W1: the closed vocabulary is a single source of truth -------------------

def test_english_levels_are_a_closed_ordered_vocabulary():
    assert ENGLISH_LEVELS == ("none", "basic", "intermediate", "fluent")


def test_english_required_schema_exposes_the_literal_enum():
    schema = JobAudit.model_json_schema()["properties"]["english_required"]
    assert {"enum": list(ENGLISH_LEVELS), "type": "string"} in schema["anyOf"]
    assert {"type": "null"} in schema["anyOf"]


@pytest.mark.parametrize("level", ENGLISH_LEVELS)
def test_vocabulary_english_is_preserved(level):
    audit = JobAudit(
        match_score=10,
        is_suitable=False,
        missing_skills=[],
        seniority_mismatch=False,
        short_verdict="x",
        recommended_profile="backend",
        key_requirements=[],
        english_required=level,
    )
    assert audit.english_required == level


@pytest.mark.parametrize(
    "raw", [None, "", "   ", "C1", "B2", "fluent English", "advanced", 123, ["fluent"]]
)
def test_out_of_vocabulary_english_coerces_to_none(raw):
    # A non-compliant model answer must not crash the analysis nor slip past the
    # gate: it is normalized to None, which fails closed downstream.
    audit = JobAudit(
        match_score=10,
        is_suitable=False,
        missing_skills=[],
        seniority_mismatch=False,
        short_verdict="x",
        recommended_profile="backend",
        key_requirements=[],
        english_required=raw,
    )
    assert audit.english_required is None


def test_prompt_defaults_to_intermediate_and_uses_the_vocabulary():
    from services.GroqService import ENGLISH_LEVEL_PROMPT

    assert "default to 'intermediate'" in ENGLISH_LEVEL_PROMPT
    for level in ENGLISH_LEVELS:
        assert f"'{level}'" in ENGLISH_LEVEL_PROMPT


def test_default_ceiling_is_intermediate():
    # G6: the bare default of EnglishPolicy.english_allowed must stay at
    # 'intermediate'. Raising it to 'fluent' would leak fluent roles.
    assert english_allowed("intermediate") is True
    assert english_allowed("fluent") is False


def test_default_max_english_level_config_is_intermediate():
    # G3: the configured default ceiling must not drift upward.
    from core.config import settings

    assert settings.MAX_ENGLISH_LEVEL == "intermediate"


# --- Pipeline integration ----------------------------------------------------

def _job(job_id):
    return Job(
        id=job_id,
        title="Backend Engineer",
        company="Acme",
        location="Remote",
        url=job_id,
        description="Python FastAPI role.",
        is_remote=True,
    )


def _audit(english):
    return JobAudit(
        match_score=90,
        is_suitable=True,
        missing_skills=[],
        seniority_mismatch=False,
        short_verdict="Excellent technical fit",
        recommended_profile="backend",
        key_requirements=["Python"],
        work_mode="remote",
        english_required=english,
        english_evidence="fluent English required" if english == "fluent" else "",
    )


def _load(job_id):
    from database import engine

    with Session(engine) as session:
        return session.get(Job, job_id)


@pytest.mark.parametrize("english", ["none", "basic", "intermediate"])
def test_allowed_levels_are_notified(fresh_db, cycle_runner, english):
    job_id = f"https://example.com/job/{english}"
    _, notifications = cycle_runner([_job(job_id)], lambda *a, **k: _audit(english))

    stored = _load(job_id)
    assert stored.english_required == english
    assert stored.notified is True
    assert [n["id"] for n in notifications] == [job_id]


def test_fluent_role_is_withheld(fresh_db, cycle_runner):
    job_id = "https://example.com/job/fluent"
    _, notifications = cycle_runner([_job(job_id)], lambda *a, **k: _audit("fluent"))

    stored = _load(job_id)
    assert stored.ai_match_score == 90
    assert stored.english_required == "fluent"
    # W1 nit: the evidence is persisted so a withholding is auditable.
    assert stored.english_evidence == "fluent English required"
    assert stored.notified is False
    assert notifications == []


def test_ceiling_override_allows_fluent(fresh_db, cycle_runner):
    job_id = "https://example.com/job/fluent-override"
    _, notifications = cycle_runner(
        [_job(job_id)], lambda *a, **k: _audit("fluent"), MAX_ENGLISH_LEVEL="fluent"
    )

    stored = _load(job_id)
    assert stored.notified is True
    assert [n["id"] for n in notifications] == [job_id]


def test_missing_english_level_is_withheld(fresh_db, cycle_runner):
    job_id = "https://example.com/job/unknown-english"
    audit = _audit("intermediate")
    audit.english_required = "unknown-level"
    _, notifications = cycle_runner([_job(job_id)], lambda *a, **k: audit)

    stored = _load(job_id)
    assert stored.notified is False
    assert notifications == []


@pytest.mark.parametrize("raw", [None, "", "   ", "C1"])
def test_non_vocabulary_english_is_withheld_and_logged(fresh_db, cycle_runner, caplog, raw):
    # W3: missing/empty/out-of-vocabulary levels are withheld AND the reason is
    # logged so the decision stays auditable. Assignment bypasses validation on
    # purpose, simulating a legacy or manually-written stored value.
    job_id = f"https://example.com/job/withheld-{raw!r}"
    audit = _audit("intermediate")
    audit.english_required = raw

    caplog.set_level(logging.INFO)
    _, notifications = cycle_runner([_job(job_id)], lambda *a, **k: audit)

    stored = _load(job_id)
    assert stored.notified is False
    assert notifications == []
    assert "Withheld" in caplog.text


def test_model_emitted_out_of_vocabulary_level_is_withheld(fresh_db, cycle_runner):
    # End-to-end W1+W3: the model answers 'C1', the validator normalizes it to
    # None, and the gate withholds it.
    job_id = "https://example.com/job/model-c1"
    _, notifications = cycle_runner([_job(job_id)], lambda *a, **k: _audit("C1"))

    stored = _load(job_id)
    assert stored.english_required is None
    assert stored.notified is False
    assert notifications == []


# --- W2: raising the ceiling retroactively releases withheld rows -------------

def test_raising_ceiling_releases_stored_row_without_ai(fresh_db, cycle_runner):
    job_id = "https://example.com/job/retro-english"
    calls = []

    def analyze(job_arg, cv_data):
        calls.append(job_arg.id)
        return _audit("fluent")

    # Cycle 1: withheld by the intermediate ceiling, analyzed exactly once.
    _, first = cycle_runner([_job(job_id)], analyze, MAX_ENGLISH_LEVEL="intermediate")
    assert first == []
    assert calls == [job_id]

    stored = _load(job_id)
    assert stored.notified is False
    assert stored.ai_match_score == 90

    # Cycle 2: the ceiling is raised. The stored row is released with no AI call.
    _, second = cycle_runner([_job(job_id)], analyze, MAX_ENGLISH_LEVEL="fluent")
    assert [n["id"] for n in second] == [job_id]
    assert calls == [job_id], "the release path must not call the AI"

    stored = _load(job_id)
    assert stored.notified is True

    # Cycle 3: already notified, so it must not be re-notified.
    _, third = cycle_runner([_job(job_id)], analyze, MAX_ENGLISH_LEVEL="fluent")
    assert third == []
    assert calls == [job_id]


@pytest.mark.parametrize(
    "stored_score,location_eligible,analysis_failed,notified",
    [
        (50, True, False, False),   # below the score threshold
        (90, False, False, False),  # location-ineligible
        (90, None, False, False),   # location verdict unknown (NULL) must stay closed
        (90, True, True, False),    # failed analysis (belongs to the retry path)
        (90, True, False, True),    # already notified
    ],
)
def test_stored_english_predicate_rejects_non_withheld_rows(
    stored_score, location_eligible, analysis_failed, notified
):
    assert (
        is_notifiable_with_stored_english(
            location_eligible=location_eligible,
            match_score=stored_score,
            notified=notified,
            analysis_failed=analysis_failed,
            english_required="fluent",
            min_match_score=70,
            max_english_level="fluent",
        )
        is False
    )


@pytest.mark.parametrize("location_eligible", [True, False, None])
def test_stored_english_predicate_delegates_location_and_score(location_eligible):
    # The stored-row gate must delegate the location+score rule to
    # LocationPolicy.is_notifiable so the two can never drift. This locks the
    # equivalence, including location_eligible=None (which must stay closed).
    from services.LocationPolicy import is_notifiable

    assert is_notifiable_with_stored_english(
        location_eligible=location_eligible,
        match_score=90,
        notified=False,
        analysis_failed=False,
        english_required="fluent",
        min_match_score=70,
        max_english_level="fluent",
    ) is is_notifiable(location_eligible, 90, 70)


def test_stored_english_predicate_accepts_releasable_row():
    assert is_notifiable_with_stored_english(
        location_eligible=True,
        match_score=90,
        notified=False,
        analysis_failed=False,
        english_required="fluent",
        min_match_score=70,
        max_english_level="fluent",
    )
    # The same row stays withheld while the ceiling is still too low.
    assert is_notifiable_with_stored_english(
        location_eligible=True,
        match_score=90,
        notified=False,
        analysis_failed=False,
        english_required="fluent",
        min_match_score=70,
        max_english_level="intermediate",
    ) is False
