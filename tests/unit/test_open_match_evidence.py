"""Application-owned semantic evidence checks for classifier proposals."""

# ruff: noqa: RUF001 -- reviewed multilingual evidence is intentional.

from datetime import date, datetime
from zoneinfo import ZoneInfo

from modules.application import (
    _accepted_city_display_labels,
    _event_time_is_supported,
    _is_explicit_children_only_game,
    _open_match_expiry,
    _open_places_are_supported,
    _optional_values_are_supported,
    _resolve_source_location_across_supported_locales,
    _stated_payment_amount_and_currency,
)
from modules.domain import (
    GeographicType,
    LocationCandidate,
    LocationInterpretation,
    LocationResolution,
    LocationResolutionQuery,
)


class _LocalizedLocationResolver:
    def opportunity_revision_id(self, proposal_id: str) -> str:
        return f"revision:{proposal_id}"

    def resolve(self, query: LocationResolutionQuery) -> LocationResolution:
        place_labels = {
            "en": "Central Station",
            "es": "Estación Central",
            "fr": "Gare Centrale",
            "ru": "Центральная",
        }
        parent_labels = {
            "en": ("Country", "City"),
            "es": ("País", "Ciudad"),
            "fr": ("Pays", "Ville"),
            "ru": ("Страна", "Город"),
        }
        return LocationResolution(
            interpretations=(
                LocationInterpretation(
                    places=(
                        LocationCandidate(
                            place_id="station:example:central",
                            display_name=place_labels[query.locale],
                            geographic_type=GeographicType.STATION,
                            country_id="country:example",
                            city_id="city:example",
                            verified_parent_ids=("country:example", "city:example"),
                            parent_display_names=parent_labels[query.locale],
                            iana_timezone="Europe/Paris",
                            resolver_version="controlled-resolver-v1",
                            glossary_version="location-glossary-v1",
                        ),
                    ),
                    glossary_version="location-glossary-v1",
                ),
            )
        )


class _RussianOnlyLocationResolver(_LocalizedLocationResolver):
    def resolve(self, query: LocationResolutionQuery) -> LocationResolution:
        if query.locale != "ru":
            return LocationResolution(interpretations=())
        return super().resolve(query)


def test_bounded_date_range_expires_after_its_last_local_date() -> None:
    timezone = ZoneInfo("Europe/Moscow")
    assert _open_match_expiry(
        date(2026, 8, 20), date(2026, 8, 20), "19:00", timezone
    ) == datetime(2026, 8, 20, 19, 0, tzinfo=timezone)
    assert _open_match_expiry(
        date(2026, 8, 20), date(2026, 8, 22), "19:00", timezone
    ) == datetime(2026, 8, 23, 0, 0, tzinfo=timezone)


def test_city_level_labels_come_from_the_accepted_non_spb_candidate() -> None:
    city = LocationCandidate(
        place_id="city:example:lyon",
        display_name="Lyon",
        geographic_type=GeographicType.CITY,
        country_id="country:example:fr",
        city_id="city:example:lyon",
        verified_parent_ids=("country:example:fr",),
        parent_display_names=("France",),
        iana_timezone="Europe/Paris",
        resolver_version="controlled-resolver-v1",
        glossary_version="location-glossary-v1",
        localized_display_names=(("fr", "Lyon"), ("ru", "Лион")),
    )
    assert _accepted_city_display_labels(city, "city:example:lyon") == {
        "en": "Lyon",
        "ru": "Лион",
        "es": "Lyon",
        "fr": "Lyon",
    }


def test_source_location_reconciles_localized_labels_by_stable_identity() -> None:
    resolved = _resolve_source_location_across_supported_locales(
        _LocalizedLocationResolver(),
        mention="Central",
        country_id="country:example",
        city_id="city:example",
    )

    assert resolved is not None
    place, city_labels = resolved
    assert place.place_id == "station:example:central"
    assert dict(place.localized_display_names) == {
        "en": "Central Station",
        "es": "Estación Central",
        "fr": "Gare Centrale",
        "ru": "Центральная",
    }
    assert city_labels == {
        "en": "City",
        "es": "Ciudad",
        "fr": "Ville",
        "ru": "Город",
    }


