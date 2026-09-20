"""
Pure planner for the searches a scraping cycle will run.

Keeping the plan as a value (instead of nested loops inside ``main.py``) makes
the cycle's workload auditable and unit-testable: the number and shape of the
searches can be asserted without touching the network.

The remote (Spanish-language) searches are bounded by ``max_remote_searches`` so
a large configuration can never grow the cycle without bound.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Sequence

logger = logging.getLogger(__name__)

# Hard bound on the added remote search volume per cycle.
MAX_REMOTE_SEARCHES = 12


@dataclass(frozen=True)
class ScrapeSearch:
    """A single scraper invocation in the cycle plan."""

    source: str  # "getonboard" | "jobspy"
    term: str
    location: Optional[str] = None
    country: Optional[str] = None
    is_remote: bool = False
    limit: int = 15


def parse_csv(value: Optional[str]) -> list[str]:
    """Split a comma-separated config value, dropping blanks."""
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _is_known_country_token(token: str) -> bool:
    """
    True when jobspy accepts ``token`` as a ``country_indeed`` value.

    jobspy's own ``Country`` catalog is the single source of truth for valid
    tokens, so this consults it lazily instead of maintaining a duplicate list
    that would drift. The import is guarded so the planner stays importable and
    never raises when jobspy is unavailable.
    """
    try:
        from jobspy.model import Country
    except Exception:
        # jobspy missing: keep the derived token rather than dropping the search.
        return bool(token)
    try:
        Country.from_string(token)
    except Exception:
        return False
    return True


def country_token_for_location(location: str) -> Optional[str]:
    """
    Derive the jobspy ``country_indeed`` token from a location name.

    Feeds conventionally put the country in the last comma-separated component,
    so "Buenos Aires, Argentina" resolves to "argentina" and a location that
    legitimately carries a comma still works. Returns ``None`` when the location
    is blank or names no country jobspy recognizes (for example a bare city such
    as "Buenos Aires"), so callers can skip it instead of letting jobspy raise
    ``ValueError`` mid-cycle.
    """
    if not location:
        return None
    token = location.split(",")[-1].strip().lower()
    if not token or not _is_known_country_token(token):
        return None
    return token


def build_scrape_plan(
    *,
    search_terms: Sequence[str],
    sources: Sequence[str],
    jobspy_locations: Sequence[tuple[str, str]],
    getonboard_enabled: bool,
    remote_enabled: bool,
    remote_terms: Sequence[str],
    remote_locations: Sequence[str],
    limit: int = 15,
    max_remote_searches: int = MAX_REMOTE_SEARCHES,
) -> list[ScrapeSearch]:
    """
    Build the ordered list of searches for one cycle.

    Order preserves the existing behavior: GetOnBoard first, then the
    per-country JobSpy searches, then the bounded remote JobSpy searches.
    """
    sources_lower = {source.strip().lower() for source in sources if source.strip()}
    plan: list[ScrapeSearch] = []

    if getonboard_enabled and "getonboard" in sources_lower:
        for term in search_terms:
            plan.append(ScrapeSearch(source="getonboard", term=term))

    if any(source != "getonboard" for source in sources_lower):
        for location, country in jobspy_locations:
            for term in search_terms:
                plan.append(
                    ScrapeSearch(
                        source="jobspy",
                        term=term,
                        location=location,
                        country=country,
                        limit=limit,
                    )
                )

        if remote_enabled:
            remote_searches: list[ScrapeSearch] = []
            for location in remote_locations:
                country = country_token_for_location(location)
                if country is None:
                    logger.warning(
                        "Skipping remote search location %r: it does not resolve to a "
                        "known jobspy country token.",
                        location,
                    )
                    continue
                for term in remote_terms:
                    remote_searches.append(
                        ScrapeSearch(
                            source="jobspy",
                            term=term,
                            location=location,
                            country=country,
                            is_remote=True,
                            limit=limit,
                        )
                    )
            if max_remote_searches is not None and len(remote_searches) > max_remote_searches:
                logger.warning(
                    "Remote search plan truncated from %d to %d searches (max_remote_searches).",
                    len(remote_searches),
                    max_remote_searches,
                )
                remote_searches = remote_searches[:max_remote_searches]
            plan.extend(remote_searches)

    return plan


def summarize_plan(plan: Sequence[ScrapeSearch]) -> dict[str, int]:
    """Count the plan by category for logging and auditing."""
    getonboard = sum(1 for search in plan if search.source == "getonboard")
    jobspy = sum(1 for search in plan if search.source == "jobspy" and not search.is_remote)
    remote = sum(1 for search in plan if search.is_remote)
    return {
        "getonboard": getonboard,
        "jobspy": jobspy,
        "remote": remote,
        "total": len(plan),
    }
