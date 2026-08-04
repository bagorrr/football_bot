"""Resolver-backed Search Area behavior at the approved system seam."""

# ruff: noqa: RUF001 -- reviewed multilingual interface copy is intentional.

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from modules.contracts import RuntimeRole
from modules.domain import (
    ConversationStage,
    GeographicType,
    LocationCandidate,
    LocationInterpretation,
    LocationResolution,
)
from modules.testkit import (
    ControlledLocationResolverAdapter,
    ControlledTelegramDeliveryAdapter,
    FrozenClock,
    InjectedTelegramDeliveryError,
    boot_acceptance_spine,
)


class _AdjustableClock:
    def __init__(self, instant: datetime) -> None:
        self.instant = instant

    def now(self) -> datetime:
        return self.instant

    def advance(self, delta: timedelta) -> None:
        self.instant += delta


def test_unique_validated_country_from_natural_language_advances_to_city() -> None:
    telegram_delivery = ControlledTelegramDeliveryAdapter()
    resolver = ControlledLocationResolverAdapter()
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 5, 12, 0, tzinfo=UTC)),
        telegram_delivery=telegram_delivery,
        location_resolver=resolver,
    )
    system.reset()
    user_id = 42_001
    system.start_bot_user(
        update_id="start-country-resolution",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="select-country-language",
        telegram_user_id=user_id,
        locale="en",
    )
    system.select_direction(
        update_id="select-country-intent",
        telegram_user_id=user_id,
        direction="game_search",
    )

    system.submit_location_text(
        update_id="resolve-country",
        telegram_user_id=user_id,
        text="I want to play in Russia",
    )

    draft = system.discovery_draft(user_id)
    assert draft.stage == "city"
    assert draft.country is not None
    assert draft.country.place_id == "country:ru"
    assert draft.country.geographic_type == "country"
    assert draft.country.country_id == "country:ru"
    assert draft.city is None
    assert telegram_delivery.messages[-1].text == (
        "✅ Search country: **Russia**.\n\n🏙 In which city should we search?"
    )


def test_unique_city_preserves_verified_country_parent_and_iana_timezone() -> None:
    telegram_delivery = ControlledTelegramDeliveryAdapter()
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 5, 12, 0, tzinfo=UTC)),
        telegram_delivery=telegram_delivery,
        location_resolver=ControlledLocationResolverAdapter(),
    )
    system.reset()
    user_id = 42_002
    system.start_bot_user(
        update_id="start-city-resolution",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="select-city-language",
        telegram_user_id=user_id,
        locale="en",
    )
    system.select_direction(
        update_id="select-city-intent",
        telegram_user_id=user_id,
        direction="game_search",
    )
    system.submit_location_text(
        update_id="resolve-country-before-city",
        telegram_user_id=user_id,
        text="Russia",
    )

    system.submit_location_text(
        update_id="resolve-city",
        telegram_user_id=user_id,
        text="Let's search in Saint Petersburg",
    )

    draft = system.discovery_draft(user_id)
    assert draft.stage == "search_area"
    assert draft.city is not None
    assert draft.city.place_id == "city:ru:saint-petersburg"
    assert draft.city.geographic_type == "city"
    assert draft.city.country_id == "country:ru"
    assert draft.city.city_id == "city:ru:saint-petersburg"
    assert draft.city.verified_parent_ids == ("country:ru",)
    assert draft.city.iana_timezone == "Europe/Moscow"
    assert "Selected city: Saint Petersburg." in telegram_delivery.messages[-1].text
    assert "type one or several districts" in telegram_delivery.messages[-1].text


def test_ambiguous_country_is_distinguished_and_left_unconfirmed() -> None:
    telegram_delivery = ControlledTelegramDeliveryAdapter()
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 5, 12, 0, tzinfo=UTC)),
        telegram_delivery=telegram_delivery,
        location_resolver=ControlledLocationResolverAdapter(),
    )
    system.reset()
    user_id = 42_003
    system.start_bot_user(
        update_id="start-ambiguous-country",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="select-ambiguous-country-language",
        telegram_user_id=user_id,
        locale="en",
    )
    system.select_direction(
        update_id="select-ambiguous-country-intent",
        telegram_user_id=user_id,
        direction="game_search",
    )

    system.submit_location_text(
        update_id="resolve-ambiguous-country",
        telegram_user_id=user_id,
        text="Georgia",
    )

    draft = system.discovery_draft(user_id)
    assert draft.stage == "country"
    assert draft.country is None
    assert telegram_delivery.messages[-1].text == (
        "I found several countries: Georgia and South Georgia and the South "
        "Sandwich Islands. Type the country more precisely."
    )