def test_source_location_accepts_one_locale_with_safe_label_fallbacks() -> None:
    resolved = _resolve_source_location_across_supported_locales(
        _RussianOnlyLocationResolver(),
        mention="Центральная",
        country_id="country:example",
        city_id="city:example",
    )

    assert resolved is not None
    place, city_labels = resolved
    assert place.place_id == "station:example:central"
    assert city_labels == {
        "en": "Город",
        "es": "Город",
        "fr": "Город",
        "ru": "Город",
    }


def test_only_explicit_children_games_trigger_the_domain_exclusion() -> None:
    assert _is_explicit_children_only_game("Завтра детская игра, нужно одно место")
    assert _is_explicit_children_only_game("Завтра детские игры, нужно одно место")
    assert _is_explicit_children_only_game("Children's game tomorrow; one place open")
    assert _is_explicit_children_only_game("Kids’ game tomorrow; one place open")
    assert _is_explicit_children_only_game("Games for children tomorrow")
    assert _is_explicit_children_only_game("Partidos infantiles mañana")
    assert _is_explicit_children_only_game("Torneos para niños mañana")
    assert _is_explicit_children_only_game("Matchs pour enfants demain")
    assert _is_explicit_children_only_game("Tournois pour enfants demain")
    assert not _is_explicit_children_only_game("Команда 2012 г.р., игра завтра")
    assert not _is_explicit_children_only_game("Youth team needs a goalkeeper")


def test_overlapping_substrings_do_not_authorize_normalized_facts() -> None:
    assert not _event_time_is_supported(
        date(2026, 8, 2),
        date(2026, 8, 2),
        None,
        "20 August 2026",
    )
    assert not _event_time_is_supported(
        date(2026, 8, 2),
        date(2026, 8, 2),
        None,
        "On 20 August 2026 we need 2 players",
    )
    assert not _open_places_are_supported(1, "10 places")
    assert not _open_places_are_supported(1, "one referee")
    assert not _open_places_are_supported(1, "one team registered")
    assert not _open_places_are_supported(1, "одно судейское место")
    assert not _open_places_are_supported(1, "one player was injured")
    assert not _open_places_are_supported(1, "one goalkeeper received an award")
    assert not _open_places_are_supported(1, "one parking place")
    assert not _open_places_are_supported(1, "одно место занято")
    assert not _open_places_are_supported(1, "un joueur est blessé")
    assert not _open_places_are_supported(
        1, "Tickets available to watch the game. one player scored"
    )
    assert not _open_places_are_supported(
        1, "Looking at highlights, one goalkeeper received an award"
    )
    assert not _open_places_are_supported(1, "Есть запись игры. один игрок забил")
    assert not _open_places_are_supported(1, "Hay vídeo del partido. un jugador marcó")
    assert not _open_places_are_supported(
        2, "Need players for tomorrow. We won two trophies"
    )
    assert not _open_places_are_supported(3, "Score was three nil")
    assert not _open_places_are_supported(2, "Need players. Two places occupied")
    assert not _open_places_are_supported(2, "Need two places occupied")
    assert not _open_places_are_supported(2, "Need players, two places occupied")
    assert not _open_places_are_supported(2, "Need players — two places occupied")
    assert not _open_places_are_supported(
        2, "Need players. Two spots available in the parking lot"
    )
    assert not _open_places_are_supported(
        2, "Need players; two places available in the car park"
    )
    assert not _open_places_are_supported(
        2, "Need players and two spots are available for spectators"
    )
    assert not _open_places_are_supported(
        2, "Need players. Two places available in the stands"
    )
    assert not _open_places_are_supported(
        2, "Need players. Two places available for parents"
    )
    assert not _open_places_are_supported(
        2, "Need players. Two places available on the bus"
    )
    assert not _open_places_are_supported(
        1, "Need players. One place available in the stands"
    )
    assert not _open_places_are_supported(
        1, "Need players. One place available for parents"
    )
    assert not _open_places_are_supported(
        1, "Need players. One place available on the bus"
    )
    assert not _open_places_are_supported(1, "One place available on the bus")
    assert _open_places_are_supported(1, "Our team needs one defender")
    assert _open_places_are_supported(1, "El equipo necesita un portero")
    assert _open_places_are_supported(1, "Notre équipe cherche un gardien")
    assert not _optional_values_are_supported(
        {"playing_levels": ["average"]},
        {"playing_levels": "above average"},
    )


