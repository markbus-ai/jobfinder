"""
Unit tests for the deterministic geographic eligibility policy.

These tests import only ``services.LocationPolicy`` (standard library only), so
they need no project dependencies, no network access, and no API keys.

The cases marked "production" mirror real rows from the live database.
"""

import inspect

import pytest

from services.LocationPolicy import (
    REASON_ONSITE_CANDIDATE_CITY,
    REASON_ONSITE_FOREIGN,
    REASON_ONSITE_OTHER_ARGENTINA,
    REASON_REMOTE_DISABLED,
    REASON_REMOTE_FOREIGN_RESTRICTED,
    REASON_REMOTE_OK,
    REASON_UNKNOWN_LOCATION,
    REASON_UNKNOWN_WORK_MODE_FOREIGN,
    classify_location,
    is_notifiable,
)


@pytest.mark.parametrize(
    "location,is_remote,modality,title,expected_eligible,expected_reason",
    [
        # production: local on-site job in the candidate city
        (
            "Mar del Plata, Buenos Aires Province, Argentina",
            False,
            "onsite",
            "",
            True,
            REASON_ONSITE_CANDIDATE_CITY,
        ),
        # candidate city aliases must be accepted
        ("Mar del Plata, ARG", False, None, "", True, REASON_ONSITE_CANDIDATE_CITY),
        ("MdP", False, None, "", True, REASON_ONSITE_CANDIDATE_CITY),
        (
            "General Pueyrredón, Buenos Aires, Argentina",
            False,
            None,
            "",
            True,
            REASON_ONSITE_CANDIDATE_CITY,
        ),
        # production: foreign on-site
        (
            "Madrid, Community of Madrid, Spain",
            False,
            "onsite",
            "",
            False,
            REASON_ONSITE_FOREIGN,
        ),
        (
            "Santiago, Santiago Metropolitan Region, Chile",
            False,
            "onsite",
            "",
            False,
            REASON_ONSITE_FOREIGN,
        ),
        (
            "Montevideo, Montevideo, Uruguay",
            False,
            "onsite",
            "",
            False,
            REASON_ONSITE_FOREIGN,
        ),
        (
            "Bogotá, Capital District, Colombia",
            False,
            "onsite",
            "",
            False,
            REASON_ONSITE_FOREIGN,
        ),
        # production false positive: remote flag on a Barcelona listing
        (
            "Barcelona, Catalonia, Spain",
            True,
            None,
            "Senior/Staff - Backend Engineer - remote",
            False,
            REASON_REMOTE_FOREIGN_RESTRICTED,
        ),
        # production: other Argentine city, on-site
        (
            "Buenos Aires, Buenos Aires Province, Argentina",
            False,
            "onsite",
            "",
            False,
            REASON_ONSITE_OTHER_ARGENTINA,
        ),
        # remote is fine even from a non-candidate Argentine city
        (
            "La Plata, Buenos Aires Province, Argentina",
            True,
            None,
            "Backend Engineer - Remote",
            True,
            REASON_REMOTE_OK,
        ),
        ("Buenos Aires, Argentina", True, None, "Backend", True, REASON_REMOTE_OK),
        # plain remote without restriction
        ("Remote", False, None, "", True, REASON_REMOTE_OK),
        ("Remote - LATAM", False, None, "", True, REASON_REMOTE_OK),
        ("Remote", True, "remote", "", True, REASON_REMOTE_OK),
        # unknown location fails closed
        ("", False, None, "", False, REASON_UNKNOWN_LOCATION),
        (None, False, None, "", False, REASON_UNKNOWN_LOCATION),
        ("", False, "onsite", "", False, REASON_UNKNOWN_LOCATION),
        # foreign country but no work-mode signal
        ("Spain", False, None, "", False, REASON_UNKNOWN_WORK_MODE_FOREIGN),
        # accented and uppercase variants
        ("MÉXICO", False, "onsite", "", False, REASON_ONSITE_FOREIGN),
        ("España", False, "onsite", "", False, REASON_ONSITE_FOREIGN),
        ("MARRUECOS", False, "onsite", "", False, REASON_UNKNOWN_LOCATION),
    ],
)
def test_classify_location(location, is_remote, modality, title, expected_eligible, expected_reason):
    verdict = classify_location(
        location=location,
        is_remote=is_remote,
        modality=modality,
        title=title,
    )
    assert verdict.eligible is expected_eligible
    assert verdict.reason == expected_reason