def test_natural_language_whole_city_scope_completes_the_search_area() -> None:
    telegram_delivery = ControlledTelegramDeliveryAdapter()
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 5, 12, 0, tzinfo=UTC)),
        telegram_delivery=telegram_delivery,
        location_resolver=ControlledLocationResolverAdapter(),
    )
    system.reset()
    user_id = 42_004
    system.start_bot_user(
        update_id="start-whole-city",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="select-whole-city-language",
        telegram_user_id=user_id,
        locale="en",
    )
    system.select_direction(
        update_id="select-whole-city-intent",
        telegram_user_id=user_id,
        direction="game_search",
    )
    system.submit_location_text(
        update_id="resolve-whole-city-country",
        telegram_user_id=user_id,
        text="Russia",
    )
    system.submit_location_text(
        update_id="resolve-whole-city-city",
        telegram_user_id=user_id,
        text="Saint Petersburg",
    )

    system.submit_location_text(
        update_id="resolve-whole-city-scope",
        telegram_user_id=user_id,
        text="Anywhere in the whole city works",
    )

    draft = system.discovery_draft(user_id)
    assert draft.stage == "required_date"
    assert draft.whole_city is True
    assert draft.sub_city_areas == ()
    assert draft.city is not None
    assert draft.city.iana_timezone == "Europe/Moscow"
    assert telegram_delivery.messages[-1].text == (
        "✅ Search area: **Russia → Saint Petersburg → whole city**.\n\n"
        "📅 When?\n\nType a date or range in your own words."
    )


def test_one_answer_accepts_several_typed_areas_with_verified_hierarchy() -> None:
    telegram_delivery = ControlledTelegramDeliveryAdapter()
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 5, 12, 0, tzinfo=UTC)),
        telegram_delivery=telegram_delivery,
        location_resolver=ControlledLocationResolverAdapter(),
    )
    system.reset()
    user_id = 42_005
    system.start_bot_user(
        update_id="start-typed-areas",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="select-typed-areas-language",
        telegram_user_id=user_id,
        locale="en",
    )
    system.select_direction(
        update_id="open-typed-areas-transfer",
        telegram_user_id=user_id,
        direction="transfer_search",
    )
    system.select_direction(
        update_id="select-typed-areas-intent",
        telegram_user_id=user_id,
        direction="new_team_search",
    )
    system.submit_location_text(
        update_id="resolve-typed-areas-country",
        telegram_user_id=user_id,
        text="Russia",
    )
    system.submit_location_text(
        update_id="resolve-typed-areas-city",
        telegram_user_id=user_id,
        text="Saint Petersburg",
    )

    system.submit_location_text(
        update_id="resolve-typed-areas-scope",
        telegram_user_id=user_id,
        text="Near Komendantsky metro and in Primorsky District",
    )

    draft = system.discovery_draft(user_id)
    assert draft.stage == "post_core"
    assert draft.whole_city is False
    assert [area.place_id for area in draft.sub_city_areas] == [
        "station:ru:spb:komendantsky-prospekt",
        "district:ru:spb:primorsky",
    ]
    station, district = draft.sub_city_areas
    assert station.geographic_type == "station"
    assert station.verified_parent_ids == (
        "district:ru:spb:primorsky",
        "city:ru:saint-petersburg",
        "country:ru",
    )
    assert district.geographic_type == "administrative_district"
    assert district.verified_parent_ids == (
        "city:ru:saint-petersburg",
        "country:ru",
    )
    assert all(
        area.resolver_version == "controlled-resolver-v1"
        for area in (station, district)
    )
    assert all(
        area.glossary_version == "controlled-glossary-v1"
        for area in (station, district)
    )
    assert (
        "Komendantsky Prospekt, Primorsky District"
        in telegram_delivery.messages[-1].text
    )


