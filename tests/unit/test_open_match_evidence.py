"""Application-owned semantic evidence checks for classifier proposals."""

# ruff: noqa: RUF001 -- reviewed multilingual evidence is intentional.

from datetime import date, datetime
from zoneinfo import ZoneInfo

from modules.application import (
    _accepted_city_display_labels,
    _body_establishes_current_open_match,
    _event_time_is_supported,
    _is_explicit_children_only_game,
    _location_mention_is_authoritative,
    _open_match_expiry,
    _open_places_are_supported,
    _optional_values_are_supported,
    _resolve_source_location_across_supported_locales,
    _select_response_route,
    _stated_payment_amount_and_currency,
)
from modules.contracts import JsonValue
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


def test_authoritative_body_must_establish_one_current_open_match() -> None:
    for body in (
        "Practice 20 August 2026 at Central Station. Need two players",
        "Training 20 August 2026 at Central Station. Need two players",
        "Match or practice 20 August 2026 at Central Station. Need two players",
        "Тренировка 20 августа 2026 у Центральной. Нужны два игрока",
        "Partido o entrenamiento 20 agosto 2026 en Estación Central. "
        "Necesitamos dos jugadores",
        "Match ou entraînement le 20 août 2026 à la Gare Centrale. "
        "Besoin de deux joueurs",
    ):
        assert not _body_establishes_current_open_match(body)

    for body in (
        "Football match 20 August 2026 at Central Station. Need two players",
        "Футбольный матч 20 августа 2026 у Центральной. Нужны два игрока",
        "Partido de fútbol 20 agosto 2026 en Estación Central. "
        "Necesitamos dos jugadores",
        "Match de football le 20 août 2026 à la Gare Centrale. Besoin de deux joueurs",
        "В субботу в 19:00 на [ЛОКАЦИИ] нужен один защитник",
    ):
        assert _body_establishes_current_open_match(body)


def test_resolved_location_requires_positive_unambiguous_source_geography() -> None:
    for body, mention in (
        ("Football match 20 August 2026, not at Central Station", "Central Station"),
        ("Football match at Central Station or North Station", "Central Station"),
        ("Матч не у Центральной", "Центральной"),
        ("Матч у Центральной или Северной", "Центральной"),
        ("Partido no en Estación Central", "Estación Central"),
        ("Partido en Estación Central o Estación Norte", "Estación Central"),
        ("Match pas à la Gare Centrale", "Gare Centrale"),
        ("Match à la Gare Centrale ou à la Gare du Nord", "Gare Centrale"),
    ):
        assert not _location_mention_is_authoritative(body, mention)

    for body, mention in (
        ("Football match at Central Station", "Central Station"),
        ("Матч у Центральной", "Центральной"),
        ("Partido en Estación Central", "Estación Central"),
        ("Match à la Gare Centrale", "Gare Centrale"),
    ):
        assert _location_mention_is_authoritative(body, mention)


def test_location_evidence_tracks_current_replacement_across_the_revision() -> None:
    assert not _location_mention_is_authoritative(
        "Football match at Central Station. Central Station is not the venue",
        "Central Station",
    )
    revised = "Football match at Central Station. Update: North Station instead"
    assert not _location_mention_is_authoritative(revised, "Central Station")
    assert _location_mention_is_authoritative(revised, "North Station")

    for body, old_mention, current_mention in (
        (
            "Football match at Central Station. The venue is now North Station",
            "Central Station",
            "North Station",
        ),
        (
            "Матч у Центральной. Место теперь Северная",
            "Центральной",
            "Северная",
        ),
        (
            "Partido en Estación Central. El lugar ahora es Estación Norte",
            "Estación Central",
            "Estación Norte",
        ),
        (
            "Match à la Gare Centrale. Le lieu est maintenant Gare du Nord",
            "Gare Centrale",
            "Gare du Nord",
        ),
    ):
        assert not _location_mention_is_authoritative(body, old_mention)
        assert _location_mention_is_authoritative(body, current_mention)