@pytest.mark.parametrize(
    "title",
    [
        "Remote - Spain",
        "Software Engineer - Remote - Spain",
        "must reside in Spain",
        "Remote (Barcelona)",
        "Remote - USA only",
    ],
)
def test_explicit_foreign_residence_requirement_is_blocked(title):
    verdict = classify_location(location="", title=title)
    assert verdict.eligible is False
    assert verdict.reason == REASON_REMOTE_FOREIGN_RESTRICTED


def test_foreign_restriction_in_description_is_blocked():
    verdict = classify_location(
        location="Remote",
        title="Backend Engineer",
        description="Candidates must be based in Mexico to be considered.",
    )
    assert verdict.eligible is False
    assert verdict.reason == REASON_REMOTE_FOREIGN_RESTRICTED


def test_remote_disabled_blocks_remote_jobs():
    verdict = classify_location(location="Remote", allow_remote=False)
    assert verdict.eligible is False
    assert verdict.reason == REASON_REMOTE_DISABLED


def test_foreign_remotes_allowed_when_policy_disabled():
    verdict = classify_location(
        location="Remote - Spain",
        block_foreign_restricted_remote=False,
    )
    assert verdict.eligible is True
    assert verdict.reason == REASON_REMOTE_OK


def test_uncorroborated_remote_flag_on_foreign_location_is_blocked():
    # is_remote=True alone must not allow a foreign-anchored listing.
    verdict = classify_location(
        location="Madrid, Spain",
        is_remote=True,
        title="Backend Engineer",
    )
    assert verdict.eligible is False
    assert verdict.reason == REASON_REMOTE_FOREIGN_RESTRICTED


def test_verdict_exposes_structured_fields():
    verdict = classify_location(
        location="Barcelona, Catalonia, Spain",
        is_remote=True,
        title="Backend Engineer - remote",
    )
    assert verdict.work_mode == "remote"
    assert verdict.country == "Spain"
    assert verdict.city == "Barcelona"
    assert verdict.human_reason


class TestNotificationGate:
    """Regression: an ineligible location can never produce a notification."""

    def test_ineligible_never_notifies_even_with_perfect_score(self):
        assert is_notifiable(location_eligible=False, match_score=100) is False

    def test_eligible_below_threshold_does_not_notify(self):
        assert is_notifiable(location_eligible=True, match_score=69) is False

    def test_notification_gate_has_no_is_suitable_bypass(self):
        # The gate exposes exactly these parameters: reintroducing is_suitable
        # as a bypass would change the signature and fail this assertion.
        params = list(inspect.signature(is_notifiable).parameters)
        assert params == ["location_eligible", "match_score", "min_match_score"]
        # The threshold is honored, not silently ignored.
        assert is_notifiable(location_eligible=True, match_score=69, min_match_score=70) is False
        assert is_notifiable(location_eligible=True, match_score=70, min_match_score=70) is True

    def test_custom_threshold(self):
        assert is_notifiable(location_eligible=True, match_score=60, min_match_score=60) is True
        assert is_notifiable(location_eligible=False, match_score=60, min_match_score=60) is False


# --- Bounded correction regressions ----------------------------------------
# The cases below use the exact strings from the correction brief.