def test_same_intent_country_and_city_history_is_only_an_unconfirmed_shortcut() -> None:
    clock = _AdjustableClock(datetime(2026, 8, 5, 12, 0, tzinfo=UTC))
    telegram_delivery = ControlledTelegramDeliveryAdapter()
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_delivery=telegram_delivery,
        location_resolver=ControlledLocationResolverAdapter(),
    )
    system.reset()
    user_id = 42_006
    system.start_bot_user(
        update_id="start-before-suggestion-history",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language-before-suggestion-history",
        telegram_user_id=user_id,
        locale="en",
    )
    system.select_direction(
        update_id="intent-before-suggestion-history",
        telegram_user_id=user_id,
        direction="game_search",
    )
    system.submit_location_text(
        update_id="country-before-suggestion-history",
        telegram_user_id=user_id,
        text="Russia",
    )
    system.submit_location_text(
        update_id="city-before-suggestion-history",
        telegram_user_id=user_id,
        text="Saint Petersburg",
    )
    other_user_id = 42_066
    system.start_bot_user(
        update_id="start-other-suggestion-owner",
        telegram_user_id=other_user_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language-other-suggestion-owner",
        telegram_user_id=other_user_id,
        locale="en",
    )
    system.select_direction(
        update_id="intent-other-suggestion-owner",
        telegram_user_id=other_user_id,
        direction="game_search",
    )
    assert all(
        label != "Russia"
        for row in telegram_delivery.messages[-1].button_rows
        for label, _ in row
    )
    clock.advance(timedelta(days=30))
    assert system.expire_inactive_discovery_drafts() == 2
    system.start_bot_user(
        update_id="start-suggestion-flow",
        telegram_user_id=user_id,
        telegram_language_hint="fr",
    )
    system.select_direction(
        update_id="different-intent-has-no-suggestion",
        telegram_user_id=user_id,
        direction="player_search",
    )
    assert all(
        label != "Russia"
        for row in telegram_delivery.messages[-1].button_rows
        for label, _ in row
    )
    system.go_back(
        update_id="back-before-same-intent-suggestion",
        telegram_user_id=user_id,
    )
    system.select_direction(
        update_id="same-intent-has-suggestion",
        telegram_user_id=user_id,
        direction="game_search",
    )

    unconfirmed_country = system.discovery_draft(user_id)
    assert unconfirmed_country.country is None
    assert (
        "Russia",
        f"location-suggestion:country:country:ru:{unconfirmed_country.screen_revision}",
    ) in telegram_delivery.messages[-1].button_rows[0]

    offered_revision = unconfirmed_country.screen_revision
    system.dismiss_location_suggestion(
        update_id="choose-another-country",
        telegram_user_id=user_id,
        kind="country",
    )
    free_text_country = system.discovery_draft(user_id)
    assert free_text_country.country is None
    assert all(
        label != "Russia"
        for row in telegram_delivery.messages[-1].button_rows
        for label, _ in row
    )
    system.select_location_suggestion(
        update_id="stale-country-suggestion",
        telegram_user_id=user_id,
        kind="country",
        place_id="country:ru",
        screen_revision=offered_revision,
    )
    assert system.discovery_draft(user_id) == free_text_country
    system.start_bot_user(
        update_id="resume-country-suggestion",
        telegram_user_id=user_id,
        telegram_language_hint="ru",
    )

    system.select_location_suggestion(
        update_id="accept-country-suggestion",
        telegram_user_id=user_id,
        kind="country",
        place_id="country:ru",
    )
    system.restart(RuntimeRole.BOT_ASSISTANT)
    system.start_bot_user(
        update_id="resume-before-city-suggestion",
        telegram_user_id=user_id,
        telegram_language_hint="es",
    )

    unconfirmed_city = system.discovery_draft(user_id)
    assert unconfirmed_city.country is not None
    assert unconfirmed_city.city is None
    assert (
        "Saint Petersburg",
        "location-suggestion:city:city:ru:saint-petersburg:"
        f"{unconfirmed_city.screen_revision}",
    ) in telegram_delivery.messages[-1].button_rows[0]