def test_explicit_route_requires_contact_semantics_before_fallback_priority() -> None:
    fallback: JsonValue = {
        "reply_route_url": "https://t.me/source_chat/49?comment=1",
    }
    venue_reference = _select_response_route(
        body="Venue page @stadium; reply here to join",
        proposed_routes=[
            {
                "kind": "explicit_telegram_username",
                "value": "@stadium",
                "evidence": "@stadium",
            }
        ],
        bounded_metadata=fallback,
    )
    assert venue_reference == {
        "kind": "reply_thread",
        "value": "https://t.me/source_chat/49?comment=1",
    }

    for body in (
        "Do not contact @stadium; reply here to join",
        "Venue contact: @stadium; reply here to join",
        "The venue contact is @stadium; reply here to join",
    ):
        assert _select_response_route(
            body=body,
            proposed_routes=[
                {
                    "kind": "explicit_telegram_username",
                    "value": "@stadium",
                    "evidence": "@stadium",
                }
            ],
            bounded_metadata=fallback,
        ) == {
            "kind": "reply_thread",
            "value": "https://t.me/source_chat/49?comment=1",
        }

    for body, kind, value in (
        (
            "Message @match_contact to join",
            "explicit_telegram_username",
            "@match_contact",
        ),
        ("Call +44 20 7946 0958 to join", "explicit_phone", "+44 20 7946 0958"),
        (
            "Register at https://example.test/open-match/49",
            "explicit_url",
            "https://example.test/open-match/49",
        ),
    ):
        assert _select_response_route(
            body=body,
            proposed_routes=[{"kind": kind, "value": value, "evidence": value}],
            bounded_metadata=fallback,
        ) == {"kind": kind, "value": value}


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


def test_temporal_range_endpoints_must_belong_to_one_cited_expression() -> None:
    start = date(2026, 8, 20)
    end = date(2026, 9, 10)

    for evidence in (
        "From 20 August 2026 to 10 September 2026",
        "С 20 августа 2026 по 10 сентября 2026",
        "Del 20 agosto 2026 al 10 septiembre 2026",
        "Du 20 août 2026 au 10 septembre 2026",
    ):
        assert _event_time_is_supported(start, end, None, evidence)

    assert _event_time_is_supported(
        date(2026, 8, 20),
        date(2026, 8, 22),
        None,
        "20–22 августа 2026",
    )
    assert not _event_time_is_supported(
        start,
        end,
        None,
        "Previous game 20 August 2026. Player birthday 10 September 2026.",
    )


def test_relative_and_compact_ranges_preserve_both_related_endpoints() -> None:
    source_event_time = datetime(2026, 8, 20, 9, 0, tzinfo=ZoneInfo("UTC"))
    relative_cases = (
        ("tomorrow through Sunday", "Europe/London"),
        ("завтра по воскресенье", "Europe/Moscow"),
        ("mañana hasta domingo", "Europe/Madrid"),
        ("demain jusqu’à dimanche", "Europe/Paris"),
    )
    for evidence, timezone in relative_cases:
        assert _event_time_is_supported(
            date(2026, 8, 21),
            date(2026, 8, 23),
            None,
            evidence,
            source_event_time=source_event_time,
            source_timezone=timezone,
        )

    for evidence in (
        "20–22 August 2026",
        "20–22 августа 2026",
        "20–22 de agosto de 2026",
        "20–22 août 2026",
    ):
        assert _event_time_is_supported(
            date(2026, 8, 20),
            date(2026, 8, 22),
            None,
            evidence,
        )

    for evidence in (
        "From 20 to 22 August 2026",
        "С 20 по 22 августа 2026",
        "Del 20 al 22 de agosto de 2026",
        "Du 20 au 22 août 2026",
        "August 20–22, 2026",
    ):
        assert _event_time_is_supported(
            date(2026, 8, 20),
            date(2026, 8, 22),
            None,
            evidence,
        )


def test_spanish_day_part_evidence_rejects_negation_and_competing_markers() -> None:
    for day_part in ("daytime", "evening"):
        assert not _event_time_is_supported(
            date(2026, 8, 20),
            date(2026, 8, 20),
            None,
            "20 agosto 2026 no por la tarde, de día",
            day_part=day_part,
        )
        assert not _event_time_is_supported(
            date(2026, 8, 20),
            date(2026, 8, 20),
            None,
            "20 agosto 2026 de día o por la tarde",
            day_part=day_part,
        )

    assert not _event_time_is_supported(
        date(2026, 8, 20),
        date(2026, 8, 20),
        None,
        "20 agosto 2026 no por la tarde",
        day_part="evening",
    )


def test_temporal_details_require_one_positive_event_expression() -> None:
    invalid_cases = (
        (
            None,
            "evening",
            "Match 20 August 2026. Training is in the evening",
        ),
        (None, None, "Match is not on 20 August 2026"),
        (None, "evening", "20 agosto 2026, no queremos jugar fútbol por la tarde"),
        (
            None,
            "daytime",
            "20 agosto 2026 de día; el partido será realmente por la tarde",
        ),
        ("19:00", None, "20 August 2026 not at 19:00"),
        ("23:59", None, "Previous score was 23:59. Match 20 August 2026"),
    )
    for exact_time, day_part, evidence in invalid_cases:
        assert not _event_time_is_supported(
            date(2026, 8, 20),
            date(2026, 8, 20),
            exact_time,
            evidence,
            day_part=day_part,
        )

    valid_cases = (
        ("19:00", None, "Match 20 August 2026 at 19:00"),
        ("19:00", None, "Матч 20 августа 2026 в 19:00"),
        (None, "evening", "Partido 20 agosto 2026 por la tarde"),
        (None, "evening", "Match le 20 août 2026 le soir"),
    )
    for exact_time, day_part, evidence in valid_cases:
        assert _event_time_is_supported(
            date(2026, 8, 20),
            date(2026, 8, 20),
            exact_time,
            evidence,
            day_part=day_part,
        )


