"""
FIX 1: the per-country scrape must target the right Indeed domain.

``country_relevant`` was never a jobspy parameter: it was silently swallowed by
``**kwargs``, so every "search in Argentina / Chile / ..." hit the US domain.
These tests lock in ``country_indeed`` and prove the tokens resolve.
"""

import inspect

import pytest
from jobspy.model import Country

from services import JobServices


class _EmptyFrame:
    """Minimal stand-in for the empty pandas DataFrame jobspy returns."""

    empty = True


def test_scrape_jobs_declares_country_indeed_not_country_relevant():
    import jobspy

    parameters = inspect.signature(jobspy.scrape_jobs).parameters
    assert "country_indeed" in parameters
    assert "country_relevant" not in parameters


def test_scraper_passes_country_indeed_and_not_country_relevant(monkeypatch):
    captured = {}

    def fake_scrape_jobs(**kwargs):
        captured.update(kwargs)
        return _EmptyFrame()

    monkeypatch.setattr(JobServices, "scrape_jobs", fake_scrape_jobs)

    JobServices.JobService().get_latest_jobs(
        term="python developer",
        location="Argentina",
        country="argentina",
        limit=15,
    )

    assert captured["country_indeed"] == "argentina"
    assert "country_relevant" not in captured
    # Unrelated behavior must be preserved.
    assert captured["location"] == "Argentina"
    assert captured["hours_old"] == 24
    assert captured["results_wanted"] == 15


@pytest.mark.parametrize(
    "country",
    ["argentina", "spain", "mexico", "colombia", "chile", "uruguay"],
)
def test_each_target_country_reaches_the_scraper(monkeypatch, country):
    captured = {}

    def fake_scrape_jobs(**kwargs):
        captured.update(kwargs)
        return _EmptyFrame()

    monkeypatch.setattr(JobServices, "scrape_jobs", fake_scrape_jobs)

    JobServices.JobService().get_latest_jobs(country=country)

    assert captured["country_indeed"] == country
    assert "country_relevant" not in captured


@pytest.mark.parametrize(
    "token,expected",
    [
        ("argentina", Country.ARGENTINA),
        ("spain", Country.SPAIN),
        ("mexico", Country.MEXICO),
        ("colombia", Country.COLOMBIA),
        ("chile", Country.CHILE),
        ("uruguay", Country.URUGUAY),
    ],
)
def test_country_from_string_resolves_target_tokens(token, expected):
    assert Country.from_string(token) is expected
    # The resolved enum is what drives the Indeed domain and indeed-co header.
    assert Country.from_string(token).indeed_domain_value


def test_dead_kwarg_is_not_a_valid_country():
    with pytest.raises(ValueError):
        Country.from_string("country_relevant")
