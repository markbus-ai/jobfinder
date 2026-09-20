"""
FIX 3: a bounded, Spanish-language remote search for LATAM.

jobspy's ``is_remote`` parameter was never used, so the cycle only ran English
terms against on-site search. These tests lock in the remote plan and prove the
flag reaches the scraper.
"""

import logging

import pytest

from services import JobServices
from services.SearchPlanner import (
    build_scrape_plan,
    country_token_for_location,
    parse_csv,
    summarize_plan,
)

DEFAULT_TERMS = [
    "python developer",
    "backend developer",
    "fastapi developer",
    "fullstack developer",
    "ai engineer",
]
DEFAULT_LOCATIONS = [
    ("Argentina", "argentina"),
    ("Spain", "spain"),
    ("Mexico", "mexico"),
    ("Colombia", "colombia"),
    ("Chile", "chile"),
    ("Uruguay", "uruguay"),
]
REMOTE_TERMS = [
    "desarrollador backend remoto",
    "desarrollador python remoto",
    "desarrollador fullstack remoto",
]
REMOTE_LOCATIONS = ["Argentina", "Uruguay", "Chile"]


class _EmptyFrame:
    empty = True


def _plan(remote_enabled=True, remote_terms=None, remote_locations=None):
    return build_scrape_plan(
        search_terms=DEFAULT_TERMS,
        sources=["getonboard", "linkedin"],
        jobspy_locations=DEFAULT_LOCATIONS,
        getonboard_enabled=True,
        remote_enabled=remote_enabled,
        remote_terms=remote_terms if remote_terms is not None else REMOTE_TERMS,
        remote_locations=remote_locations if remote_locations is not None else REMOTE_LOCATIONS,
    )


def test_remote_searches_are_issued_with_is_remote_true():
    plan = _plan()
    remote = [search for search in plan if search.is_remote]

    assert len(remote) == len(REMOTE_TERMS) * len(REMOTE_LOCATIONS)
    assert all(search.source == "jobspy" for search in remote)
    assert {(search.term, search.location) for search in remote} == {
        (term, location) for term in REMOTE_TERMS for location in REMOTE_LOCATIONS
    }
    assert all(search.country for search in remote)


@pytest.mark.parametrize(
    "location,expected",
    [
        ("Argentina", "argentina"),
        ("Uruguay", "uruguay"),
        ("Chile", "chile"),
        ("Buenos Aires, Argentina", "argentina"),
        ("Remote, Chile", "chile"),
    ],
)
def test_remote_country_token(location, expected):
    assert country_token_for_location(location) == expected


@pytest.mark.parametrize(
    "location",
    ["", "   ", "Buenos Aires", "Narnia", "Remote", "country_relevant"],
)
def test_unresolvable_remote_country_token_is_none(location):
    # A bare city or unknown name must resolve to None, never raise.
    assert country_token_for_location(location) is None


def test_unresolvable_remote_location_is_skipped_with_warning(caplog):
    caplog.set_level(logging.WARNING)
    plan = _plan(remote_locations=["Buenos Aires", "Chile"])
    remote = [search for search in plan if search.is_remote]

    assert {(search.location, search.country) for search in remote} == {("Chile", "chile")}
    assert "Buenos Aires" in caplog.text


def test_comma_separated_locations_plan_only_the_valid_entries(caplog):
    # W4 reproduction: "Buenos Aires, Argentina, Chile" splits into three entries;
    # the bare city is skipped with a warning and the valid countries are planned.
    caplog.set_level(logging.WARNING)
    locations = parse_csv("Buenos Aires, Argentina, Chile")
    assert locations == ["Buenos Aires", "Argentina", "Chile"]

    plan = _plan(remote_locations=locations)
    remote = [search for search in plan if search.is_remote]
    assert {search.country for search in remote} == {"argentina", "chile"}
    assert "Buenos Aires" in caplog.text


def test_remote_search_disabled():
    plan = _plan(remote_enabled=False)
    assert not any(search.is_remote for search in plan)
    # The existing per-country search is untouched.
    assert sum(1 for search in plan if search.source == "jobspy") == 30


def test_remote_volume_is_bounded():
    many_terms = [f"termino remoto {i}" for i in range(20)]
    plan = _plan(remote_terms=many_terms)
    remote = [search for search in plan if search.is_remote]
    # Literal on purpose: asserting the imported constant would silently pass if
    # the cap itself changed.
    assert len(remote) == 12


def test_plan_summary_counts_before_and_after():
    before = summarize_plan(_plan(remote_enabled=False))
    after = summarize_plan(_plan(remote_enabled=True))

    # Before: 5 GetOnBoard + 6 countries x 5 terms = 35 searches.
    assert before == {"getonboard": 5, "jobspy": 30, "remote": 0, "total": 35}
    # After: 9 added remote searches = 44 searches.
    assert after == {"getonboard": 5, "jobspy": 30, "remote": 9, "total": 44}


def test_jobservice_forwards_is_remote_to_scrape_jobs(monkeypatch):
    captured = {}

    def fake_scrape_jobs(**kwargs):
        captured.update(kwargs)
        return _EmptyFrame()

    monkeypatch.setattr(JobServices, "scrape_jobs", fake_scrape_jobs)

    JobServices.JobService().get_latest_jobs(
        term="desarrollador backend remoto",
        location="Argentina",
        country="argentina",
        is_remote=True,
    )

    assert captured["is_remote"] is True
    assert captured["search_term"] == "desarrollador backend remoto"
    assert captured["country_indeed"] == "argentina"
    assert captured["hours_old"] == 24


def test_cycle_issues_remote_search_with_is_remote(fresh_db, cycle_runner):
    service, _ = cycle_runner([], lambda *a, **k: None, REMOTE_SEARCH_ENABLED=True)

    remote_calls = [call for call in service.calls if call.get("is_remote")]
    assert len(remote_calls) == 3  # 1 remote term x 3 remote locations
    assert {call["term"] for call in remote_calls} == {"desarrollador backend remoto"}
    assert {call["location"] for call in remote_calls} == {"Argentina", "Uruguay", "Chile"}
    assert {call["country"] for call in remote_calls} == {"argentina", "uruguay", "chile"}


def test_cycle_skips_remote_search_when_disabled(fresh_db, cycle_runner):
    service, _ = cycle_runner([], lambda *a, **k: None, REMOTE_SEARCH_ENABLED=False)
    assert not any(call.get("is_remote") for call in service.calls)
    # The cycle runner uses one term x six countries for the per-country search.
    assert len(service.calls) == 6


def test_local_country_targets_are_literal(fresh_db, cycle_runner):
    # G1: the local jobspy targets must stay exactly these country tokens. A
    # mutation of 'argentina' to 'usa' must fail here.
    service, _ = cycle_runner([], lambda *a, **k: None)
    pairs = {(call["location"], call["country"]) for call in service.calls}
    assert pairs == {
        ("Argentina", "argentina"),
        ("Spain", "spain"),
        ("Mexico", "mexico"),
        ("Colombia", "colombia"),
        ("Chile", "chile"),
        ("Uruguay", "uruguay"),
    }


def test_default_config_terms_and_locations():
    from core.config import settings

    terms = parse_csv(settings.SEARCH_TERMS_REMOTE)
    assert "desarrollador backend remoto" in terms
    assert "desarrollador python remoto" in terms
    assert "desarrollador fullstack remoto" in terms
    assert parse_csv(settings.REMOTE_SEARCH_LOCATIONS) == ["Argentina", "Uruguay", "Chile"]
    assert settings.REMOTE_SEARCH_ENABLED is True
