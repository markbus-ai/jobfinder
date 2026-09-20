"""
FIX 2: a transient failure (HTTP 429, connection error, timeout, 5xx) must not
be persisted as a permanent 0/100, and a retryable row must be re-analyzed.
"""

import logging
import types
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
import groq
import pytest
from sqlmodel import Session

from models.JobModels import Job
from services.AnalysisRetry import (
    MAX_ANALYSIS_ATTEMPTS_CAP,
    RETRY_AFTER_SLEEP_CAP_SECONDS,
    TransientAnalysisError,
    cap_analysis_attempts,
    compute_backoff,
    extract_retry_after,
    extract_status_code,
    is_transient_exception,
    retry_after_sleep,
    should_reanalyze,
)
from services.GroqService import AIService, JobAudit

_REQUEST = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")


def _status_error(cls, status, retry_after=None):
    headers = {"retry-after": retry_after} if retry_after is not None else {}
    response = httpx.Response(
        status, headers=headers, json={"error": {"message": "x"}}, request=_REQUEST
    )
    return cls(f"Error code: {status}", response=response, body=None)


# --- Pure classification -----------------------------------------------------

@pytest.mark.parametrize(
    "exc,expected",
    [
        (_status_error(groq.RateLimitError, 429), True),
        (_status_error(groq.InternalServerError, 503), True),
        (groq.APIConnectionError(request=_REQUEST), True),
        (groq.APITimeoutError(request=_REQUEST), True),
        (_status_error(groq.BadRequestError, 400), False),
        (ValueError("not an api error"), False),
    ],
)
def test_is_transient_exception(exc, expected):
    assert is_transient_exception(exc) is expected


def test_is_transient_detects_wrapped_instructor_error():
    # instructor wraps the typed groq error in its own exception; the original is
    # reachable through the chain, which is how the production 429 surfaces.
    inner = _status_error(groq.RateLimitError, 429)
    wrapper = RuntimeError("Max retries exceeded")
    wrapper.__cause__ = inner
    assert is_transient_exception(wrapper) is True


def test_extract_retry_after_reads_structured_header():
    exc = _status_error(groq.RateLimitError, 429, retry_after="5")
    assert extract_retry_after(exc) == 5.0


def test_extract_retry_after_walks_the_wrapper_chain():
    inner = _status_error(groq.RateLimitError, 429, retry_after="3")
    wrapper = RuntimeError("wrapped")
    wrapper.__cause__ = inner
    assert extract_retry_after(wrapper) == 3.0


def test_extract_retry_after_is_none_without_header():
    assert extract_retry_after(_status_error(groq.RateLimitError, 429)) is None


def test_extract_retry_after_is_bounded():
    exc = _status_error(groq.RateLimitError, 429, retry_after="9999")
    assert extract_retry_after(exc) == 60.0


def test_extract_retry_after_parses_http_date():
    # Retry-After is honored in both documented forms: numeric seconds and an
    # HTTP-date. This locks the HTTP-date branch, which had no coverage.
    when = datetime.now(timezone.utc) + timedelta(seconds=30)
    exc = _status_error(groq.RateLimitError, 429, retry_after=format_datetime(when, usegmt=True))
    value = extract_retry_after(exc)
    assert value is not None
    assert 25.0 <= value <= 60.0


def test_extract_status_code_walks_the_wrapper_chain():
    inner = _status_error(groq.RateLimitError, 429)
    wrapper = RuntimeError("wrapped")
    wrapper.__cause__ = inner
    assert extract_status_code(wrapper) == 429
    assert extract_status_code(_status_error(groq.BadRequestError, 400)) == 400
    assert extract_status_code(ValueError("plain")) is None


def test_real_instructor_wrapped_429_is_transient():
    # Reproduces the production surface exactly: instructor wraps the groq 429 in
    # InstructorRetryException, whose __cause__ is the typed RateLimitError.
    import instructor
    from pydantic import BaseModel

    def make_429(request):
        return httpx.Response(
            429,
            headers={"retry-after": "7"},
            json={"error": {"message": "Request too large"}},
            request=request,
        )

    raw = groq.Groq(
        api_key="k",
        http_client=httpx.Client(transport=httpx.MockTransport(make_429)),
        max_retries=0,
    )
    client = instructor.from_groq(raw, mode=instructor.Mode.JSON)

    class _Model(BaseModel):
        x: int = 0

    with pytest.raises(Exception) as excinfo:
        client.chat.completions.create(
            model="m", response_model=_Model, messages=[{"role": "user", "content": "hi"}]
        )

    assert type(excinfo.value).__name__ == "InstructorRetryException"
    assert is_transient_exception(excinfo.value) is True
    assert extract_retry_after(excinfo.value) == 7.0
    assert extract_status_code(excinfo.value) == 429