def test_city_resolution_outcomes_are_distinct_and_preserve_confirmed_country() -> None:
    telegram_delivery = ControlledTelegramDeliveryAdapter()
    resolver = ControlledLocationResolverAdapter()
    invalid_city = LocationCandidate(
        place_id="city:us:saint-petersburg",
        display_name="Saint Petersburg, Florida",
        geographic_type=GeographicType.CITY,
        country_id="country:us",
        city_id="city:us:saint-petersburg",
        verified_parent_ids=("country:us",),
        parent_display_names=("United States",),
        iana_timezone="America/New_York",
        resolver_version="controlled-resolver-v1",
        glossary_version="controlled-glossary-v1",
    )
    alternate_city = LocationCandidate(
        place_id="city:ru:saint-petersburg-leningrad",
        display_name="Saint Petersburg",
        geographic_type=GeographicType.CITY,
        country_id="country:ru",
        city_id="city:ru:saint-petersburg-leningrad",
        verified_parent_ids=("region:ru:leningrad", "country:ru"),
        parent_display_names=("Leningrad Oblast", "Russia"),
        iana_timezone="Europe/Moscow",
        resolver_version="controlled-resolver-v1",
        glossary_version="controlled-glossary-v1",
    )
    ambiguous_city = LocationResolution(
        interpretations=(
            LocationInterpretation(
                places=(alternate_city,), glossary_version="controlled-glossary-v1"
            ),
            LocationInterpretation(
                glossary_version="controlled-glossary-v1",
                places=(
                    LocationCandidate(
                        place_id="city:ru:saint-petersburg",
                        display_name="Saint Petersburg",
                        geographic_type=GeographicType.CITY,
                        country_id="country:ru",
                        city_id="city:ru:saint-petersburg",
                        verified_parent_ids=("country:ru",),
                        parent_display_names=("Russia",),
                        iana_timezone="Europe/Moscow",
                        resolver_version="controlled-resolver-v1",
                        glossary_version="controlled-glossary-v1",
                    ),
                ),
            ),
        )
    )
    resolver.return_for(
        stage=ConversationStage.CITY,
        text="the wrong parent",
        resolution=LocationResolution(
            interpretations=(
                LocationInterpretation(
                    places=(invalid_city,),
                    glossary_version="controlled-glossary-v1",
                ),
            )
        ),
    )
    resolver.return_for(
        stage=ConversationStage.CITY,
        text="Saint Petersburg maybe",
        resolution=ambiguous_city,
    )
    resolver.fail_for(stage=ConversationStage.CITY, text="resolver unavailable")
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 5, 12, 0, tzinfo=UTC)),
        telegram_delivery=telegram_delivery,
        location_resolver=resolver,
    )
    system.reset()
    user_id = 42_007
    system.start_bot_user(
        update_id="start-resolution-outcomes",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language-resolution-outcomes",
        telegram_user_id=user_id,
        locale="en",
    )
    system.select_direction(
        update_id="intent-resolution-outcomes",
        telegram_user_id=user_id,
        direction="game_search",
    )
    system.submit_location_text(
        update_id="country-resolution-outcomes",
        telegram_user_id=user_id,
        text="Russia",
    )

    expected_copy = {
        "unknown city": "I couldn't find that city. Type another city.",
        "the wrong parent": (
            "That result is not a valid city in Russia. Type another city."
        ),
        "Saint Petersburg maybe": (
            "I found several matching cities: Saint Petersburg (Leningrad Oblast "
            "→ Russia) and Saint Petersburg (Russia). Type the city more precisely."
        ),
        "resolver unavailable": (
            "Location search is temporarily unavailable. Your confirmed "
            "country is unchanged; please try again."
        ),
    }
    for index, (text, expected_message) in enumerate(expected_copy.items()):
        system.submit_location_text(
            update_id=f"city-resolution-outcome-{index}",
            telegram_user_id=user_id,
            text=text,
        )
        draft = system.discovery_draft(user_id)
        assert draft.stage == "city"
        assert draft.country is not None
        assert draft.country.place_id == "country:ru"
        assert draft.city is None
        assert telegram_delivery.messages[-1].text == expected_message


def test_back_preserves_search_area_and_stale_callbacks_are_inert() -> None:
    telegram_delivery = ControlledTelegramDeliveryAdapter()
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 5, 12, 0, tzinfo=UTC)),
        telegram_delivery=telegram_delivery,
        location_resolver=ControlledLocationResolverAdapter(),
    )
    system.reset()
    user_id = 42_008
    system.start_bot_user(
        update_id="start-search-area-back",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language-search-area-back",
        telegram_user_id=user_id,
        locale="en",
    )
    system.select_direction(
        update_id="intent-search-area-back",
        telegram_user_id=user_id,
        direction="game_search",
    )
    system.submit_location_text(
        update_id="country-search-area-back",
        telegram_user_id=user_id,
        text="Russia",
    )
    system.submit_location_text(
        update_id="city-search-area-back",
        telegram_user_id=user_id,
        text="Saint Petersburg",
    )
    stale_search_area_revision = system.discovery_draft(user_id).screen_revision
    system.submit_location_text(
        update_id="scope-search-area-back",
        telegram_user_id=user_id,
        text="the whole city",
    )

    system.go_back(
        update_id="back-to-search-area",
        telegram_user_id=user_id,
    )
    at_search_area = system.discovery_draft(user_id)
    assert at_search_area.stage == "search_area"
    assert at_search_area.whole_city is True
    assert at_search_area.city is not None
    assert at_search_area.country is not None

    system.submit_location_text(
        update_id="stale-search-area-answer",
        telegram_user_id=user_id,
        text="Near Komendantsky metro and in Primorsky District",
        screen_revision=stale_search_area_revision,
    )
    after_stale = system.discovery_draft(user_id)
    assert after_stale == at_search_area

    system.go_back(update_id="back-to-city", telegram_user_id=user_id)
    at_city = system.discovery_draft(user_id)
    assert at_city.stage == "city"
    assert at_city.country == at_search_area.country
    assert at_city.city == at_search_area.city
    assert at_city.whole_city is True
    assert all(
        label != "Saint Petersburg"
        for row in telegram_delivery.messages[-1].button_rows
        for label, _ in row
    )

    system.go_back(update_id="back-to-country", telegram_user_id=user_id)
    at_country = system.discovery_draft(user_id)
    assert at_country.stage == "country"
    assert at_country.country == at_search_area.country
    assert at_country.city == at_search_area.city
    assert at_country.whole_city is True
    assert all(
        label != "Russia"
        for row in telegram_delivery.messages[-1].button_rows
        for label, _ in row
    )


