"""Regression coverage for retained Referee compatibility paths."""

from __future__ import annotations

import pytest

from modules.application import _post_core_message
from modules.domain import AcceptedLocation, GeographicType, UserIntent
from modules.postgres_adapter import (
    _legacy_candidate_alias_for_canonical,
    _proposition_identity_parts,
)

SOURCE_MESSAGE_ID = "source:referee:message:1"
IDENTITY_HASH = "0123456789abcdef"

COUNTRY = AcceptedLocation(
    place_id="country:ru",
    display_name="Russia",
    geographic_type=GeographicType.COUNTRY,
    country_id="country:ru",
    city_id=None,
    verified_parent_ids=(),
    parent_display_names=(),
    iana_timezone=None,
    resolver_version="controlled-resolver-v1",
    glossary_version="location-glossary-v1",
)
CITY = AcceptedLocation(
    place_id="city:ru:saint-petersburg",
    display_name="Saint Petersburg",
    geographic_type=GeographicType.CITY,
    country_id="country:ru",
    city_id="city:ru:saint-petersburg",
    verified_parent_ids=("country:ru",),
    parent_display_names=("Russia",),
    iana_timezone="Europe/Moscow",
    resolver_version="controlled-resolver-v1",
    glossary_version="location-glossary-v1",
)


@pytest.mark.parametrize(
    "opportunity_type",
    ("referee_availability", "referee_request"),
)
@pytest.mark.parametrize("identity_format", ("candidate", "proposition"))
def test_existing_referee_identity_formats_remain_parseable(
    opportunity_type: str, identity_format: str
) -> None:
    opportunity_id = (
        f"opportunity:{SOURCE_MESSAGE_ID}:{opportunity_type}:"
        f"{identity_format}:{IDENTITY_HASH}"
    )

    assert _proposition_identity_parts(
        source_message_id=SOURCE_MESSAGE_ID,
        opportunity_id=opportunity_id,
    ) == (opportunity_type, identity_format, IDENTITY_HASH)


@pytest.mark.parametrize(
    "opportunity_type",
    ("referee_availability", "referee_request"),
)
def test_existing_referee_proposition_keeps_legacy_candidate_alias(
    opportunity_type: str,
) -> None:
    canonical_id = (
        f"opportunity:{SOURCE_MESSAGE_ID}:{opportunity_type}:proposition:"
        f"{IDENTITY_HASH}"
    )

    assert _legacy_candidate_alias_for_canonical(
        source_message_id=SOURCE_MESSAGE_ID,
        opportunity_id=canonical_id,
    ) == (
        f"opportunity:{SOURCE_MESSAGE_ID}:{opportunity_type}:candidate:{IDENTITY_HASH}"
    )


@pytest.mark.parametrize(
    ("user_intent", "details_callback"),
    (
        (UserIntent.REFEREE_SEARCH, "referee-search-details:hub"),
        (
            UserIntent.REFEREEING_SERVICE_OFFER,
            "refereeing-service-offer-details:hub",
        ),
    ),
)
def test_existing_referee_post_core_routes_remain_direction_specific(
    user_intent: UserIntent, details_callback: str
) -> None:
    message = _post_core_message(
        update_id="post-core:referee",
        telegram_user_id=49_100,
        locale="en",
        screen_revision=7,
        country=COUNTRY,
        city=CITY,
        areas=(),
        whole_city=True,
        user_intent=user_intent,
    )

    assert message.button_rows[1][0][1] == f"{details_callback}:7"