def test_compute_backoff_honors_retry_after():
    assert compute_backoff(0, retry_after=7) == 7.0
    assert compute_backoff(3, retry_after=7) == 7.0


def test_compute_backoff_is_bounded_exponential():
    assert compute_backoff(0) == 2.0
    assert compute_backoff(1) == 4.0
    assert compute_backoff(2) == 8.0
    assert compute_backoff(20) == 30.0


def test_retry_after_sleep_is_capped():
    assert retry_after_sleep(None) == 0.0
    assert retry_after_sleep(7) == 7.0
    assert retry_after_sleep(-3) == 0.0
    assert retry_after_sleep(9999) == RETRY_AFTER_SLEEP_CAP_SECONDS


# --- W5: the analysis retry budget has a hard cap ----------------------------

def test_analysis_attempts_hard_cap():
    assert MAX_ANALYSIS_ATTEMPTS_CAP == 10
    assert cap_analysis_attempts(1000) == 10
    assert cap_analysis_attempts(3) == 3
    assert cap_analysis_attempts(0) == 0
    assert cap_analysis_attempts(None) == 0


def test_default_max_analysis_attempts_config():
    # G4: the configured default retry budget must not drift upward.
    from core.config import settings

    assert settings.MAX_ANALYSIS_ATTEMPTS == 3


@pytest.mark.parametrize(
    "failed,attempts,max_attempts,expected",
    [
        (True, 0, 3, True),
        (True, 2, 3, True),
        (True, 3, 3, False),
        (True, 4, 3, False),
        (True, None, 3, True),
        (False, 0, 3, False),
        (None, None, 3, False),
        (True, 0, 0, False),
    ],
)
def test_should_reanalyze(failed, attempts, max_attempts, expected):
    assert should_reanalyze(failed, attempts, max_attempts) is expected


# --- AIService classification ------------------------------------------------

def _job(job_id="https://example.com/job/1"):
    return Job(
        id=job_id,
        title="Backend Engineer",
        company="Acme",
        location="Remote",
        url=job_id,
        description="Python FastAPI role.",
        is_remote=True,
    )


class _RaisingClient:
    def __init__(self, exc):
        self._exc = exc
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs):
        raise self._exc


def test_analyze_job_raises_transient_error_on_429():
    service = AIService(api_key="test-key", sleep=lambda _seconds: None)
    service.client = _RaisingClient(_status_error(groq.RateLimitError, 429, retry_after="2"))

    with pytest.raises(TransientAnalysisError) as excinfo:
        service.analyze_job(_job(), {"name": "candidate"})

    assert excinfo.value.status_code == 429
    assert excinfo.value.retry_after == 2.0


def test_analyze_job_returns_zero_audit_on_permanent_error():
    service = AIService(api_key="test-key", sleep=lambda _seconds: None)
    service.client = _RaisingClient(_status_error(groq.BadRequestError, 400))

    audit = service.analyze_job(_job(), {"name": "candidate"})

    assert audit.match_score == 0
    assert audit.is_suitable is False
    assert "Error" in audit.short_verdict


def test_analyze_job_classifies_by_final_error():
    # A transient blip followed by a permanent model error is permanent overall.
    service = AIService(api_key="test-key", sleep=lambda _seconds: None)

    class _SequenceClient:
        def __init__(self):
            self.calls = 0
            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise _status_error(groq.RateLimitError, 429)
            raise _status_error(groq.BadRequestError, 400)

    service.client = _SequenceClient()

    audit = service.analyze_job(_job(), {"name": "candidate"})
    assert audit.match_score == 0


# --- Pipeline integration ----------------------------------------------------

def _healthy_audit(score=80, english="basic"):
    return JobAudit(
        match_score=score,
        is_suitable=True,
        missing_skills=[],
        seniority_mismatch=False,
        short_verdict="Strong technical fit",
        recommended_profile="backend",
        key_requirements=["Python", "FastAPI"],
        work_mode="remote",
        english_required=english,
    )


def _persist(job):
    from database import engine

    with Session(engine) as session:
        session.add(job)
        session.commit()


def _load(job_id):
    from database import engine

    with Session(engine) as session:
        return session.get(Job, job_id)


def test_transient_429_does_not_persist_a_permanent_score(fresh_db, cycle_runner):
    job = _job()
    job_id = job.id
    calls = []

    def analyze(job_arg, cv_data):
        calls.append(job_arg.id)
        raise TransientAnalysisError("429 rate limited", status_code=429, retry_after=2.0)

    _, notifications = cycle_runner([job], analyze)

    stored = _load(job_id)
    assert stored is not None
    assert stored.analysis_failed is True
    assert stored.analysis_attempts == 1
    assert stored.ai_match_score is None
    assert stored.notified is False
    assert notifications == []
    assert calls == [job_id]


