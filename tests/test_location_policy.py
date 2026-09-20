"""
Unit tests for the deterministic geographic eligibility policy.

These tests import only ``services.LocationPolicy`` (standard library only), so
they need no project dependencies, no network access, and no API keys.

The cases marked "production" mirror real rows from the live database.
"""

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
    # The same restricted listing is blocked while enforcement is on...
    blocked = classify_location(location="Remote - Spain")
    assert blocked.eligible is False
    assert blocked.reason == REASON_REMOTE_FOREIGN_RESTRICTED
    assert blocked.country == "Spain"
    # ...and only the explicit opt-out lets it through.
    allowed = classify_location(
        location="Remote - Spain",
        block_foreign_restricted_remote=False,
    )
    assert allowed.eligible is True
    assert allowed.reason == REASON_REMOTE_OK
    assert allowed.country == "Spain"


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

    def test_notification_gate_rejects_is_suitable_bypass(self):
        # A reintroduced is_suitable bypass would make this call legal and fail
        # the test instead of silently overriding the threshold.
        with pytest.raises(TypeError):
            is_notifiable(location_eligible=True, match_score=100, is_suitable=True)
        # The default threshold is honored, not ignored.
        assert is_notifiable(location_eligible=True, match_score=69) is False
        assert is_notifiable(location_eligible=True, match_score=70) is True
        assert is_notifiable(location_eligible=True, match_score=100, min_match_score=101) is False

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
    "text,expected_country",
    [
        ("Indianapolis", None),
        ("Ukulele", None),
        ("Leonardo", None),
        ("California", None),
        ("join us", None),
        # F2: descriptive third-party mentions must not become a country anchor.
        ("us based companies", None),
        ("located in europe, brazil, or argentina", None),
    ],
)
def test_country_words_inside_other_words_do_not_match(text, expected_country):
    verdict = classify_location(location="Remote", title=text)
    assert verdict.eligible is True
    assert verdict.reason == REASON_REMOTE_OK
    assert verdict.country == expected_country


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


# --- Final bounded correction: work mode, openness, anchors -----------------
# The cases below use the exact strings from the correction brief.

@pytest.mark.parametrize(
    "location,modality,title,description",
    [
        ("Barcelona, Spain", "onsite", "Worldwide LATAM Sales Manager", ""),
        ("Barcelona, Spain", "onsite", "On-site Sales Manager", "We are a worldwide team"),
        ("Barcelona, Spain", "onsite", "", "Remote-first culture"),
        ("Madrid, Spain", "presencial", "LATAM Manager", "worldwide company"),
        ("Madrid, Spain", "onsite", "Global Operations Lead", "We operate worldwide"),
    ],
)
def test_explicit_modality_onsite_is_not_flipped_by_openness(
    location, modality, title, description
):
    # F1: openness wording must never turn an on-site foreign listing remote.
    verdict = classify_location(
        location=location, modality=modality, title=title, description=description
    )
    assert verdict.eligible is False
    assert verdict.reason == REASON_ONSITE_FOREIGN
    assert verdict.work_mode in ("onsite", "hybrid")


@pytest.mark.parametrize(
    "openness_word",
    ["worldwide", "anywhere", "global", "international", "LATAM", "Americas"],
)
@pytest.mark.parametrize("field", ["title", "description"])
def test_openness_never_sets_work_mode(field, openness_word):
    payload = {"location": "Barcelona, Spain", "modality": "onsite", field: openness_word}
    verdict = classify_location(**payload)
    assert verdict.eligible is False
    assert verdict.reason == REASON_ONSITE_FOREIGN


def test_openness_in_title_does_not_set_work_mode_without_modality():
    # A known foreign city with no modality is still on-site, never remote.
    verdict = classify_location(location="Barcelona, Spain", title="Worldwide Sales Manager")
    assert verdict.eligible is False
    assert verdict.reason == REASON_ONSITE_FOREIGN


def test_explicit_modality_onsite_beats_is_remote_flag():
    verdict = classify_location(location="Barcelona, Spain", modality="onsite", is_remote=True)
    assert verdict.eligible is False
    assert verdict.reason == REASON_ONSITE_FOREIGN
    assert verdict.work_mode == "onsite"