def test_supported_languages_use_exact_semantic_evidence() -> None:
    assert _event_time_is_supported(
        date(2026, 9, 25),
        date(2026, 9, 25),
        "20:00",
        "25 septembre 2026 à 20:00",
    )
    assert _event_time_is_supported(
        date(2026, 8, 15),
        date(2026, 8, 15),
        "19:00",
        "Матч завтра в 19:00",
        source_event_time=datetime(2026, 8, 14, 20, 0, tzinfo=ZoneInfo("UTC")),
        source_timezone="Europe/Moscow",
    )
    assert _open_places_are_supported(2, "hay dos plazas para jugadores")
    assert _optional_values_are_supported(
        {
            "positions": ["defender"],
            "playing_levels": ["average"],
            "playing_surfaces": ["artificial_turf"],
            "payment": "paid",
        },
        {
            "positions": "defensa",
            "playing_levels": "nivel medio",
            "playing_surfaces": "césped artificial",
            "payment": "cuota de 8 €",
        },
    )


def test_spanish_daytime_and_evening_evidence_remain_distinct() -> None:
    daytime_evidence = "Partido 20 agosto 2026 de día"
    evening_evidence = "Partido 20 agosto 2026 por la tarde"

    assert _event_time_is_supported(
        date(2026, 8, 20),
        date(2026, 8, 20),
        None,
        daytime_evidence,
        day_part="daytime",
    )
    assert not _event_time_is_supported(
        date(2026, 8, 20),
        date(2026, 8, 20),
        None,
        daytime_evidence,
        day_part="evening",
    )
    assert _event_time_is_supported(
        date(2026, 8, 20),
        date(2026, 8, 20),
        None,
        evening_evidence,
        day_part="evening",
    )
    assert not _event_time_is_supported(
        date(2026, 8, 20),
        date(2026, 8, 20),
        None,
        evening_evidence,
        day_part="daytime",
    )


def test_explicit_amount_and_currency_establishes_paid_without_inference() -> None:
    for evidence in (
        "Fee 500 EUR",
        "Участие 900 рублей",
        "Entrada 20 euros",
        "Tarif 500 CHF",
        "€ 25",
    ):
        assert _optional_values_are_supported(
            {"payment": "paid"},
            {"payment": evidence},
        )

    for evidence in (
        "Fee 500",
        "Currency EUR will be confirmed",
        "Budget 500 and currency EUR",
        "€ currency accepted",
    ):
        assert not _optional_values_are_supported(
            {"payment": "paid"},
            {"payment": evidence},
        )

    assert _stated_payment_amount_and_currency("Fee 500 EUR") == ("500", "EUR")
    assert _stated_payment_amount_and_currency("Tarif 500 CHF") == ("500", "CHF")
    assert _stated_payment_amount_and_currency("Fee 1 500 EUR") == (
        "1 500",
        "EUR",
    )
    assert _stated_payment_amount_and_currency("Fee 500 VIP") is None


def test_weekday_relative_evidence_uses_source_chat_local_calendar() -> None:
    cases = (
        (
            date(2026, 8, 15),
            "Match on Saturday at 19:00",
            datetime(2026, 8, 14, 21, 30, tzinfo=ZoneInfo("UTC")),
            "Europe/Moscow",
        ),
        (
            date(2026, 8, 17),
            "Матч в понедельник в 19:00",
            datetime(2026, 8, 16, 12, 0, tzinfo=ZoneInfo("UTC")),
            "Europe/Moscow",
        ),
        (
            date(2026, 8, 17),
            "Partido el lunes a las 19:00",
            datetime(2026, 8, 16, 12, 0, tzinfo=ZoneInfo("UTC")),
            "Europe/Madrid",
        ),
        (
            date(2026, 8, 17),
            "Match lundi à 19:00",
            datetime(2026, 8, 16, 12, 0, tzinfo=ZoneInfo("UTC")),
            "Europe/Paris",
        ),
        (
            date(2026, 8, 24),
            "Match on Monday at 19:00",
            datetime(2026, 8, 18, 12, 0, tzinfo=ZoneInfo("UTC")),
            "Europe/London",
        ),
    )
    for expected, evidence, source_event_time, timezone in cases:
        assert _event_time_is_supported(
            expected,
            expected,
            "19:00",
            evidence,
            source_event_time=source_event_time,
            source_timezone=timezone,
        )

    assert not _event_time_is_supported(
        date(2026, 8, 16),
        date(2026, 8, 16),
        "19:00",
        "Match on Saturday at 19:00",
        source_event_time=datetime(2026, 8, 14, 21, 30, tzinfo=ZoneInfo("UTC")),
        source_timezone="Europe/Moscow",
    )