def test_temporal_evidence_rejects_trailing_event_cancellation() -> None:
    event_date = date(2026, 8, 20)
    invalid_cases = (
        (None, None, "Match 20 August 2026 is not happening"),
        ("19:00", None, "Match 20 August 2026 at 19:00 is cancelled"),
        (None, "evening", "Match 20 August 2026 in the evening is cancelled"),
        (None, None, "Матч 20 августа 2026 не состоится"),
        (None, None, "Partido 20 agosto 2026 está cancelado"),
        (None, None, "Match le 20 août 2026 est annulé"),
    )
    for exact_time, day_part, evidence in invalid_cases:
        assert not _event_time_is_supported(
            event_date,
            event_date,
            exact_time,
            evidence,
            day_part=day_part,
        )

    valid_cases = (
        (None, None, "Match 20 August 2026 is happening"),
        (None, None, "Match 20 August 2026 is not cancelled"),
        ("19:00", None, "Матч 20 августа 2026 в 19:00 подтверждён"),
        (None, None, "Матч 20 августа 2026 не отменён"),
        (None, "evening", "Partido 20 agosto 2026 por la tarde confirmado"),
        (None, None, "Partido 20 agosto 2026 no está cancelado"),
        (None, "evening", "Match le 20 août 2026 le soir confirmé"),
        (None, None, "Match le 20 août 2026 n’est pas annulé"),
    )
    for exact_time, day_part, evidence in valid_cases:
        assert _event_time_is_supported(
            event_date,
            event_date,
            exact_time,
            evidence,
            day_part=day_part,
        )


def test_temporal_evidence_binds_full_clause_cancellation_polarity() -> None:
    event_date = date(2026, 8, 20)
    cancelled_cases = (
        (None, None, "Match 20 August 2026 got cancelled"),
        ("19:00", None, "Match 20 August 2026 at 19:00 got cancelled"),
        (None, "evening", "Match 20 August 2026 in the evening got cancelled"),
        (None, None, "Матч 20 августа 2026 был отменён"),
        ("19:00", None, "Матч 20 августа 2026 в 19:00 был отменён"),
        (None, "evening", "Матч 20 августа 2026 вечером был отменён"),
        (None, None, "Partido 20 agosto 2026 fue cancelado"),
        ("19:00", None, "Partido 20 agosto 2026 a las 19:00 fue cancelado"),
        (None, "evening", "Partido 20 agosto 2026 por la tarde fue cancelado"),
        (None, None, "Match le 20 août 2026 a été annulé"),
        ("19:00", None, "Match le 20 août 2026 à 19:00 a été annulé"),
        (None, "evening", "Match le 20 août 2026 le soir a été annulé"),
    )
    for exact_time, day_part, evidence in cancelled_cases:
        assert not _event_time_is_supported(
            event_date,
            event_date,
            exact_time,
            evidence,
            day_part=day_part,
        )

    affirmed_cases = (
        (None, None, "Match 20 August 2026 was not cancelled"),
        ("19:00", None, "Матч 20 августа 2026 в 19:00 не был отменён"),
        (None, "evening", "Partido 20 agosto 2026 por la tarde no fue cancelado"),
        (None, None, "Match le 20 août 2026 n’a pas été annulé"),
    )
    for exact_time, day_part, evidence in affirmed_cases:
        assert _event_time_is_supported(
            event_date,
            event_date,
            exact_time,
            evidence,
            day_part=day_part,
        )


def test_temporal_evidence_rejects_completed_cancellation_and_withdrawal() -> None:
    event_date = date(2026, 8, 20)
    for evidence in (
        "Match 20 August 2026 got called off",
        "Match 20 August 2026 has been called off",
        "Match 20 August 2026 was withdrawn",
        "Матч 20 августа 2026 был снят",
        "Partido 20 agosto 2026 fue retirado",
        "Match le 20 août 2026 a été retiré",
    ):
        assert not _event_time_is_supported(
            event_date,
            event_date,
            None,
            evidence,
        )

    for evidence in (
        "Match 20 August 2026 has not been cancelled",
        "Матч 20 августа 2026 не был отменён",
        "Partido 20 agosto 2026 no fue cancelado",
        "Match le 20 août 2026 n’a pas été annulé",
    ):
        assert _event_time_is_supported(
            event_date,
            event_date,
            None,
            evidence,
        )