def test_transient_handler_consumes_retry_after(fresh_db, cycle_runner, caplog):
    # The pipeline must surface and act on Retry-After instead of ignoring it.
    job_id = "https://example.com/job/retry-after"

    def analyze(job_arg, cv_data):
        raise TransientAnalysisError("429 rate limited", status_code=429, retry_after=7.0)

    caplog.set_level(logging.WARNING)
    _, notifications = cycle_runner([_job(job_id)], analyze)

    stored = _load(job_id)
    assert stored.analysis_failed is True
    assert notifications == []
    assert "retry_after=7.0" in caplog.text


def test_dedup_reanalyzes_failed_row_and_skips_healthy_row(fresh_db, cycle_runner):
    failed_id = "https://example.com/job/failed"
    healthy_id = "https://example.com/job/healthy"
    _persist(
        Job(
            id=failed_id,
            title="Retry me",
            company="Acme",
            location="Remote",
            url=failed_id,
            description="Python role",
            is_remote=True,
            analysis_failed=True,
            analysis_attempts=1,
            ai_match_score=None,
        )
    )
    _persist(
        Job(
            id=healthy_id,
            title="Already scored",
            company="Acme",
            location="Remote",
            url=healthy_id,
            description="Python role",
            is_remote=True,
            analysis_failed=False,
            analysis_attempts=0,
            ai_match_score=50,
        )
    )

    # Fresh scrape objects (same URLs) — the persisted rows are expired.
    scraped = [
        Job(id=failed_id, title="Retry me", company="Acme", location="Remote",
            url=failed_id, description="Python role", is_remote=True),
        Job(id=healthy_id, title="Already scored", company="Acme", location="Remote",
            url=healthy_id, description="Python role", is_remote=True),
    ]

    analyzed = []

    def analyze(job_arg, cv_data):
        analyzed.append(job_arg.id)
        return _healthy_audit()

    _, notifications = cycle_runner(scraped, analyze)

    retried = _load(failed_id)
    assert retried.analysis_failed is False
    assert retried.ai_match_score == 80
    assert retried.analysis_attempts == 1  # preserved, not reset

    untouched = _load(healthy_id)
    assert untouched.ai_match_score == 50  # healthy row was skipped
    assert analyzed == [failed_id]
    assert [n["id"] for n in notifications] == [failed_id]


def test_attempts_stop_at_max_analysis_attempts(fresh_db, cycle_runner):
    job_id = "https://example.com/job/exhausted"
    _persist(
        Job(
            id=job_id,
            title="Almost exhausted",
            company="Acme",
            location="Remote",
            url=job_id,
            description="Python role",
            is_remote=True,
            analysis_failed=True,
            analysis_attempts=2,  # MAX_ANALYSIS_ATTEMPTS default is 3
        )
    )

    def _scraped():
        return Job(id=job_id, title="Almost exhausted", company="Acme", location="Remote",
                   url=job_id, description="Python role", is_remote=True)

    calls = []

    def analyze(job_arg, cv_data):
        calls.append(job_arg.id)
        raise TransientAnalysisError("429 rate limited", status_code=429)

    # First run: the final allowed attempt, which exhausts the budget.
    _, notifications = cycle_runner([_scraped()], analyze)

    stored = _load(job_id)
    assert stored.analysis_attempts == 3
    assert stored.analysis_failed is True
    assert stored.ai_match_score == 0
    assert notifications == []
    assert calls == [job_id]

    # Second run: exhausted rows are skipped, so no further AI call happens.
    _, notifications = cycle_runner([_scraped()], analyze)
    assert calls == [job_id]
    assert notifications == []


def test_permanent_failure_keeps_legacy_behavior(fresh_db, cycle_runner):
    job = _job("https://example.com/job/permanent")
    job_id = job.id
    calls = []

    def analyze(job_arg, cv_data):
        calls.append(job_arg.id)
        return JobAudit(
            match_score=0,
            is_suitable=False,
            missing_skills=["Error en procesamiento de IA"],
            seniority_mismatch=False,
            short_verdict="Error técnico: bad request",
            recommended_profile="backend",
            key_requirements=[],
        )

    _, notifications = cycle_runner([job], analyze)

    stored = _load(job_id)
    assert stored.ai_match_score == 0
    assert stored.analysis_failed is False
    assert notifications == []

    # A permanent failure is never retried.
    _, _ = cycle_runner([_job(job_id)], analyze)
    assert calls == [job_id]
