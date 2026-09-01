"""Required Date behavior at the approved PostgreSQL-backed system seam."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime

import pytest

from modules.contracts import RuntimeRole
from modules.domain import (
    ConversationStage,
    DateInterpretation,
    DateInterpretationResolution,
    GeographicType,
    LocationCandidate,
    LocationInterpretation,
    LocationResolution,
)
from modules.testkit import (
    AcceptanceSpine,
    ControlledDateInterpretationAdapter,
    ControlledLocationResolverAdapter,
    ControlledTelegramDeliveryAdapter,
    ControlledTimezoneDataAdapter,
    FrozenClock,
    boot_legacy_acceptance_spine,
)
from modules.timezone_data_adapter import InstalledTimezoneDataAdapter


def test_relative_date_uses_the_confirmed_city_local_calendar() -> None:
    telegram = ControlledTelegramDeliveryAdapter()
    dates = ControlledDateInterpretationAdapter()
    dates.return_for(
        text="tomorrow",
        resolution=DateInterpretationResolution(
            interpretations=(
                DateInterpretation(
                    start_local_date=date(2026, 8, 10),
                    end_local_date=date(2026, 8, 10),
                    iana_timezone="Europe/Moscow",
                ),
            )
        ),
    )
    timezone_data = InstalledTimezoneDataAdapter()
    real_timezone_data_version = timezone_data.resolve("Europe/Moscow").version
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 8, 21, 30, tzinfo=UTC)),
        telegram_delivery=telegram,
        date_interpretation=dates,
        timezone_data=timezone_data,
    )
    system.reset()
    user_id = 43_001
    _advance_to_required_date(system, user_id=user_id, intent="game_search")

    system.submit_required_date_text(
        update_id="date-tomorrow",
        telegram_user_id=user_id,
        text="tomorrow",
    )

    draft = system.discovery_draft(user_id)
    assert draft.stage == "post_core"
    assert draft.required_date is not None
    assert draft.required_date.start_local_date == date(2026, 8, 10)
    assert draft.required_date.end_local_date == date(2026, 8, 10)
    assert draft.required_date.iana_timezone == "Europe/Moscow"
    assert dates.queries[0].timezone_data_version == real_timezone_data_version
    assert draft.required_date.timezone_data_version == real_timezone_data_version
    assert dates.queries[0].authoritative_utc == datetime(
        2026, 8, 8, 21, 30, tzinfo=UTC
    )
    assert dates.queries[0].current_local_date == date(2026, 8, 9)
    confirmations = system.required_date_confirmations(user_id)
    assert len(confirmations) == 1
    assert confirmations[0].required_date == draft.required_date
    assert (
        confirmations[0].required_date.timezone_data_version
        == real_timezone_data_version
    )
    assert telegram.messages[-1].text.startswith(
        "✅ Search area: **Russia → Saint Petersburg → whole city**."
    )


def test_timezone_data_version_comes_from_the_package_fallback_with_the_zone() -> None:
    dates = ControlledDateInterpretationAdapter()
    dates.return_for(
        text="tomorrow",
        resolution=DateInterpretationResolution(
            interpretations=(
                DateInterpretation(
                    start_local_date=date(2026, 8, 10),
                    end_local_date=date(2026, 8, 10),
                    iana_timezone="Europe/Moscow",
                ),
            )
        ),
    )
    timezone_data = ControlledTimezoneDataAdapter()
    timezone_data.add_source(version="earlier-source-version")
    timezone_data.add_package_fallback(
        version="fallback-source-version",
        timezones=("Europe/Moscow",),
    )
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 8, 21, 30, tzinfo=UTC)),
        date_interpretation=dates,
        timezone_data=timezone_data,
    )
    system.reset()
    user_id = 43_006
    _advance_to_required_date(system, user_id=user_id, intent="game_search")

    system.submit_required_date_text(
        update_id="date-from-package-fallback",
        telegram_user_id=user_id,
        text="tomorrow",
    )

    draft = system.discovery_draft(user_id)
    assert draft.required_date is not None
    assert dates.queries[0].timezone_data_version == "fallback-source-version"
    assert draft.required_date.timezone_data_version == "fallback-source-version"
    confirmations = system.required_date_confirmations(user_id)
    assert len(confirmations) == 1
    assert (
        confirmations[0].required_date.timezone_data_version
        == "fallback-source-version"
    )


def test_mismatched_timezone_data_fails_without_temporal_persistence() -> None:
    dates = ControlledDateInterpretationAdapter()
    dates.return_for(
        text="tomorrow",
        resolution=DateInterpretationResolution(
            interpretations=(
                DateInterpretation(
                    start_local_date=date(2026, 8, 10),
                    end_local_date=date(2026, 8, 10),
                    iana_timezone="Europe/Moscow",
                ),
            )
        ),
    )
    timezone_data = ControlledTimezoneDataAdapter()
    timezone_data.return_mismatch_for(
        requested_timezone="Europe/Moscow",
        returned_timezone="UTC",
        version="mismatched-source-version",
    )
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 8, 21, 30, tzinfo=UTC)),
        date_interpretation=dates,
        timezone_data=timezone_data,
    )
    system.reset()
    user_id = 43_007
    _advance_to_required_date(system, user_id=user_id, intent="game_search")

    system.submit_required_date_text(
        update_id="date-with-mismatched-timezone-data",
        telegram_user_id=user_id,
        text="tomorrow",
    )

    draft = system.discovery_draft(user_id)
    assert draft.stage == "required_date"
    assert draft.required_date is None
    assert dates.queries == []
    assert system.required_date_confirmations(user_id) == ()


@pytest.mark.parametrize("failure", ("missing_version", "invalid_data"))
def test_unverifiable_timezone_data_fails_without_temporal_persistence(
    failure: str,
) -> None:
    dates = ControlledDateInterpretationAdapter()
    dates.return_for(
        text="tomorrow",
        resolution=DateInterpretationResolution(
            interpretations=(
                DateInterpretation(
                    start_local_date=date(2026, 8, 10),
                    end_local_date=date(2026, 8, 10),
                    iana_timezone="Europe/Moscow",
                ),
            )
        ),
    )
    timezone_data = ControlledTimezoneDataAdapter()
    timezone_data.fail_for(iana_timezone="Europe/Moscow", failure=failure)
    telegram = ControlledTelegramDeliveryAdapter()
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 8, 21, 30, tzinfo=UTC)),
        telegram_delivery=telegram,
        date_interpretation=dates,
        timezone_data=timezone_data,
    )
    system.reset()
    user_id = 43_008 + len(failure)
    _advance_to_required_date(system, user_id=user_id, intent="game_search")

    system.submit_required_date_text(
        update_id=f"date-with-{failure}",
        telegram_user_id=user_id,
        text="tomorrow",
    )

    draft = system.discovery_draft(user_id)
    assert draft.stage == "required_date"
    assert draft.required_date is None
    assert dates.queries == []
    assert system.required_date_confirmations(user_id) == ()
    assert "📅 When?" in telegram.messages[-1].text


def test_confirming_a_different_city_invalidates_only_dependent_required_date() -> None:
    dates = ControlledDateInterpretationAdapter()
    dates.return_for(
        text="August 10-12",
        resolution=DateInterpretationResolution(
            interpretations=(
                DateInterpretation(
                    start_local_date=date(2026, 8, 10),
                    end_local_date=date(2026, 8, 12),
                    iana_timezone="Europe/Moscow",
                ),
            )
        ),
    )
    resolver = ControlledLocationResolverAdapter()
    resolver.return_for(
        stage=ConversationStage.CITY,
        text="Moscow",
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
                            localized_display_names=tuple(
                                (locale, "Moscow")
                                for locale in ("en", "es", "fr", "ru")
                            ),
                        ),
                    ),
                ),
            )
        ),
    )
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 8, 12, 0, tzinfo=UTC)),
        date_interpretation=dates,
        location_resolver=resolver,
    )
    system.reset()
    user_id = 43_002
    _advance_to_required_date(system, user_id=user_id, intent="game_search")
    system.submit_required_date_text(
        update_id="confirm-range-before-city-change",
        telegram_user_id=user_id,
        text="August 10-12",
    )
    system.go_back(
        update_id="back-to-date-before-city-change", telegram_user_id=user_id
    )
    system.go_back(
        update_id="back-to-area-before-city-change", telegram_user_id=user_id
    )
    system.go_back(
        update_id="back-to-city-before-city-change", telegram_user_id=user_id
    )

    system.submit_location_text(
        update_id="confirm-different-city",
        telegram_user_id=user_id,
        text="Moscow",
    )

    draft = system.discovery_draft(user_id)
    assert draft.city is not None
    assert draft.city.place_id == "city:ru:moscow"
    assert draft.required_date is None
    assert draft.country is not None
    assert draft.country.place_id == "country:ru"


def test_confirming_a_different_country_invalidates_required_date() -> None:
    dates = ControlledDateInterpretationAdapter()
    dates.return_for(
        text="August 10",
        resolution=DateInterpretationResolution(
            interpretations=(
                DateInterpretation(
                    start_local_date=date(2026, 8, 10),
                    end_local_date=date(2026, 8, 10),
                    iana_timezone="Europe/Moscow",
                ),
            )
        ),
    )
    resolver = ControlledLocationResolverAdapter()
    resolver.return_for(
        stage=ConversationStage.COUNTRY,
        text="Germany",
        resolution=LocationResolution(
            interpretations=(
                LocationInterpretation(
                    glossary_version="controlled-glossary-v1",
                    places=(
                        LocationCandidate(
                            place_id="country:de",
                            display_name="Germany",
                            geographic_type=GeographicType.COUNTRY,
                            country_id="country:de",
                            city_id=None,
                            verified_parent_ids=(),
                            parent_display_names=(),
                            iana_timezone=None,
                            resolver_version="controlled-resolver-v1",
                            glossary_version="controlled-glossary-v1",
                            localized_display_names=tuple(
                                (locale, "Germany")
                                for locale in ("en", "es", "fr", "ru")
                            ),
                        ),
                    ),
                ),
            )
        ),
    )
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 8, 12, 0, tzinfo=UTC)),
        date_interpretation=dates,
        location_resolver=resolver,
    )
    system.reset()
    user_id = 43_009
    _advance_to_required_date(system, user_id=user_id, intent="game_search")
    system.submit_required_date_text(
        update_id="date-before-country-change",
        telegram_user_id=user_id,
        text="August 10",
    )
    confirmed = system.discovery_draft(user_id).required_date
    for index in range(4):
        system.go_back(
            update_id=f"back-before-country-change-{index}",
            telegram_user_id=user_id,
        )

    system.submit_location_text(
        update_id="confirm-different-country",
        telegram_user_id=user_id,
        text="Germany",
    )

    draft = system.discovery_draft(user_id)
    assert draft.country is not None
    assert draft.country.place_id == "country:de"
    assert draft.city is None
    assert draft.sub_city_areas == ()
    assert draft.required_date is None
    confirmations = system.required_date_confirmations(user_id)
    assert len(confirmations) == 1
    assert confirmations[0].required_date == confirmed


def test_confirming_a_different_terminal_intent_clears_required_date() -> None:
    dates = ControlledDateInterpretationAdapter()
    dates.return_for(
        text="August 10",
        resolution=DateInterpretationResolution(
            interpretations=(
                DateInterpretation(
                    start_local_date=date(2026, 8, 10),
                    end_local_date=date(2026, 8, 10),
                    iana_timezone="Europe/Moscow",
                ),
            )
        ),
    )
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 8, 12, 0, tzinfo=UTC)),
        date_interpretation=dates,
    )
    system.reset()
    user_id = 43_003
    _advance_to_required_date(system, user_id=user_id, intent="game_search")
    system.submit_required_date_text(
        update_id="date-before-intent-change",
        telegram_user_id=user_id,
        text="August 10",
    )
    for index in range(5):
        system.go_back(
            update_id=f"back-before-intent-change-{index}",
            telegram_user_id=user_id,
        )

    system.select_direction(
        update_id="confirm-different-intent",
        telegram_user_id=user_id,
        direction="player_search",
    )

    draft = system.discovery_draft(user_id)
    assert draft.user_intent == "player_search"
    assert draft.stage == "country"
    assert draft.required_date is None


@pytest.mark.parametrize(
    ("text", "proposals", "technical"),
    (
        ("unknown", (), False),
        (
            "past",
            (DateInterpretation(date(2026, 8, 7), date(2026, 8, 7), "Europe/Moscow"),),
            False,
        ),
        (
            "reversed",
            (
                DateInterpretation(
                    date(2026, 8, 12), date(2026, 8, 10), "Europe/Moscow"
                ),
            ),
            False,
        ),
        (
            "wrong timezone",
            (DateInterpretation(date(2026, 8, 10), date(2026, 8, 10), "UTC"),),
            False,
        ),
        (
            "ambiguous",
            (
                DateInterpretation(
                    date(2026, 8, 10), date(2026, 8, 10), "Europe/Moscow"
                ),
                DateInterpretation(
                    date(2026, 8, 11), date(2026, 8, 11), "Europe/Moscow"
                ),
            ),
            False,
        ),
        ("technical", (), True),
    ),
)
def test_unaccepted_date_outcomes_preserve_the_confirmed_date_and_stage(
    text: str,
    proposals: tuple[DateInterpretation, ...],
    technical: bool,
) -> None:
    dates = ControlledDateInterpretationAdapter()
    dates.return_for(
        text="initial date",
        resolution=DateInterpretationResolution(
            interpretations=(
                DateInterpretation(
                    date(2026, 8, 10), date(2026, 8, 10), "Europe/Moscow"
                ),
            )
        ),
    )
    if technical:
        dates.fail_for(text=text)
    else:
        dates.return_for(
            text=text,
            resolution=DateInterpretationResolution(interpretations=proposals),
        )
    telegram = ControlledTelegramDeliveryAdapter()
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 8, 12, 0, tzinfo=UTC)),
        telegram_delivery=telegram,
        date_interpretation=dates,
    )
    system.reset()
    user_id = 43_100 + len(text)
    _advance_to_required_date(system, user_id=user_id, intent="game_search")
    system.submit_required_date_text(
        update_id=f"initial-{text}", telegram_user_id=user_id, text="initial date"
    )
    confirmed = system.discovery_draft(user_id).required_date
    system.go_back(update_id=f"back-{text}", telegram_user_id=user_id)

    system.submit_required_date_text(
        update_id=f"rejected-{text}", telegram_user_id=user_id, text=text
    )

    draft = system.discovery_draft(user_id)
    assert draft.stage == "required_date"
    assert draft.required_date == confirmed
    assert len(system.required_date_confirmations(user_id)) == 1
    assert "📅 When?" in telegram.messages[-1].text


def test_search_area_only_replacement_preserves_required_date() -> None:
    dates = ControlledDateInterpretationAdapter()
    dates.return_for(
        text="August 10",
        resolution=DateInterpretationResolution(
            interpretations=(
                DateInterpretation(
                    date(2026, 8, 10), date(2026, 8, 10), "Europe/Moscow"
                ),
            )
        ),
    )
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 8, 12, 0, tzinfo=UTC)),
        date_interpretation=dates,
    )
    system.reset()
    user_id = 43_004
    _advance_to_required_date(system, user_id=user_id, intent="game_search")
    system.submit_required_date_text(
        update_id="date-before-area-change",
        telegram_user_id=user_id,
        text="August 10",
    )
    confirmed = system.discovery_draft(user_id).required_date
    system.go_back(update_id="back-date-before-area-change", telegram_user_id=user_id)
    system.go_back(update_id="back-area-before-area-change", telegram_user_id=user_id)

    system.submit_location_text(
        update_id="replace-search-area-only",
        telegram_user_id=user_id,
        text="Near Komendantsky metro and in Primorsky District",
    )

    draft = system.discovery_draft(user_id)
    assert draft.stage == "required_date"
    assert draft.required_date == confirmed
    assert draft.whole_city is False
    assert len(draft.sub_city_areas) == 2


def test_back_restart_stale_and_replayed_input_preserve_concrete_date() -> None:
    dates = ControlledDateInterpretationAdapter()
    for text, day in (("August 10", 10), ("August 11", 11)):
        dates.return_for(
            text=text,
            resolution=DateInterpretationResolution(
                interpretations=(
                    DateInterpretation(
                        date(2026, 8, day),
                        date(2026, 8, day),
                        "Europe/Moscow",
                    ),
                )
            ),
        )
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 8, 12, 0, tzinfo=UTC)),
        date_interpretation=dates,
    )
    system.reset()
    user_id = 43_005
    _advance_to_required_date(system, user_id=user_id, intent="game_search")
    required_revision = system.discovery_draft(user_id).screen_revision
    system.submit_required_date_text(
        update_id="accepted-before-replay",
        telegram_user_id=user_id,
        text="August 10",
    )
    confirmed = system.discovery_draft(user_id).required_date
    system.submit_required_date_text(
        update_id="stale-date-answer",
        telegram_user_id=user_id,
        text="August 11",
        screen_revision=required_revision,
    )
    system.submit_required_date_text(
        update_id="accepted-before-replay",
        telegram_user_id=user_id,
        text="August 11",
    )
    assert system.discovery_draft(user_id).required_date == confirmed
    assert len(system.required_date_confirmations(user_id)) == 1
    system.go_back(update_id="back-after-date", telegram_user_id=user_id)
    assert system.discovery_draft(user_id).required_date == confirmed

    system.restart(role=RuntimeRole.BOT_ASSISTANT)
    system.start_bot_user(
        update_id="restart-after-date",
        telegram_user_id=user_id,
        telegram_language_hint="ru",
    )

    resumed = system.discovery_draft(user_id)
    assert resumed.stage == "required_date"
    assert resumed.required_date == confirmed


def test_clock_advancement_across_restart_does_not_roll_relative_date_forward() -> None:
    dates = ControlledDateInterpretationAdapter()
    dates.return_for(
        text="tomorrow",
        resolution=DateInterpretationResolution(
            interpretations=(
                DateInterpretation(
                    start_local_date=date(2026, 8, 10),
                    end_local_date=date(2026, 8, 10),
                    iana_timezone="Europe/Moscow",
                ),
            )
        ),
    )
    clock = FrozenClock(datetime(2026, 8, 8, 21, 30, tzinfo=UTC))
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        date_interpretation=dates,
    )
    system.reset()
    user_id = 43_010
    _advance_to_required_date(system, user_id=user_id, intent="game_search")
    system.submit_required_date_text(
        update_id="relative-date-before-clock-advance",
        telegram_user_id=user_id,
        text="tomorrow",
    )
    confirmed = system.discovery_draft(user_id).required_date
    assert confirmed is not None
    assert confirmed.start_local_date == date(2026, 8, 10)
    assert confirmed.end_local_date == date(2026, 8, 10)

    clock.advance_to(datetime(2026, 8, 9, 21, 30, tzinfo=UTC))
    system.restart(role=RuntimeRole.BOT_ASSISTANT)
    system.start_bot_user(
        update_id="restart-after-clock-advance",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )

    resumed = system.discovery_draft(user_id)
    assert resumed.stage == "post_core"
    assert resumed.required_date == confirmed
    assert len(dates.queries) == 1
    confirmations = system.required_date_confirmations(user_id)
    assert len(confirmations) == 1
    assert confirmations[0].required_date == confirmed


@pytest.mark.parametrize(
    ("intent", "branch", "expected_stage"),
    (
        ("game_search", None, "required_date"),
        ("player_search", None, "required_date"),
        ("tournament_search", "competition_search", "required_date"),
        ("opponent_search", "competition_search", "required_date"),
        ("new_team_search", "transfer_search", "post_core"),
        ("transfer_player_search", "transfer_search", "post_core"),
        ("coach_search", "coaching_services", "post_core"),
        ("coaching_service_offer", "coaching_services", "post_core"),
        ("referee_search", "refereeing_services", "required_date"),
        ("refereeing_service_offer", "refereeing_services", "required_date"),
    ),
)
def test_only_the_six_date_required_user_intents_enter_required_date(
    intent: str, branch: str | None, expected_stage: str
) -> None:
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 8, 12, 0, tzinfo=UTC)),
    )
    system.reset()
    user_id = 43_200
    _advance_to_core(system, user_id=user_id, intent=intent, branch=branch)

    assert system.discovery_draft(user_id).stage == expected_stage


def _advance_to_required_date(
    system: AcceptanceSpine, *, user_id: int, intent: str
) -> None:
    system.start_bot_user(
        update_id=f"start-{user_id}",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id=f"language-{user_id}", telegram_user_id=user_id, locale="en"
    )
    system.select_direction(
        update_id=f"intent-{user_id}",
        telegram_user_id=user_id,
        direction=intent,
    )
    system.submit_location_text(
        update_id=f"country-{user_id}", telegram_user_id=user_id, text="Russia"
    )
    system.submit_location_text(
        update_id=f"city-{user_id}",
        telegram_user_id=user_id,
        text="Saint Petersburg",
    )
    system.submit_location_text(
        update_id=f"area-{user_id}", telegram_user_id=user_id, text="whole city"
    )


def _advance_to_core(
    system: AcceptanceSpine,
    *,
    user_id: int,
    intent: str,
    branch: str | None,
) -> None:
    system.start_bot_user(
        update_id=f"start-core-{user_id}",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id=f"language-core-{user_id}",
        telegram_user_id=user_id,
        locale="en",
    )
    if branch is not None:
        system.select_direction(
            update_id=f"branch-core-{user_id}",
            telegram_user_id=user_id,
            direction=branch,
        )
    system.select_direction(
        update_id=f"intent-core-{user_id}",
        telegram_user_id=user_id,
        direction=intent,
    )
    system.submit_location_text(
        update_id=f"country-core-{user_id}",
        telegram_user_id=user_id,
        text="Russia",
    )
    system.submit_location_text(
        update_id=f"city-core-{user_id}",
        telegram_user_id=user_id,
        text="Saint Petersburg",
    )
    system.submit_location_text(
        update_id=f"area-core-{user_id}",
        telegram_user_id=user_id,
        text="whole city",
    )