def test_complete_body_vetoes_separate_temporal_retraction_and_competition() -> None:
    event_date = date(2026, 8, 20)
    for body in (
        "Football match 20 August 2026. Update: it was cancelled",
        "Футбольный матч 20 августа 2026. Обновление: его отменили",
        "Partido de fútbol 20 agosto 2026. Actualización: fue cancelado",
        "Match de football le 20 août 2026. Mise à jour : il a été annulé",
        "Football match 20 August 2026. We withdrew it",
        "Football match 20 August 2026 or 21 August 2026",
        "Матч 20 августа 2026 или 21 августа 2026",
        "Partido 20 agosto 2026 o 21 agosto 2026",
        "Match le 20 août 2026 ou le 21 août 2026",
    ):
        assert not _event_time_is_supported(
            event_date,
            event_date,
            None,
            "20 August 2026" if "August" in body else body.split(".", 1)[0],
            authoritative_body=body,
        )

    for body in (
        "Football match 20 August 2026. It was not cancelled",
        "Футбольный матч 20 августа 2026. Его не отменили",
        "Partido de fútbol 20 agosto 2026. No fue cancelado",
        "Match de football le 20 août 2026. Il n’a pas été annulé",
    ):
        assert _event_time_is_supported(
            event_date,
            event_date,
            None,
            body.split(".", 1)[0],
            authoritative_body=body,
        )


def test_complete_body_temporal_retraction_must_refer_to_the_same_event() -> None:
    event_date = date(2026, 8, 20)
    for body in (
        "Football match 20 August 2026. The previous match was cancelled",
        "Футбольный матч 20 августа 2026. Предыдущий матч был отменён",
        "Partido de fútbol 20 agosto 2026. El partido anterior fue cancelado",
        "Match de football le 20 août 2026. Le match précédent a été annulé",
    ):
        assert _event_time_is_supported(
            event_date,
            event_date,
            None,
            body.split(".", 1)[0],
            authoritative_body=body,
        )

    for body in (
        "Football match 20 August 2026. Match cancelled",
        "Футбольный матч 20 августа 2026. Матч отменён",
        "Partido de fútbol 20 agosto 2026. Partido cancelado",
        "Match de football le 20 août 2026. Match annulé",
    ):
        assert not _event_time_is_supported(
            event_date,
            event_date,
            None,
            body.split(".", 1)[0],
            authoritative_body=body,
        )

    withdrawn_next_sentence = (
        (
            "Football match 20 August 2026. It will not go ahead",
            "20 August 2026",
        ),
        ("Футбольный матч 20 августа 2026. Он не состоится", "20 августа 2026"),
        (
            "Partido de fútbol 20 agosto 2026. No se jugará",
            "20 agosto 2026",
        ),
        (
            "Match de football le 20 août 2026. Il n'aura pas lieu",
            "20 août 2026",
        ),
    )
    for body, evidence in withdrawn_next_sentence:
        assert not _event_time_is_supported(
            event_date,
            event_date,
            None,
            evidence,
            authoritative_body=body,
        )


def test_open_player_evidence_accepts_positive_counts_and_rejects_closure() -> None:
    positive_cases = (
        (6, "Need six players"),
        (6, "Need six more players"),
        (6, "Нужно шесть игроков"),
        (6, "Necesitamos seis jugadores"),
        (6, "Besoin de six joueurs"),
        (11, "Need eleven players"),
        (27, "Need twenty seven players"),
        (27, "Need 27 more experienced players"),
        (27, "Нужно двадцать семь ещё опытных игроков"),
        (27, "Necesitamos veinte y siete jugadores experimentados"),
        (27, "Besoin de vingt-sept joueurs expérimentés"),
        (127, "Need one hundred twenty seven experienced players"),
        (127, "Нужно сто двадцать семь опытных игроков"),
        (127, "Necesitamos ciento veintisiete jugadores"),
        (127, "Besoin de cent vingt-sept joueurs"),
        (80, "Besoin de quatre-vingts joueurs"),
        (1000, "Necesitamos mil jugadores"),
        (27, "Need 27 players"),
        (27, "Need 27 more players"),
    )
    for open_places, evidence in positive_cases:
        assert _open_places_are_supported(open_places, evidence)
    assert not _open_places_are_supported(0, "Need 0 players")

    for evidence in (
        "We don’t need two players",
        "We dont need two players",
        "No longer need 2 players",
        "Больше не нужно два игрока",
        "Ya no necesitamos dos jugadores",
        "Nous ne cherchons pas deux joueurs",
        "Nous ne cherchons plus deux joueurs",
        "Nous n’avons plus besoin de deux joueurs",
    ):
        assert not _open_places_are_supported(2, evidence)
    assert not _open_places_are_supported(1, "Need zero players")
    assert not _open_places_are_supported(2, "Need one one players")
    assert not _open_places_are_supported(31, "Need twenty eleven players")