@pytest.mark.parametrize(
    "location,title",
    [
        (
            "Montevideo, Montevideo, Uruguay",
            "Senior MLOps Engineer - Remote - Latin America",
        ),
        (
            "Concepcion, Biobío Region, Chile",
            "Software Engineer (Angular + SEO/Marketing) - Remote - Latin America",
        ),
    ],
)
def test_latam_openness_overrides_foreign_anchor(location, title):
    # Explicit openness to Latin America beats a foreign location anchor.
    verdict = classify_location(location=location, title=title)
    assert verdict.eligible is True
    assert verdict.reason == REASON_REMOTE_OK
    assert verdict.work_mode == "remote"


@pytest.mark.parametrize(
    "description",
    [
        "Must be based in the US. We are a worldwide team.",
        "US only. Join our international team.",
        "Only candidates residing in Spain. We are global.",
        "Candidates must be based in Mexico. We are a global company.",
    ],
)
def test_explicit_restriction_wins_over_openness_keyword(description):
    verdict = classify_location(location="Remote", description=description)
    assert verdict.eligible is False
    assert verdict.reason == REASON_REMOTE_FOREIGN_RESTRICTED


@pytest.mark.parametrize(
    "location,expected_country",
    [
        ("Remote (US)", "United States"),
        ("US Remote", "United States"),
        ("Remote, US", "United States"),
        ("Remote within the US", "United States"),
        ("Remote (EU)", "European Union"),
        ("Remote (Europe)", "European Union"),
    ],
)
def test_us_and_eu_surface_forms_are_blocked(location, expected_country):
    verdict = classify_location(location=location)
    assert verdict.eligible is False
    assert verdict.reason == REASON_REMOTE_FOREIGN_RESTRICTED
    assert verdict.country == expected_country


def test_americas_anchor_is_eligible():
    # "Americas" includes Argentina, so it must not be blanket-blocked.
    verdict = classify_location(location="Remote (Americas)")
    assert verdict.eligible is True
    assert verdict.reason == REASON_REMOTE_OK


@pytest.mark.parametrize("location", ["Anywhere", "Worldwide", "Work from anywhere"])
def test_anywhere_remote_keywords_are_eligible(location):
    verdict = classify_location(location=location)
    assert verdict.eligible is True
    assert verdict.reason == REASON_REMOTE_OK
    assert verdict.work_mode == "remote"


def test_villa_argentina_place_name_is_not_argentina():
    verdict = classify_location(location="Villa Argentina, Canelones, Uruguay")
    assert verdict.eligible is False
    assert verdict.reason == REASON_ONSITE_FOREIGN
    assert verdict.country == "Uruguay"


def test_toluca_remote_is_blocked_as_foreign():
    verdict = classify_location(location="", title="AI Developer (Remote, Toluca)")
    assert verdict.eligible is False
    assert verdict.reason == REASON_REMOTE_FOREIGN_RESTRICTED
    assert verdict.country == "Mexico"


@pytest.mark.parametrize(
    "text,forbidden_country",
    [
        ("Indianapolis", "United States"),
        ("Ukulele", "United Kingdom"),
        ("Leonardo", "Mexico"),
        ("California", "United States"),
        ("join us", "United States"),
    ],
)
def test_country_words_inside_other_words_do_not_match(text, forbidden_country):
    verdict = classify_location(location="Remote", title=text)
    assert verdict.eligible is True
    assert verdict.reason == REASON_REMOTE_OK
    assert verdict.country != forbidden_country


def test_argentina_city_detection_is_functional():
    # Buenos Aires alone must be recognized as an Argentine city, not unknown.
    verdict = classify_location(location="Buenos Aires")
    assert verdict.eligible is False
    assert verdict.reason == REASON_ONSITE_OTHER_ARGENTINA


def test_remote_flag_alone_on_empty_location_is_accepted():
    verdict = classify_location(location="", is_remote=True)
    assert verdict.eligible is True
    assert verdict.reason == REASON_REMOTE_OK
    assert verdict.work_mode == "remote"