def test_explicit_modality_onsite_beats_openness_wording():
    verdict = classify_location(
        location="Barcelona, Spain",
        modality="onsite",
        is_remote=True,
        title="Worldwide",
        description="Global international team",
    )
    assert verdict.eligible is False
    assert verdict.reason == REASON_ONSITE_FOREIGN
    assert verdict.work_mode == "onsite"


@pytest.mark.parametrize(
    "location,description",
    [
        ("Remote", "Must be based in the US. We are a worldwide team."),
        ("Remote", "US only. Join our international team."),
        ("Remote", "Only candidates residing in Spain. We are global."),
        ("Remote", "Candidates must be based in Mexico. We are a global company."),
        ("Remote", "Open worldwide, but you must be based in Poland."),
        ("Remote", "We are global. Must reside in Spain."),
        ("Remote", "US-based candidates only."),
        ("Remote", "Only US based candidates will be considered."),
    ],
)
def test_candidate_directed_requirements_still_block(location, description):
    verdict = classify_location(location=location, description=description)
    assert verdict.eligible is False
    assert verdict.reason == REASON_REMOTE_FOREIGN_RESTRICTED


@pytest.mark.parametrize(
    "location,title,description",
    [
        ("Remote", "us based companies", ""),
        ("Remote", "", "our clients are based in the US"),
        ("Remote", "", "our team is located in Europe"),
        ("Remote", "located in europe, brazil, or argentina", ""),
    ],
)
def test_descriptive_third_party_statements_do_not_block(location, title, description):
    # F2: descriptions about third parties are not residence requirements.
    verdict = classify_location(location=location, title=title, description=description)
    assert verdict.eligible is True
    assert verdict.reason == REASON_REMOTE_OK


def test_soft_us_preference_does_not_block():
    # "preferred" is a preference, not a candidate-directed requirement.
    verdict = classify_location(
        location="Remote - Americas", title="US-based candidates preferred"
    )
    assert verdict.eligible is True
    assert verdict.reason == REASON_REMOTE_OK


@pytest.mark.parametrize(
    "location,expected_country",
    [
        ("Europe - Remote", "European Union"),
        ("Europe, Remote", "European Union"),
        ("EMEA - Remote", "EMEA"),
        ("APAC Remote", "APAC"),
        ("Remote - Europe", "European Union"),
    ],
)
def test_region_restriction_in_either_order_blocks(location, expected_country):
    # F3: the region restriction must be recognized before or after "remote".
    verdict = classify_location(location=location)
    assert verdict.eligible is False
    assert verdict.reason == REASON_REMOTE_FOREIGN_RESTRICTED
    assert verdict.country == expected_country


@pytest.mark.parametrize(
    "location",
    ["Remote - Americas", "LATAM / Europe - Remote", "Remote - LATAM"],
)
def test_allow_regions_stay_eligible(location):
    # F3: an OR-list that includes the candidate's region stays eligible.
    verdict = classify_location(location=location)
    assert verdict.eligible is True
    assert verdict.reason == REASON_REMOTE_OK


@pytest.mark.parametrize(
    "location",
    [
        "Spain, Mar del Plata",
        "Barcelona, Mar del Plata",
        "Mar del Plata, Spain",
        "Madrid, Spain, General Pueyrredon",
    ],
)
def test_foreign_country_beats_candidate_city(location):
    # F4: a foreign country in the location must not allow an on-site job.
    verdict = classify_location(location=location, modality="onsite")
    assert verdict.eligible is False
    assert verdict.reason == REASON_ONSITE_FOREIGN
    assert verdict.country == "Spain"


@pytest.mark.parametrize(
    "location,expected_country",
    [
        ("US Remote", "United States"),
        ("Remote (US)", "United States"),
        ("Remote, US", "United States"),
        ("Remote within the US", "United States"),
        ("Remote - US", "United States"),
    ],
)
def test_us_remote_forms_are_blocked(location, expected_country):
    verdict = classify_location(location=location)
    assert verdict.eligible is False
    assert verdict.reason == REASON_REMOTE_FOREIGN_RESTRICTED
    assert verdict.country == expected_country