def test_open_player_evidence_requires_one_current_non_competing_opening() -> None:
    closed_cases = (
        ("Need two players, but both places are already filled", 2),
        ("No need for two players", 2),
        ("Two players not needed", 2),
        ("Нужно два игрока, но оба места уже заняты", 2),
        ("Не нужно два игрока", 2),
        ("Два игрока больше не нужны", 2),
        ("Necesitamos dos jugadores, pero las plazas ya están cubiertas", 2),
        ("No necesitamos dos jugadores", 2),
        ("Dos jugadores ya no son necesarios", 2),
        ("Besoin de deux joueurs, mais les places sont déjà pourvues", 2),
        ("Pas besoin de deux joueurs", 2),
        ("Deux joueurs ne sont plus nécessaires", 2),
        ("Besoin de mille mille joueurs", 2000),
    )
    for evidence, open_places in closed_cases:
        assert not _open_places_are_supported(open_places, evidence)

    positive_cases = (
        ("Need one thousand two hundred experienced players", 1200),
        ("Нужно тысяча двести опытных игроков", 1200),
        ("Necesitamos mil doscientos jugadores experimentados", 1200),
        ("Besoin de mille deux cents joueurs expérimentés", 1200),
    )
    for evidence, open_places in positive_cases:
        assert _open_places_are_supported(open_places, evidence)


def test_open_player_evidence_uses_the_complete_current_opening_expression() -> None:
    positive_cases = (
        ("Looking for two players", 2),
        ("Ищем два игрока", 2),
        ("Buscamos dos jugadores", 2),
        ("Nous recherchons deux joueurs", 2),
        ("Need 1,200 more experienced players", 1200),
        ("Нужно 1 200 ещё опытных игроков", 1200),
        ("Necesitamos 1.200 jugadores experimentados", 1200),
        ("Besoin de 1 200 joueurs expérimentés", 1200),
    )
    for evidence, open_places in positive_cases:
        assert _open_places_are_supported(open_places, evidence)

    withdrawn_or_contradictory_cases = (
        "Need two players, but the request was withdrawn",
        "Need two players. We no longer need two players",
        "Нужно два игрока, но заявка была отозвана",
        "Нужно два игрока. Больше не нужно два игрока",
        "Necesitamos dos jugadores, pero la solicitud fue retirada",
        "Necesitamos dos jugadores. Ya no necesitamos dos jugadores",
        "Besoin de deux joueurs, mais la demande a été retirée",
        "Besoin de deux joueurs. Nous n’avons plus besoin de deux joueurs",
    )
    for evidence in withdrawn_or_contradictory_cases:
        assert not _open_places_are_supported(2, evidence)


def test_current_role_opening_allows_unknown_count_and_whole_body_veto() -> None:
    for body in (
        "Football match 20 August 2026. Looking for a goalkeeper",
        "Футбольный матч 20 августа 2026. Ищем вратаря",
        "Partido de fútbol 20 agosto 2026. Buscamos portero",
        "Match de football le 20 août 2026. Recherche gardien",
    ):
        assert _open_places_are_supported(None, body)

    for body in (
        "Football match 20 August 2026. Need two players. We have withdrawn it",
        "Football match 20 August 2026. Need two players. Both slots are filled",
        "Матч 20 августа 2026. Нужны два игрока. Заявка отозвана",
        "Partido 20 agosto 2026. Necesitamos dos jugadores. Las plazas están cubiertas",
        "Match le 20 août 2026. Besoin de deux joueurs. Les places sont pourvues",
    ):
        assert not _open_places_are_supported(None, body)


def test_current_individual_opening_is_proven_across_the_complete_body() -> None:
    for body in (
        "Goalkeeper wanted",
        "Нужен вратарь",
        "Se busca portero",
        "Gardien recherché",
    ):
        assert _open_places_are_supported(None, body)

    for body in (
        "Looking for a goalkeeper. We found one",
        "Ищем вратаря. Одного уже нашли",
        "Buscamos un portero. Ya encontramos uno",
        "Nous cherchons un gardien. On en a trouvé un",
    ):
        assert not _open_places_are_supported(None, body)

    for body in (
        "Football match 20 August 2026. Need a goalkeeper. All roles have been filled",
        "Футбольный матч 20 августа 2026. Нужен вратарь. Все роли уже заполнены",
        "Partido de fútbol 20 agosto 2026. Necesitamos un portero. "
        "Todos los puestos están cubiertos",
        "Match de football le 20 août 2026. Besoin d'un gardien. "
        "Tous les rôles sont pourvus",
    ):
        assert not _open_places_are_supported(None, body)