def test_country_rejection_and_resolver_failure_preserve_prior_confirmed_values() -> (
    None
):
    telegram_delivery = ControlledTelegramDeliveryAdapter()
    resolver = ControlledLocationResolverAdapter()
    resolver.return_for(
        stage=ConversationStage.COUNTRY,
        text="not a country",
        resolution=LocationResolution(
            interpretations=(
                LocationInterpretation(
                    glossary_version="controlled-glossary-v1",
                    places=(
                        LocationCandidate(
                            place_id="city:ru:moscow",
                            display_name="Moscow",
                            geographic_type=GeographicType.CITY,
                            country_id="country:ru",
                            city_id="city:ru:moscow",
                            verified_parent_ids=("country:ru",),
                            parent_display_names=("Russia",),
                            iana_timezone="Europe/Moscow",
                            resolver_version="controlled-resolver-v1",
                            glossary_version="controlled-glossary-v1",
                        ),
                    ),
                ),
            )
        ),
    )
    resolver.fail_for(stage=ConversationStage.COUNTRY, text="resolver unavailable")
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 5, 12, 0, tzinfo=UTC)),
        telegram_delivery=telegram_delivery,
        location_resolver=resolver,
    )
    system.reset()
    user_id = 42_009
    system.start_bot_user(
        update_id="start-country-preservation",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language-country-preservation",
        telegram_user_id=user_id,
        locale="en",
    )
    system.select_direction(
        update_id="intent-country-preservation",
        telegram_user_id=user_id,
        direction="game_search",
    )
    system.submit_location_text(
        update_id="country-before-country-preservation",
        telegram_user_id=user_id,
        text="Russia",
    )
    system.submit_location_text(
        update_id="city-before-country-preservation",
        telegram_user_id=user_id,
        text="Saint Petersburg",
    )
    system.submit_location_text(
        update_id="area-before-country-preservation",
        telegram_user_id=user_id,
        text="whole city",
    )
    system.go_back(update_id="country-preservation-back-area", telegram_user_id=user_id)
    system.go_back(update_id="country-preservation-back-city", telegram_user_id=user_id)
    system.go_back(
        update_id="country-preservation-back-country", telegram_user_id=user_id
    )
    confirmed = system.discovery_draft(user_id)

    expected_copy = {
        "unknown country": "I couldn't find that country. Type another country.",
        "not a country": ("That result is not a valid country. Type another country."),
        "Georgia": (
            "I found several countries: Georgia and South Georgia and the South "
            "Sandwich Islands. Type the country more precisely."
        ),
        "resolver unavailable": (
            "Location search is temporarily unavailable. Your confirmed location "
            "is unchanged; please try again."
        ),
    }
    for index, (text, expected_message) in enumerate(expected_copy.items()):
        system.submit_location_text(
            update_id=f"country-preservation-outcome-{index}",
            telegram_user_id=user_id,
            text=text,
        )
        assert system.discovery_draft(user_id) == confirmed
        assert telegram_delivery.messages[-1].text == expected_message


