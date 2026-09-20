"""
FIX 4: report the required English level and withhold roles above the ceiling.

The candidate genuinely does not speak much English, so a fluent-English role
must not reach him even at a perfect technical score.
"""

import pytest
from sqlmodel import Session

from models.JobModels import Job
from services.EnglishPolicy import EnglishLevel, english_allowed, normalize_level
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


def test_jobaudit_defaults_to_intermediate():
    audit = JobAudit(
        match_score=10,
        is_suitable=False,
        missing_skills=[],
        seniority_mismatch=False,
        short_verdict="x",
        recommended_profile="backend",
        key_requirements=[],
    )
    assert audit.english_required == "intermediate"
    assert audit.english_evidence == ""


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