def test_open_match_proposition_requires_positive_unambiguous_football_meaning() -> (
    None
):
    for body in (
        "Basketball game tomorrow",
        "Tournament match tomorrow",
        "League game tomorrow",
    ):
        assert not _body_establishes_current_open_match(body)

    for body in (
        "Football match tomorrow",
        "This is not training. Football match tomorrow",
        "Футбольный матч завтра",
        "Partido de fútbol mañana",
        "Match de football demain",
    ):
        assert _body_establishes_current_open_match(body)

    for body in (
        "Football match is not a real game. 20 August 2026 at Central Station. "
        "Need one player",
        "Футбольный матч — не настоящая игра. 20 августа 2026 у Центральной. "
        "Нужен один игрок",
        "El partido de fútbol no es un partido real. 20 agosto 2026 en "
        "Estación Central. "
        "Necesitamos un jugador",
        "Le match de football n'est pas un vrai match. 20 août 2026 à la "
        "Gare Centrale. "
        "Besoin d'un joueur",
    ):
        assert not _body_establishes_current_open_match(body)


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
    assert _stated_payment_amount_and_currency("Entrada 500 pesos") == (
        "500",
        "pesos",
    )
    assert _stated_payment_amount_and_currency("Участие 500 юаней") == (
        "500",
        "юаней",
    )
    assert _stated_payment_amount_and_currency("Fee 500 yen") == ("500", "yen")
    assert _stated_payment_amount_and_currency("Fee 500 cad") == ("500", "cad")
    assert _stated_payment_amount_and_currency("Fee 500 eUr per player") == (
        "500",
        "eUr",
    )
    assert _stated_payment_amount_and_currency("Tarif 500 francs suisses") == (
        "500",
        "francs suisses",
    )
    assert _stated_payment_amount_and_currency("Fee 500") is None
    assert _stated_payment_amount_and_currency("Fee 500 real") is None
    assert _stated_payment_amount_and_currency("Fee 500 VIP") is None


def test_named_currencies_preserve_the_complete_source_span() -> None:
    cases = (
        ("Fee 500 dirhams", ("500", "dirhams")),
        ("Участие 500 гривен", ("500", "гривен")),
        ("Entrada 500 soles", ("500", "soles")),
        ("Tarif 500 dinars", ("500", "dinars")),
        ("Tarif 500 francs CFA", ("500", "francs CFA")),
        ("Entrada 500 pesos mexicanos", ("500", "pesos mexicanos")),
        ("Fee 500 aEd", ("500", "aEd")),
        ("Fee 500 euros per player", ("500", "euros")),
        ("Tarif 500 francs suisses par joueur", ("500", "francs suisses")),
        ("Entrada 500 pesos mexicanos por persona", ("500", "pesos mexicanos")),
        ("Взнос 500 рублей с игрока", ("500", "рублей")),
        ("Fee 500 Australian dollars. Contact @sample", ("500", "Australian dollars")),
        ("Взнос 500 российских рублей за игрока", ("500", "российских рублей")),
        ("Entrada 500 pesos argentinos por persona", ("500", "pesos argentinos")),
        ("Tarif 500 francs belges par joueur", ("500", "francs belges")),
        ("Fee 500 dirhams UAE. Contact @sample", ("500", "dirhams UAE")),
        ("Tarif 500 dirhams marocains", ("500", "dirhams marocains")),
        ("Fee 500 Czech koruna", ("500", "Czech koruna")),
        ("Fee 500 Norwegian kroner", ("500", "Norwegian kroner")),
        ("Fee 500 Polish zloty", ("500", "Polish zloty")),
        ("Fee 500 Thai baht", ("500", "Thai baht")),
        ("Fee 500 Indian rupees", ("500", "Indian rupees")),
        ("Fee 500 Brazilian reais", ("500", "Brazilian reais")),
        ("Fee 500 Iranian rials", ("500", "Iranian rials")),
        ("Fee 500 South African rand", ("500", "South African rand")),
    )
    for evidence, expected in cases:
        assert _stated_payment_amount_and_currency(evidence) == expected
        assert _optional_values_are_supported(
            {"payment": "paid"},
            {"payment": evidence},
        )

    assert _stated_payment_amount_and_currency("Fee 500") is None
    assert _stated_payment_amount_and_currency("Fee 500 real") is None
    for ambiguous_longer_name in (
        "Fee 500 euros training starts at 19:00",
        "Fee 500 euros per player parking included",
    ):
        assert _stated_payment_amount_and_currency(ambiguous_longer_name) is None