def test_search_area_outcomes_are_distinct_and_preserve_confirmed_scope() -> None:
    telegram_delivery = ControlledTelegramDeliveryAdapter()
    resolver = ControlledLocationResolverAdapter()
    wrong_city_area = LocationCandidate(
        place_id="district:ru:moscow:central",
        display_name="Central District",
        geographic_type=GeographicType.ADMINISTRATIVE_DISTRICT,
        country_id="country:ru",
        city_id="city:ru:moscow",
        verified_parent_ids=("city:ru:moscow", "country:ru"),
        parent_display_names=("Moscow", "Russia"),
        iana_timezone=None,
        resolver_version="controlled-resolver-v1",
        glossary_version="controlled-glossary-v1",
    )
    valid_area = LocationCandidate(
        place_id="district:ru:spb:primorsky",
        display_name="Primorsky District",
        geographic_type=GeographicType.ADMINISTRATIVE_DISTRICT,
        country_id="country:ru",
        city_id="city:ru:saint-petersburg",
        verified_parent_ids=("city:ru:saint-petersburg", "country:ru"),
        parent_display_names=("Saint Petersburg", "Russia"),
        iana_timezone=None,
        resolver_version="controlled-resolver-v1",
        glossary_version="controlled-glossary-v1",
    )
    alternate_valid_area = LocationCandidate(
        place_id="neighborhood:ru:spb:central",
        display_name="Central Neighborhood",
        geographic_type=GeographicType.NEIGHBORHOOD,
        country_id="country:ru",
        city_id="city:ru:saint-petersburg",
        verified_parent_ids=("city:ru:saint-petersburg", "country:ru"),
        parent_display_names=("Saint Petersburg", "Russia"),
        iana_timezone=None,
        resolver_version="controlled-resolver-v1",
        glossary_version="controlled-glossary-v1",
    )
    resolver.return_for(
        stage=ConversationStage.SEARCH_AREA,
        text="outside the city",
        resolution=LocationResolution(
            interpretations=(
                LocationInterpretation(
                    places=(wrong_city_area,),
                    glossary_version="controlled-glossary-v1",
                ),
            )
        ),
    )
    resolver.return_for(
        stage=ConversationStage.SEARCH_AREA,
        text="somewhere central",
        resolution=LocationResolution(
            interpretations=(
                LocationInterpretation(
                    places=(valid_area,),
                    glossary_version="controlled-glossary-v1",
                ),
                LocationInterpretation(
                    places=(alternate_valid_area,),
                    glossary_version="controlled-glossary-v1",
                ),
            )
        ),
    )
    resolver.fail_for(stage=ConversationStage.SEARCH_AREA, text="resolver unavailable")
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 5, 12, 0, tzinfo=UTC)),
        telegram_delivery=telegram_delivery,
        location_resolver=resolver,
    )
    system.reset()
    user_id = 42_010
    system.start_bot_user(
        update_id="start-area-preservation",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language-area-preservation",
        telegram_user_id=user_id,
        locale="en",
    )
    system.select_direction(
        update_id="intent-area-preservation",
        telegram_user_id=user_id,
        direction="game_search",
    )
    system.submit_location_text(
        update_id="country-area-preservation",
        telegram_user_id=user_id,
        text="Russia",
    )
    system.submit_location_text(
        update_id="city-area-preservation",
        telegram_user_id=user_id,
        text="Saint Petersburg",
    )
    system.submit_location_text(
        update_id="confirmed-area-preservation",
        telegram_user_id=user_id,
        text="whole city",
    )
    system.go_back(update_id="back-area-preservation", telegram_user_id=user_id)
    confirmed = system.discovery_draft(user_id)

    expected_copy = {
        "unknown scope": (
            "I couldn't identify that Search Area. Type one or several places, "
            "or type “whole city”."
        ),
        "outside the city": (
            "That result is outside Saint Petersburg or has an unsupported place "
            "type. Your confirmed Search Area is unchanged."
        ),
        "somewhere central": (
            "I found several possible Search Areas. Type the places more precisely."
        ),
        "resolver unavailable": (
            "Location search is temporarily unavailable. Your confirmed Search "
            "Area is unchanged; please try again."
        ),
    }
    for index, (text, expected_message) in enumerate(expected_copy.items()):
        system.submit_location_text(
            update_id=f"area-preservation-outcome-{index}",
            telegram_user_id=user_id,
            text=text,
        )
        assert system.discovery_draft(user_id) == confirmed
        assert telegram_delivery.messages[-1].text == expected_message


def test_search_area_flow_preserves_explicit_conversation_language() -> None:
    telegram_delivery = ControlledTelegramDeliveryAdapter()
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 5, 12, 0, tzinfo=UTC)),
        telegram_delivery=telegram_delivery,
        location_resolver=ControlledLocationResolverAdapter(),
    )
    system.reset()
    user_id = 42_011
    system.start_bot_user(
        update_id="start-russian-search-area",
        telegram_user_id=user_id,
        telegram_language_hint="fr",
    )
    system.select_fixed_language(
        update_id="select-russian-search-area",
        telegram_user_id=user_id,
        locale="ru",
    )
    system.select_direction(
        update_id="intent-russian-search-area",
        telegram_user_id=user_id,
        direction="game_search",
    )
    system.submit_location_text(
        update_id="country-russian-search-area",
        telegram_user_id=user_id,
        text="Russia",
    )
    system.submit_location_text(
        update_id="city-russian-search-area",
        telegram_user_id=user_id,
        text="Saint Petersburg",
    )
    system.submit_location_text(
        update_id="scope-russian-search-area",
        telegram_user_id=user_id,
        text="whole city",
    )

    assert system.conversation_state(user_id).locale == "ru"
    assert telegram_delivery.messages[-1].display_locale == "ru"
    assert telegram_delivery.messages[-1].text == (
        "✅ Зона поиска: **Россия → Санкт-Петербург → весь город**.\n\n"
        "📅 Когда?\n\nНапишите дату или период своими словами."
    )


