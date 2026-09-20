"""
Failure classification and retry bookkeeping for the AI analysis step.

The Groq client raises typed exceptions (``groq.RateLimitError``,
``groq.APIConnectionError``, ``groq.APITimeoutError``,
``groq.InternalServerError``), but ``instructor`` wraps them in its own
``InstructorRetryException``. The original typed error is still reachable
through the exception chain (``__cause__`` / ``__context__``), so this module
classifies failures by walking that chain and inspecting the structured
``status_code`` and exception type instead of substring-matching the message.

This module is intentionally dependency-light: it only needs the standard
library, and imports ``groq`` lazily so it stays importable when ``groq`` is not
installed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Iterator, Optional

logger = logging.getLogger(__name__)

# Bounded backoff so a missing or hostile header can never stall a cycle.
DEFAULT_BACKOFF_SECONDS = 2.0
MAX_BACKOFF_SECONDS = 30.0
MAX_RETRY_AFTER_SECONDS = 60.0

# HTTP status codes that are worth retrying: request timeout, too early, and
# rate limiting. Every 5xx is transient as well.
_TRANSIENT_STATUS_CODES = frozenset({408, 425, 429})


class TransientAnalysisError(RuntimeError):
    """
    Raised when job analysis failed for a retryable (transient) reason.

    A transient failure must NOT be persisted as a permanent 0/100 score. The
    caller is expected to persist the row with ``analysis_failed=True`` and an
    incremented ``analysis_attempts`` so a later cycle can retry it.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        retry_after: Optional[float] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


def exception_chain(exc: BaseException) -> Iterator[BaseException]:
    """Yield an exception and every cause/context reachable from it, once each."""
    seen: set[int] = set()
    current: Optional[BaseException] = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _transient_types() -> tuple[type, ...]:
    """Typed Groq exceptions that always mean a transient failure."""
    try:
        import groq
    except ImportError:  # pragma: no cover - groq is a production dependency
        return ()
    candidates = (
        getattr(groq, "RateLimitError", None),
        getattr(groq, "APIConnectionError", None),
        getattr(groq, "APITimeoutError", None),
        getattr(groq, "InternalServerError", None),
    )
    return tuple(cls for cls in candidates if isinstance(cls, type))


def _is_transient(exc: BaseException) -> bool:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and (status in _TRANSIENT_STATUS_CODES or status >= 500):
        return True
    return isinstance(exc, _transient_types())


def is_transient_exception(exc: BaseException) -> bool:
    """True when the exception (or any wrapped cause) is a retryable failure."""
    return any(_is_transient(item) for item in exception_chain(exc))


def _parse_retry_after(raw: object) -> Optional[float]:
    """Parse a ``Retry-After`` header value (seconds or HTTP date) to seconds."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max((when - datetime.now(timezone.utc)).total_seconds(), 0.0)


def extract_retry_after(exc: BaseException) -> Optional[float]:
    """
    Return the ``Retry-After`` value advertised by the API, clamped to a bound.

    Returns ``None`` when no header is present. The value is capped at
    ``MAX_RETRY_AFTER_SECONDS`` so an unreasonable header cannot freeze a cycle.
    """
    for item in exception_chain(exc):
        response = getattr(item, "response", None)
        headers = getattr(response, "headers", None)
        if headers is None:
            continue
        raw = headers.get("retry-after") or headers.get("Retry-After")
        value = _parse_retry_after(raw)
        if value is not None:
            return min(value, MAX_RETRY_AFTER_SECONDS)
    return None


def extract_status_code(exc: BaseException) -> Optional[int]:
    """Return the first integer ``status_code`` found in the exception chain."""
    for item in exception_chain(exc):
        status = getattr(item, "status_code", None)
        if isinstance(status, int):
            return status
    return None


def compute_backoff(attempt: int, retry_after: Optional[float] = None) -> float:
    """
    Bounded delay before the next key rotation.

    Honors ``Retry-After`` when the API provides it; otherwise falls back to
    capped exponential backoff (2s, 4s, 8s, ... up to 30s).
    """
    if retry_after is not None:
        return min(max(retry_after, 0.0), MAX_RETRY_AFTER_SECONDS)
    return min(DEFAULT_BACKOFF_SECONDS * (2 ** max(attempt, 0)), MAX_BACKOFF_SECONDS)


def should_reanalyze(
    analysis_failed: Optional[bool],
    analysis_attempts: Optional[int],
    max_attempts: int,
) -> bool:
    """
    Pure dedup predicate: may this already-persisted row be analyzed again?

    A row is retryable only when it failed transiently AND still has attempts
    left. Healthy rows (never failed) and rows that exhausted their attempts are
    skipped, which preserves the original dedup behavior for them.
    """
    if not analysis_failed:
        return False
    if max_attempts is None or max_attempts <= 0:
        return False
    return (analysis_attempts or 0) < max_attempts