def test_currency_evidence_disambiguates_iso_prose_and_ordinary_qualifiers() -> None:
    for ordinary_prose in (
        "We will try 500 players",
        "The top 500 players qualify",
        "Need 500 all-round players",
    ):
        assert _stated_payment_amount_and_currency(ordinary_prose) is None
        assert not _optional_values_are_supported(
            {"payment": "paid"},
            {"payment": ordinary_prose},
        )

    qualified_payments = (
        ("Fee 500 euros each player", ("500", "euros")),
        ("Взнос 500 рублей за каждого игрока", ("500", "рублей")),
        ("Entrada 500 euros por cada jugador", ("500", "euros")),
        ("Tarif 500 euros pour chaque joueur", ("500", "euros")),
        ("Fee 500 eUr for each player", ("500", "eUr")),
    )
    for evidence, expected in qualified_payments:
        assert _stated_payment_amount_and_currency(evidence) == expected
        assert _optional_values_are_supported(
            {"payment": "paid"},
            {"payment": evidence},
        )


def test_currency_evidence_rejects_iso_words_and_accepts_every_person() -> None:
    for ordinary_prose in (
        "Fee covers all 500",
        "Entry top 500",
        "Payment try 500",
        "Fee covers ALL 500",
        "Entry TOP 500",
        "Payment TRY 500",
    ):
        assert _stated_payment_amount_and_currency(ordinary_prose) is None

    qualified_payments = (
        ("Fee 500 euros for every player", ("500", "euros")),
        ("Взнос 500 рублей для каждого игрока", ("500", "рублей")),
        ("Entrada 500 euros para cada persona", ("500", "euros")),
        ("Tarif 500 euros pour chaque personne", ("500", "euros")),
    )
    for evidence, expected in qualified_payments:
        assert _stated_payment_amount_and_currency(evidence) == expected
        assert _optional_values_are_supported(
            {"payment": "paid"},
            {"payment": evidence},
        )


def test_optional_game_search_facts_require_affirmative_evidence() -> None:
    negated_cases: tuple[tuple[dict[str, JsonValue], dict[str, JsonValue]], ...] = (
        ({"team_formats": ["7x7"]}, {"team_formats": "We are not playing 7x7"}),
        ({"positions": ["defender"]}, {"positions": "We do not need a defender"}),
        (
            {"playing_levels": ["professional"]},
            {"playing_levels": "The level is not professional"},
        ),
        ({"venue_settings": ["indoor"]}, {"venue_settings": "The game is not indoor"}),
        (
            {"playing_surfaces": ["artificial_turf"]},
            {"playing_surfaces": "No artificial turf"},
        ),
        ({"payment": "paid"}, {"payment": "Participation is not paid"}),
        ({"payment": "free"}, {"payment": "This is not free"}),
    )
    for candidate, evidence in negated_cases:
        assert not _optional_values_are_supported(candidate, evidence)

    affirmative_cases: tuple[tuple[dict[str, JsonValue], dict[str, JsonValue]], ...] = (
        ({"team_formats": ["7x7"]}, {"team_formats": "We are playing 7x7"}),
        ({"positions": ["defender"]}, {"positions": "We need a defender"}),
        (
            {"playing_levels": ["professional"]},
            {"playing_levels": "Professional level"},
        ),
        ({"venue_settings": ["indoor"]}, {"venue_settings": "The game is indoor"}),
        (
            {"playing_surfaces": ["artificial_turf"]},
            {"playing_surfaces": "Artificial turf"},
        ),
        ({"payment": "paid"}, {"payment": "Participation is paid"}),
        ({"payment": "free"}, {"payment": "This is free"}),
    )
    for candidate, evidence in affirmative_cases:
        assert _optional_values_are_supported(candidate, evidence)


def test_optional_game_search_facts_reject_retracted_and_competing_support() -> None:
    adversarial_cases: tuple[tuple[dict[str, JsonValue], str, str], ...] = (
        ({"team_formats": ["7x7"]}, "team_formats", "7x7 was cancelled"),
        (
            {"positions": ["defender"]},
            "positions",
            "Need a defender, but the request was withdrawn",
        ),
        (
            {"positions": ["defender"]},
            "positions",
            "Нужен защитник, но заявка была отозвана",
        ),
        (
            {"positions": ["defender"]},
            "positions",
            "Necesitamos defensa, pero la solicitud fue retirada",
        ),
        (
            {"positions": ["defender"]},
            "positions",
            "Besoin d’un défenseur, mais la demande a été retirée",
        ),
        (
            {"positions": ["defender"]},
            "positions",
            "Need a defender or a goalkeeper",
        ),
        (
            {"playing_levels": ["professional"]},
            "playing_levels",
            "Professional level. The level is not professional",
        ),
        (
            {"venue_settings": ["indoor"]},
            "venue_settings",
            "Indoor. It is not indoor",
        ),
        (
            {"playing_surfaces": ["artificial_turf"]},
            "playing_surfaces",
            "Artificial turf. The field is no longer artificial turf",
        ),
        (
            {"payment": "paid"},
            "payment",
            "Participation is paid. Payment was cancelled",
        ),
    )
    for candidate, field_name, source_expression in adversarial_cases:
        assert not _optional_values_are_supported(
            candidate,
            {field_name: source_expression},
        )