def test_whole_city_uses_validated_identity_not_localized_candidate_equality() -> None:
    telegram_delivery = ControlledTelegramDeliveryAdapter()
    resolver = ControlledLocationResolverAdapter()
    resolver.return_for(
        stage=ConversationStage.SEARCH_AREA,
        text="localized whole city",
        resolution=LocationResolution(
            interpretations=(
                LocationInterpretation(
                    places=(
                        LocationCandidate(
                            place_id="city:ru:saint-petersburg",
                            display_name="Санкт-Петербург",
                            geographic_type=GeographicType.CITY,
                            country_id="country:ru",
                            city_id="city:ru:saint-petersburg",
                            verified_parent_ids=("country:ru",),
                            parent_display_names=("Россия",),
                            iana_timezone="Europe/Moscow",
                            resolver_version="controlled-resolver-v2",
                            glossary_version="controlled-glossary-v2",
                        ),
                    ),
                    glossary_version="controlled-glossary-v2",
                    whole_city=True,
                ),
            )
        ),
    )
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 5, 12, 0, tzinfo=UTC)),
        telegram_delivery=telegram_delivery,
        location_resolver=resolver,
    )
    system.reset()
    user_id = 42_013
    system.start_bot_user(
        update_id="start-whole-city-identity",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language-whole-city-identity",
        telegram_user_id=user_id,
        locale="en",
    )
    system.select_direction(
        update_id="intent-whole-city-identity",
        telegram_user_id=user_id,
        direction="game_search",
    )
    system.submit_location_text(
        update_id="country-whole-city-identity",
        telegram_user_id=user_id,
        text="Russia",
    )
    system.submit_location_text(
        update_id="city-whole-city-identity",
        telegram_user_id=user_id,
        text="Saint Petersburg",
    )

    system.submit_location_text(
        update_id="scope-whole-city-identity",
        telegram_user_id=user_id,
        text="localized whole city",
    )

    draft = system.discovery_draft(user_id)
    assert draft.stage == "required_date"
    assert draft.whole_city is True
    assert draft.city is not None
    assert draft.city.place_id == "city:ru:saint-petersburg"
    confirmation = system.geography_confirmations(user_id)[-1]
    assert confirmation.resolver_versions == ("controlled-resolver-v2",)
    assert confirmation.glossary_version == "controlled-glossary-v2"


def test_only_application_valid_candidate_advances_among_resolver_proposals() -> None:
    resolver = ControlledLocationResolverAdapter()
    valid_country = LocationCandidate(
        place_id="country:ru",
        display_name="Russia",
        geographic_type=GeographicType.COUNTRY,
        country_id="country:ru",
        city_id=None,
        verified_parent_ids=(),
        parent_display_names=(),
        iana_timezone=None,
        resolver_version="controlled-resolver-v1",
        glossary_version="controlled-glossary-v1",
    )
    invalid_country = LocationCandidate(
        place_id="city:ru:moscow",
        display_name="Moscow",
        geographic_type=GeographicType.CITY,
        country_id="country:ru",
        city_id="city:ru:moscow",
        verified_parent_ids=("country:ru",),
        parent_display_names=("Russia",),
        iana_timezone="Europe/Moscow",
        resolver_version="controlled-resolver-v1",
        glossary_version="controlled-glossary-v1",
    )
    valid_city = LocationCandidate(
        place_id="city:ru:saint-petersburg",
        display_name="Saint Petersburg",
        geographic_type=GeographicType.CITY,
        country_id="country:ru",
        city_id="city:ru:saint-petersburg",
        verified_parent_ids=("country:ru",),
        parent_display_names=("Russia",),
        iana_timezone="Europe/Moscow",
        resolver_version="controlled-resolver-v1",
        glossary_version="controlled-glossary-v1",
    )
    invalid_city = LocationCandidate(
        place_id="city:us:saint-petersburg",
        display_name="Saint Petersburg",
        geographic_type=GeographicType.CITY,
        country_id="country:us",
        city_id="city:us:saint-petersburg",
        verified_parent_ids=("country:us",),
        parent_display_names=("United States",),
        iana_timezone="America/New_York",
        resolver_version="controlled-resolver-v1",
        glossary_version="controlled-glossary-v1",
    )
    resolver.return_for(
        stage=ConversationStage.COUNTRY,
        text="one valid country",
        resolution=LocationResolution(
            interpretations=(
                LocationInterpretation(
                    places=(valid_country,),
                    glossary_version="controlled-glossary-v1",
                ),
                LocationInterpretation(
                    places=(invalid_country,),
                    glossary_version="controlled-glossary-v1",
                ),
            )
        ),
    )
    resolver.return_for(
        stage=ConversationStage.CITY,
        text="one valid city",
        resolution=LocationResolution(
            interpretations=(
                LocationInterpretation(
                    places=(invalid_city,),
                    glossary_version="controlled-glossary-v1",
                ),
                LocationInterpretation(
                    places=(valid_city,),
                    glossary_version="controlled-glossary-v1",
                ),
            )
        ),
    )
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 5, 12, 0, tzinfo=UTC)),
        telegram_delivery=ControlledTelegramDeliveryAdapter(),
        location_resolver=resolver,
    )
    system.reset()
    user_id = 42_015
    system.start_bot_user(
        update_id="start-filtered-candidates",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language-filtered-candidates",
        telegram_user_id=user_id,
        locale="en",
    )
    system.select_direction(
        update_id="intent-filtered-candidates",
        telegram_user_id=user_id,
        direction="game_search",
    )
    system.submit_location_text(
        update_id="country-filtered-candidates",
        telegram_user_id=user_id,
        text="one valid country",
    )
    assert system.discovery_draft(user_id).stage == "city"
    system.submit_location_text(
        update_id="city-filtered-candidates",
        telegram_user_id=user_id,
        text="one valid city",
    )
    assert system.discovery_draft(user_id).stage == "search_area"