def test_semantic_evidence_is_bound_to_the_authoritative_source_body() -> None:
    event_date = date(2026, 8, 20)
    assert not _event_time_is_supported(
        event_date,
        event_date,
        None,
        "20 August 2026",
        authoritative_body="Match 20 August 2026 has been called off",
    )
    assert not _open_places_are_supported(
        2,
        "Need two players",
        authoritative_body="Need two players, but the request was withdrawn",
    )
    assert not _optional_values_are_supported(
        {"positions": ["defender"]},
        {"positions": "Need a defender"},
        authoritative_body="Need a defender or a goalkeeper",
    )
    assert not _optional_values_are_supported(
        {"payment": "paid"},
        {"payment": "Participation is paid"},
        authoritative_body="Participation is paid. Payment was cancelled",
    )
    assert not _optional_values_are_supported(
        {"positions": ["forward"]},
        {"positions": "forward"},
        authoritative_body=(
            "Football match 20 August 2026. Need one goalkeeper. "
            "Please forward this message"
        ),
    )
    assert not _optional_values_are_supported(
        {"payment": "paid"},
        {"payment": "paid"},
        authoritative_body=(
            "Football match 20 August 2026. Need a defender. Parking is paid"
        ),
    )
    assert not _optional_values_are_supported(
        {"positions": ["defender"]},
        {"positions": "Need a defender"},
        authoritative_body=(
            "Football match 20 August 2026. Need a defender. "
            "We later withdrew the opening"
        ),
    )

    assert _event_time_is_supported(
        event_date,
        event_date,
        None,
        "20 August 2026",
        authoritative_body="Match 20 August 2026 is not cancelled",
    )
    assert _open_places_are_supported(
        2,
        "Looking for two players",
        authoritative_body="Looking for two experienced players",
    )
    assert _optional_values_are_supported(
        {"positions": ["defender"]},
        {"positions": "Need a defender"},
        authoritative_body="Need a defender",
    )
    assert _optional_values_are_supported(
        {"payment": "paid"},
        {"payment": "Participation fee is paid"},
        authoritative_body=("Football match 20 August 2026. Participation fee is paid"),
    )


def test_optional_facts_reject_forward_payment_homonyms_and_filled_roles() -> None:
    assert not _optional_values_are_supported(
        {"positions": ["forward"]},
        {"positions": "forward"},
        authoritative_body=(
            "Football match 20 August 2026. Need a goalkeeper. "
            "Please forward this message"
        ),
    )

    payment_cases: tuple[
        tuple[dict[str, JsonValue], dict[str, JsonValue], str], ...
    ] = (
        (
            {"payment": "paid"},
            {"payment": "paid"},
            "Football match 20 August 2026. The team paid the referee",
        ),
        (
            {"payment": "paid"},
            {"payment": "оплачено"},
            "Футбольный матч 20 августа 2026. Команда оплатила судье",
        ),
        (
            {"payment": "paid"},
            {"payment": "pagado"},
            "Partido de fútbol 20 agosto 2026. El equipo pagó al árbitro",
        ),
        (
            {"payment": "paid"},
            {"payment": "payé"},
            "Match de football le 20 août 2026. L’équipe a payé l’arbitre",
        ),
    )
    for payment_candidate, payment_evidence, payment_body in payment_cases:
        assert not _optional_values_are_supported(
            payment_candidate,
            payment_evidence,
            authoritative_body=payment_body,
        )

    role_cases = (
        (
            "Football match 20 August 2026. Need a defender. We found one",
            "Need a defender",
        ),
        (
            "Футбольный матч 20 августа 2026. Нужен защитник. Одного уже нашли",
            "Нужен защитник",
        ),
        (
            "Partido de fútbol 20 agosto 2026. Necesitamos defensa. Ya encontramos uno",
            "Necesitamos defensa",
        ),
        (
            "Match de football le 20 août 2026. Besoin d’un défenseur. "
            "On en a trouvé un",
            "Besoin d’un défenseur",
        ),
    )
    role_candidate: dict[str, JsonValue] = {"positions": ["defender"]}
    for body, role_evidence in role_cases:
        role_evidence_value: dict[str, JsonValue] = {"positions": role_evidence}
        assert not _optional_values_are_supported(
            role_candidate,
            role_evidence_value,
            authoritative_body=body,
        )

    assert not _optional_values_are_supported(
        {"positions": ["defender"]},
        {"positions": "Defender is a legal role in the game"},
        authoritative_body=(
            "Football match 20 August 2026. Need one player. "
            "Defender is a legal role in the game"
        ),
    )
    assert not _optional_values_are_supported(
        {"positions": ["defender"]},
        {"positions": "Need a defender"},
        authoritative_body=(
            "Football match 20 August 2026. Need a defender. All roles have been filled"
        ),
    )


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