def test_geography_confirmations_are_append_only_explicit_events() -> None:
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 5, 12, 0, tzinfo=UTC)),
        telegram_delivery=ControlledTelegramDeliveryAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
    )
    system.reset()
    user_id = 42_014
    system.start_bot_user(
        update_id="start-confirmation-events",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language-confirmation-events",
        telegram_user_id=user_id,
        locale="en",
    )
    system.select_direction(
        update_id="intent-confirmation-events",
        telegram_user_id=user_id,
        direction="game_search",
    )
    assert system.geography_confirmations(user_id) == ()
    system.submit_location_text(
        update_id="country-confirmation-event",
        telegram_user_id=user_id,
        text="Russia",
    )
    system.submit_location_text(
        update_id="city-confirmation-event",
        telegram_user_id=user_id,
        text="Saint Petersburg",
    )
    system.submit_location_text(
        update_id="area-confirmation-event",
        telegram_user_id=user_id,
        text="whole city",
    )
    assert [
        confirmation.kind for confirmation in system.geography_confirmations(user_id)
    ] == ["country", "city", "search_area"]

    system.go_back(update_id="back-after-confirmation-events", telegram_user_id=user_id)
    system.submit_location_text(
        update_id="invalid-after-confirmation-events",
        telegram_user_id=user_id,
        text="unknown scope",
    )
    assert [
        confirmation.kind for confirmation in system.geography_confirmations(user_id)
    ] == ["country", "city", "search_area"]


def test_location_transition_survives_delivery_failure_and_restart() -> None:
    telegram_delivery = ControlledTelegramDeliveryAdapter()
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 5, 12, 0, tzinfo=UTC)),
        telegram_delivery=telegram_delivery,
        location_resolver=ControlledLocationResolverAdapter(),
    )
    system.reset()
    user_id = 42_012
    system.start_bot_user(
        update_id="start-location-delivery-failure",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language-location-delivery-failure",
        telegram_user_id=user_id,
        locale="en",
    )
    system.select_direction(
        update_id="intent-location-delivery-failure",
        telegram_user_id=user_id,
        direction="game_search",
    )
    telegram_delivery.fail_next()

    with pytest.raises(InjectedTelegramDeliveryError):
        system.submit_location_text(
            update_id="country-location-delivery-failure",
            telegram_user_id=user_id,
            text="Russia",
        )

    committed = system.discovery_draft(user_id)
    assert committed.stage == "city"
    assert committed.country is not None
    assert committed.country.place_id == "country:ru"
    delivered_before_retry = len(telegram_delivery.messages)

    system.restart(RuntimeRole.BOT_ASSISTANT)
    assert system.retry_bot_presentations() is True
    assert system.retry_bot_presentations() is False
    assert len(telegram_delivery.messages) == delivered_before_retry + 1
    assert telegram_delivery.messages[-1].screen_revision == committed.screen_revision
