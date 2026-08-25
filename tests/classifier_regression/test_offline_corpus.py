"""Deterministic, credential-free classifier regression gate."""

# ruff: noqa: RUF001 -- reviewed multilingual evidence is intentional.

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path

from modules.application import (
    _body_establishes_current_open_match,
    _event_time_is_supported,
    _location_mention_is_authoritative,
    _open_places_are_supported,
    _optional_values_are_supported,
    _select_response_route,
    _stated_payment_amount_and_currency,
)
from modules.classifier_contract import (
    PROPOSITION_EVIDENCE_VERSION,
    classifier_output_is_schema_valid,
)
from modules.contracts import JsonValue
from modules.ports import ClassifierAdapterResult, ClassifierRequest
from modules.testkit import ControlledModelAdapter


def test_versioned_redacted_classifier_corpus_replays_offline() -> None:
    corpus_path = Path(__file__).with_name("corpus.v1.json")
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    assert corpus["corpus_version"] == "open-match-classifier-regression-v1"
    assert corpus["redacted"] is True
    cases = corpus["cases"]
    assert cases
    assert len({case["case_id"] for case in cases}) == len(cases)
    schema_path = (
        Path(__file__).parents[2]
        / "classifier"
        / "open-match-primary-v1"
        / "source-message-classification-v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["$id"] == "source-message-classification-v1"
    assert schema["additionalProperties"] is False

    adapter = ControlledModelAdapter()
    for case in cases:
        source_event_time = case.get("source_event_time", "2026-08-14T12:00:00+00:00")
        source_chat_timezone = case.get("source_chat_timezone", "Europe/Moscow")
        assert isinstance(source_event_time, str)
        assert isinstance(source_chat_timezone, str)
        adapter.return_for(
            body=case["source"],
            result=ClassifierAdapterResult(
                output=case["recorded_output"],
                effective_model="gpt-5.6-sol",
                effective_reasoning_effort="high",
                codex_version="recorded-offline",
                adapter_kind="recorded_corpus",
                adapter_version=corpus["corpus_version"],
                duration_ms=0,
                input_tokens=0,
                output_tokens=0,
            ),
        )
        result = adapter.classify(
            ClassifierRequest(
                source_message_revision_id=f"redacted:{case['case_id']}:revision:1",
                body=case["source"],
                source_event_time=source_event_time,
                context_bundle_version="primary-classifier-context-v1",
                source_chat_reference="redacted:source-chat",
                source_chat_timezone=source_chat_timezone,
                source_chat_geography={"country_id": None, "city_id": None},
                bounded_metadata={
                    "message_language": None,
                    "attachment_types": [],
                },
                eligible_reply_context=None,
                requested_model="gpt-5.6-sol",
                requested_reasoning_effort="high",
                prompt_version="open-match-primary-v1",
                schema_version="source-message-classification-v1",
                glossary_version="football-opportunity-glossary-v1",
                context_policy_version="classifier-context-v1",
                routing_policy_version="classifier-routing-v1",
            )
        )
        assert classifier_output_is_schema_valid(
            result.output,
            body=case["source"],
        )
        expected = case["expected"]
        assert result.output["disposition"] == expected["disposition"]
        candidates = result.output["candidates"]
        assert isinstance(candidates, list)
        assert len(candidates) == expected["candidate_count"]
        if candidates:
            candidate = candidates[0]
            assert isinstance(candidate, dict)
            evidence = candidate["evidence"]
            assert isinstance(evidence, dict)
            proposition_evidence = candidate["proposition_evidence"]
            assert isinstance(proposition_evidence, dict)
            assert (
                proposition_evidence["contract_version"] == PROPOSITION_EVIDENCE_VERSION
            )
            assert proposition_evidence["coverage"] == "complete_source_revision"
            assert _optional_values_are_supported(candidate, evidence)
            assert candidate["opportunity_type"] == expected["opportunity_type"]
            assert candidate["open_places"] == expected["open_places"]
            assert candidate["positions"] == expected["positions"]
            if (
                case.get("validate_relative_event_time") is True
                or case.get("validate_event_time") is True
            ):
                event_time = candidate["event_time"]
                assert isinstance(event_time, dict)
                start_local_date = event_time["start_local_date"]
                end_local_date = event_time["end_local_date"]
                exact_local_time = event_time.get("exact_local_time")
                day_part = event_time.get("day_part")
                event_time_evidence = evidence["event_time"]
                assert isinstance(start_local_date, str)
                assert isinstance(end_local_date, str)
                assert exact_local_time is None or isinstance(exact_local_time, str)
                assert day_part is None or isinstance(day_part, str)
                assert isinstance(event_time_evidence, str)
                assert _event_time_is_supported(
                    date.fromisoformat(start_local_date),
                    date.fromisoformat(end_local_date),
                    exact_local_time,
                    event_time_evidence,
                    day_part=day_part,
                    source_event_time=datetime.fromisoformat(source_event_time),
                    source_timezone=source_chat_timezone,
                )
        assert result.effective_model == "gpt-5.6-sol"
        assert result.effective_reasoning_effort == "high"
        assert adapter.requests[-1].requested_model == "gpt-5.6-sol"
        assert adapter.requests[-1].requested_reasoning_effort == "high"

    invalid_output = deepcopy(cases[0]["recorded_output"])
    invalid_output["unexpected"] = True
    assert not classifier_output_is_schema_valid(
        invalid_output,
        body=cases[0]["source"],
    )
    unsupported_evidence = deepcopy(cases[0]["recorded_output"])
    unsupported_evidence["candidates"][0]["evidence"]["open_places"] = (
        "fabricated three places"
    )
    assert not classifier_output_is_schema_valid(
        unsupported_evidence,
        body=cases[0]["source"],
    )
    malformed_route = deepcopy(cases[0]["recorded_output"])
    malformed_route["candidates"][0]["response_routes"][0]["unexpected"] = True
    assert not classifier_output_is_schema_valid(
        malformed_route,
        body=cases[0]["source"],
    )
    invalid_domain_value = deepcopy(cases[0]["recorded_output"])
    invalid_domain_value["candidates"][0]["positions"] = ["sweeper"]
    assert not classifier_output_is_schema_valid(
        invalid_domain_value,
        body=cases[0]["source"],
    )


def test_v2_provider_schemas_match_strict_application_evidence_contract() -> None:
    """Both provider artifacts declare the same strict v2 wire contract."""
    repository_root = Path(__file__).parents[2]
    schema_paths = (
        repository_root
        / "classifier"
        / "open-match-primary-v2"
        / "source-message-classification-v2.schema.json",
        repository_root
        / "classifier"
        / "open-match-ambiguity-v1"
        / "source-message-classification-v2.schema.json",
    )

    expected_event_time = {
        "type": "object",
        "additionalProperties": False,
        "required": ["start_local_date", "end_local_date", "iana_timezone"],
        "not": {"required": ["exact_local_time", "day_part"]},
        "properties": {
            "start_local_date": {"type": "string", "format": "date"},
            "end_local_date": {"type": "string", "format": "date"},
            "exact_local_time": {
                "type": "string",
                "pattern": "^(?:[01][0-9]|2[0-3]):[0-5][0-9]$",
            },
            "day_part": {"enum": ["morning", "daytime", "evening", "night"]},
            "iana_timezone": {"type": "string", "minLength": 1},
        },
    }
    expected_proposition_evidence = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "contract_version",
            "coverage",
            "root",
            "facts",
            "routes",
            "relations",
        ],
        "properties": {
            "contract_version": {"const": "source-proposition-evidence-v1"},
            "coverage": {"const": "complete_source_revision"},
            "root": {"$ref": "#/$defs/propositionRoot"},
            "facts": {
                "type": "object",
                "additionalProperties": {"$ref": "#/$defs/propositionFact"},
            },
            "routes": {
                "type": "array",
                "maxItems": 8,
                "items": {"$ref": "#/$defs/propositionRoute"},
            },
            "relations": {
                "type": "array",
                "minItems": 1,
                "maxItems": 32,
                "items": {"$ref": "#/$defs/propositionRelation"},
            },
        },
    }

    for schema_path in schema_paths:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        assert schema["$id"] == "source-message-classification-v2"
        assert schema["$defs"]["eventTime"] == expected_event_time
        assert schema["$defs"]["propositionEvidence"] == expected_proposition_evidence
        for definition_name, required_fields in {
            "sourceSpan": ["start", "end", "text"],
            "propositionFact": [
                "proposition_id",
                "polarity",
                "currentness",
                "span",
            ],
            "propositionRoot": [
                "proposition_id",
                "domain",
                "meaning",
                "polarity",
                "currentness",
                "span",
            ],
            "propositionRoute": [
                "kind",
                "value",
                "proposition_id",
                "polarity",
                "currentness",
                "span",
            ],
            "propositionRelation": ["kind", "direction", "target", "span"],
        }.items():
            definition = schema["$defs"][definition_name]
            assert definition["type"] == "object"
            assert definition["additionalProperties"] is False
            assert definition["required"] == required_fields


def test_v3_transfer_artifacts_are_additive_and_version_bound() -> None:
    """The transfer-capable classifier artifacts use new immutable identities."""
    repository_root = Path(__file__).parents[2]
    primary_provenance = json.loads(
        (
            repository_root / "classifier" / "open-match-primary-v3" / "provenance.json"
        ).read_text(encoding="utf-8")
    )
    primary_schema = json.loads(
        (
            repository_root
            / "classifier"
            / "open-match-primary-v3"
            / "source-message-classification-v3.schema.json"
        ).read_text(encoding="utf-8")
    )
    ambiguity_schema = json.loads(
        (
            repository_root
            / "classifier"
            / "open-match-ambiguity-v2"
            / "source-message-classification-v3.schema.json"
        ).read_text(encoding="utf-8")
    )
    semantic_proof_schema = json.loads(
        (
            repository_root
            / "classifier"
            / "open-match-semantic-proof-v2"
            / "source-semantic-proof-v2.schema.json"
        ).read_text(encoding="utf-8")
    )

    assert primary_provenance["prompt_version"] == "open-match-primary-v3"
    assert primary_provenance["schema_version"] == "source-message-classification-v3"
    assert primary_schema["$id"] == "source-message-classification-v3"
    assert ambiguity_schema["$id"] == "source-message-classification-v3"
    assert semantic_proof_schema["$id"] == "source-semantic-proof-v2"
    assert "# Open Match primary classifier — v3\n" in (
        repository_root / "classifier" / "open-match-primary-v3" / "prompt.md"
    ).read_text(encoding="utf-8")
    assert "source-message-classification-v3.schema.json" in (
        repository_root / "classifier" / "open-match-primary-v3" / "prompt.md"
    ).read_text(encoding="utf-8")
    assert "# Open Match ambiguity second pass — v2\n" in (
        repository_root / "classifier" / "open-match-ambiguity-v2" / "prompt.md"
    ).read_text(encoding="utf-8")
    assert "source-message-classification-v3" in (
        repository_root / "classifier" / "open-match-ambiguity-v2" / "prompt.md"
    ).read_text(encoding="utf-8")
    assert "# Open Match semantic-proof pass — v2\n" in (
        repository_root / "classifier" / "open-match-semantic-proof-v2" / "prompt.md"
    ).read_text(encoding="utf-8")
    assert "source-semantic-proof-v2.schema.json" in (
        repository_root / "classifier" / "open-match-semantic-proof-v2" / "prompt.md"
    ).read_text(encoding="utf-8")
    assert "Player\nTransfer Availability" in (
        repository_root / "classifier" / "open-match-semantic-proof-v2" / "prompt.md"
    ).read_text(encoding="utf-8")
    assert {
        "roster_vacancy",
        "player_transfer_availability",
    }.issubset(
        set(
            primary_schema["$defs"]["acceptedCandidate"]["properties"][
                "opportunity_type"
            ]["enum"]
        )
    )
    assert "long-term" in (
        repository_root / "classifier" / "open-match-primary-v3" / "prompt.md"
    ).read_text(encoding="utf-8")


def test_offline_corpus_rejects_unrelated_numeric_date_cooccurrence() -> None:
    """A wrong normalized day cannot borrow another fact's numeric token."""
    assert not _event_time_is_supported(
        date(2026, 8, 2),
        date(2026, 8, 2),
        None,
        "20 August 2026 — two players are needed",
    )
    assert not _event_time_is_supported(
        date(2026, 8, 20),
        date(2026, 9, 10),
        None,
        "Previous game 20 August 2026. Player birthday 10 September 2026.",
    )


def test_offline_corpus_accepts_related_ranges_in_all_supported_locales() -> None:
    source_event_time = datetime.fromisoformat("2026-08-20T09:00:00+00:00")
    for evidence, timezone in (
        ("tomorrow through Sunday", "Europe/London"),
        ("завтра по воскресенье", "Europe/Moscow"),
        ("mañana hasta domingo", "Europe/Madrid"),
        ("demain jusqu’à dimanche", "Europe/Paris"),
    ):
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


def test_offline_day_part_evidence_rejects_cross_value_negation_and_ambiguity() -> None:
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


def test_offline_temporal_details_are_positive_and_event_bound() -> None:
    for exact_time, day_part, evidence in (
        (None, "evening", "Match 20 August 2026. Training is in the evening"),
        (None, None, "Match is not on 20 August 2026"),
        (None, "evening", "20 agosto 2026, no queremos jugar fútbol por la tarde"),
        (
            None,
            "daytime",
            "20 agosto 2026 de día; el partido será realmente por la tarde",
        ),
        ("19:00", None, "20 August 2026 not at 19:00"),
        ("23:59", None, "Previous score was 23:59. Match 20 August 2026"),
        (None, None, "Match 20 August 2026 is not happening"),
        ("19:00", None, "Match 20 August 2026 at 19:00 is cancelled"),
        (None, "evening", "Match 20 August 2026 in the evening is cancelled"),
        (None, None, "Матч 20 августа 2026 не состоится"),
        (None, None, "Partido 20 agosto 2026 está cancelado"),
        (None, None, "Match le 20 août 2026 est annulé"),
        (None, None, "Match 20 August 2026 got cancelled"),
        ("19:00", None, "Матч 20 августа 2026 в 19:00 был отменён"),
        (None, "evening", "Partido 20 agosto 2026 por la tarde fue cancelado"),
        (None, None, "Match le 20 août 2026 a été annulé"),
    ):
        assert not _event_time_is_supported(
            date(2026, 8, 20),
            date(2026, 8, 20),
            exact_time,
            evidence,
            day_part=day_part,
        )

    for exact_time, day_part, evidence in (
        (None, None, "Match 20 August 2026 is happening"),
        (None, None, "Match 20 August 2026 is not cancelled"),
        ("19:00", None, "Матч 20 августа 2026 в 19:00 подтверждён"),
        (None, None, "Матч 20 августа 2026 не отменён"),
        (None, "evening", "Partido 20 agosto 2026 por la tarde confirmado"),
        (None, None, "Partido 20 agosto 2026 no está cancelado"),
        (None, "evening", "Match le 20 août 2026 le soir confirmé"),
        (None, None, "Match le 20 août 2026 n’est pas annulé"),
        (None, None, "Match 20 August 2026 was not cancelled"),
        ("19:00", None, "Матч 20 августа 2026 в 19:00 не был отменён"),
        (None, "evening", "Partido 20 agosto 2026 por la tarde no fue cancelado"),
        (None, None, "Match le 20 août 2026 n’a pas été annulé"),
    ):
        assert _event_time_is_supported(
            date(2026, 8, 20),
            date(2026, 8, 20),
            exact_time,
            evidence,
            day_part=day_part,
        )


def test_offline_open_player_evidence_is_complete_and_polarity_safe() -> None:
    for evidence in (
        "Need six players",
        "Need six more players",
        "Нужно шесть игроков",
        "Necesitamos seis jugadores",
        "Besoin de six joueurs",
    ):
        assert _open_places_are_supported(6, evidence)
    assert _open_places_are_supported(27, "Need 27 players")
    assert _open_places_are_supported(27, "Need 27 more players")
    assert _open_places_are_supported(11, "Need eleven players")
    assert _open_places_are_supported(27, "Need twenty seven players")
    assert _open_places_are_supported(27, "Need 27 more experienced players")
    assert _open_places_are_supported(27, "Нужно двадцать семь ещё опытных игроков")
    assert _open_places_are_supported(
        27, "Necesitamos veinte y siete jugadores experimentados"
    )
    assert _open_places_are_supported(27, "Besoin de vingt-sept joueurs expérimentés")
    for evidence in (
        "Need one hundred twenty seven experienced players",
        "Нужно сто двадцать семь опытных игроков",
        "Necesitamos ciento veintisiete jugadores",
        "Besoin de cent vingt-sept joueurs",
    ):
        assert _open_places_are_supported(127, evidence)
    assert _open_places_are_supported(80, "Besoin de quatre-vingts joueurs")
    assert _open_places_are_supported(1000, "Necesitamos mil jugadores")

    for evidence in (
        "We don’t need two players",
        "We dont need two players",
        "No longer need 2 players",
        "Больше не нужно два игрока",
        "Ya no necesitamos dos jugadores",
        "Nous ne cherchons pas deux joueurs",
        "Nous ne cherchons plus deux joueurs",
        "Nous n’avons plus besoin de deux joueurs",
        "Need two players, but both places are already filled",
        "No need for two players",
        "Two players not needed",
        "Нужно два игрока, но оба места уже заняты",
        "Necesitamos dos jugadores, pero las plazas ya están cubiertas",
        "Besoin de deux joueurs, mais les places sont déjà pourvues",
    ):
        assert not _open_places_are_supported(2, evidence)
    assert not _open_places_are_supported(1, "Need zero players")
    assert not _open_places_are_supported(2, "Need one one players")
    assert not _open_places_are_supported(31, "Need twenty eleven players")
    assert not _open_places_are_supported(2000, "Besoin de mille mille joueurs")
    for evidence in (
        "Need one thousand two hundred experienced players",
        "Нужно тысяча двести опытных игроков",
        "Necesitamos mil doscientos jugadores experimentados",
        "Besoin de mille deux cents joueurs expérimentés",
    ):
        assert _open_places_are_supported(1200, evidence)


def test_offline_payment_evidence_covers_four_locales_without_inference() -> None:
    cases = (
        ("Fee 500 EUR", ("500", "EUR")),
        ("Участие 900 рублей", ("900", "рублей")),
        ("Entrada 20 euros", ("20", "euros")),
        ("Tarif 500 CHF", ("500", "CHF")),
        ("Entrada 500 pesos", ("500", "pesos")),
        ("Участие 500 юаней", ("500", "юаней")),
        ("Fee 500 yen", ("500", "yen")),
        ("Fee 500 cad", ("500", "cad")),
        ("Tarif 500 francs suisses", ("500", "francs suisses")),
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
        ("Fee 500 euros each player", ("500", "euros")),
        ("Взнос 500 рублей за каждого игрока", ("500", "рублей")),
        ("Entrada 500 euros por cada jugador", ("500", "euros")),
        ("Tarif 500 euros pour chaque joueur", ("500", "euros")),
        ("Fee 500 Australian dollars. Contact @sample", ("500", "Australian dollars")),
        ("Взнос 500 российских рублей за игрока", ("500", "российских рублей")),
        ("Entrada 500 pesos argentinos por persona", ("500", "pesos argentinos")),
        ("Tarif 500 francs belges par joueur", ("500", "francs belges")),
    )
    for evidence, expected_details in cases:
        assert _optional_values_are_supported(
            {"payment": "paid"},
            {"payment": evidence},
        )
        assert _stated_payment_amount_and_currency(evidence) == expected_details

    assert not _optional_values_are_supported(
        {"payment": "paid"},
        {"payment": "Fee 500"},
    )
    for ambiguous_longer_name in (
        "Fee 500 euros training starts at 19:00",
        "Fee 500 euros per player parking included",
        "We will try 500 players",
        "The top 500 players qualify",
        "Need 500 all-round players",
    ):
        assert _stated_payment_amount_and_currency(ambiguous_longer_name) is None


def test_offline_optional_game_search_facts_are_affirmative() -> None:
    negated_cases: tuple[tuple[dict[str, JsonValue], dict[str, JsonValue]], ...] = (
        ({"team_formats": ["7x7"]}, {"team_formats": "Мы не играем 7x7"}),
        ({"positions": ["defender"]}, {"positions": "No necesitamos defensa"}),
        (
            {"playing_levels": ["professional"]},
            {"playing_levels": "Niveau pas professionnel"},
        ),
        ({"venue_settings": ["indoor"]}, {"venue_settings": "Not indoor"}),
        (
            {"playing_surfaces": ["artificial_turf"]},
            {"playing_surfaces": "Без искусственного газона"},
        ),
        ({"payment": "paid"}, {"payment": "La participación no es de pago"}),
        ({"payment": "free"}, {"payment": "Ce n’est pas gratuit"}),
    )
    for candidate, evidence in negated_cases:
        assert not _optional_values_are_supported(candidate, evidence)

    affirmative_cases: tuple[tuple[dict[str, JsonValue], dict[str, JsonValue]], ...] = (
        ({"team_formats": ["7x7"]}, {"team_formats": "Играем 7x7"}),
        ({"positions": ["defender"]}, {"positions": "Necesitamos defensa"}),
        (
            {"playing_levels": ["professional"]},
            {"playing_levels": "Niveau professionnel"},
        ),
        ({"venue_settings": ["indoor"]}, {"venue_settings": "Indoor"}),
        (
            {"playing_surfaces": ["artificial_turf"]},
            {"playing_surfaces": "Искусственный газон"},
        ),
        ({"payment": "paid"}, {"payment": "La participación es de pago"}),
        ({"payment": "free"}, {"payment": "C’est gratuit"}),
    )
    for candidate, evidence in affirmative_cases:
        assert _optional_values_are_supported(candidate, evidence)


def test_offline_adversarial_facts_bind_to_complete_authoritative_expressions() -> None:
    event_date = date(2026, 8, 20)
    for source_expression in (
        "Match 20 August 2026 has been called off",
        "Матч 20 августа 2026 был снят",
        "Partido 20 agosto 2026 fue retirado",
        "Match le 20 août 2026 a été retiré",
    ):
        assert not _event_time_is_supported(
            event_date,
            event_date,
            None,
            source_expression,
        )

    positive_openings = (
        ("Looking for 1,200 more experienced players", 1200),
        ("Ищем 1 200 ещё опытных игроков", 1200),
        ("Buscamos 1.200 jugadores experimentados", 1200),
        ("Nous recherchons 1 200 joueurs expérimentés", 1200),
    )
    for source_expression, open_places in positive_openings:
        assert _open_places_are_supported(open_places, source_expression)

    for source_expression in (
        "Need two players, but the request was withdrawn",
        "Нужно два игрока, но заявка была отозвана",
        "Necesitamos dos jugadores, pero la solicitud fue retirada",
        "Besoin de deux joueurs, mais la demande a été retirée",
    ):
        assert not _open_places_are_supported(2, source_expression)

    for source_expression in (
        "Fee covers all 500",
        "Entry TOP 500",
        "Payment TRY 500",
    ):
        assert _stated_payment_amount_and_currency(source_expression) is None

    for source_expression, expected in (
        ("Fee 500 euros for every player", ("500", "euros")),
        ("Взнос 500 рублей для каждого игрока", ("500", "рублей")),
        ("Entrada 500 euros para cada persona", ("500", "euros")),
        ("Tarif 500 euros pour chaque personne", ("500", "euros")),
    ):
        assert _stated_payment_amount_and_currency(source_expression) == expected

    optional_adversarial: tuple[tuple[dict[str, JsonValue], str, str], ...] = (
        ({"team_formats": ["7x7"]}, "team_formats", "7x7 was cancelled"),
        (
            {"positions": ["defender"]},
            "positions",
            "Нужен защитник, но заявка была отозвана",
        ),
        (
            {"positions": ["defender"]},
            "positions",
            "Necesitamos defensa o portero",
        ),
        (
            {"playing_levels": ["professional"]},
            "playing_levels",
            "Niveau professionnel. Le niveau n’est pas professionnel",
        ),
        (
            {"venue_settings": ["indoor"]},
            "venue_settings",
            "Indoor. It is not indoor",
        ),
        (
            {"playing_surfaces": ["artificial_turf"]},
            "playing_surfaces",
            "Искусственный газон. Поле больше не с искусственным газоном",
        ),
        (
            {"payment": "paid"},
            "payment",
            "Participation is paid. Payment was cancelled",
        ),
    )
    for candidate, field_name, source_expression in optional_adversarial:
        assert not _optional_values_are_supported(
            candidate,
            {field_name: source_expression},
        )

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
        authoritative_body=("Football match 20 August 2026. Parking is paid"),
    )
    assert not _optional_values_are_supported(
        {"positions": ["defender"]},
        {"positions": "Need a defender"},
        authoritative_body=(
            "Football match 20 August 2026. Need a defender. "
            "We later withdrew the opening"
        ),
    )


def test_classifier_contract_accepts_an_evidence_backed_phone_route() -> None:
    corpus_path = Path(__file__).with_name("corpus.v1.json")
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    output = deepcopy(corpus["cases"][0]["recorded_output"])
    source = corpus["cases"][0]["source"].replace("@sample_contact", "+7 921 555-01-49")
    output["candidates"][0]["response_routes"] = [
        {
            "kind": "explicit_phone",
            "value": "+7 921 555-01-49",
            "evidence": "+7 921 555-01-49",
        }
    ]

    assert classifier_output_is_schema_valid(output, body=source)


def test_offline_authority_boundary_rejects_non_authoritative_facts() -> None:
    for body in (
        "Football match is not intended for individual players. "
        "20 August 2026 at Central Station. Need one player. "
        "Contact @match_contact",
        "Футбольный матч не предназначен для отдельных игроков. "
        "20 августа 2026 у Центральной. Нужен один игрок. "
        "Контакт @match_contact",
        "El partido de fútbol no está destinado a jugadores individuales. "
        "20 agosto 2026 en Estación Central. Necesitamos un jugador. "
        "Contacto @match_contact",
        "Le match de football n'est pas destiné aux joueurs individuels. "
        "20 août 2026 à la Gare Centrale. Besoin d'un joueur. "
        "Contact @match_contact",
    ):
        assert not _body_establishes_current_open_match(body)

    for body in (
        "Practice 20 August 2026 at Central Station. Need two players",
        "Тренировка 20 августа 2026 у Центральной. Нужны два игрока",
        "Partido o entrenamiento 20 agosto 2026 en Estación Central",
        "Match ou entraînement le 20 août 2026 à la Gare Centrale",
    ):
        assert not _body_establishes_current_open_match(body)

    for body, mention in (
        ("Football match not at Central Station", "Central Station"),
        ("Матч не у Центральной", "Центральной"),
        ("Partido no en Estación Central", "Estación Central"),
        ("Match pas à la Gare Centrale", "Gare Centrale"),
    ):
        assert not _location_mention_is_authoritative(body, mention)

    fallback: JsonValue = {"reply_route_url": "https://t.me/source_chat/49?comment=1"}
    for body in (
        "Venue page @stadium. Reply here",
        "Страница площадки @stadium. Ответьте здесь",
        "Página del campo @stadium. Responde aquí",
        "Page du terrain @stadium. Répondez ici",
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


def test_classifier_contract_accepts_an_evidence_backed_url_route() -> None:
    corpus_path = Path(__file__).with_name("corpus.v1.json")
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    output = deepcopy(corpus["cases"][0]["recorded_output"])
    source = corpus["cases"][0]["source"].replace(
        "@sample_contact", "https://example.test/open-match/49"
    )
    output["candidates"][0]["response_routes"] = [
        {
            "kind": "explicit_url",
            "value": "https://example.test/open-match/49",
            "evidence": "https://example.test/open-match/49",
        }
    ]

    assert classifier_output_is_schema_valid(output, body=source)


def test_classifier_contract_leaves_source_metadata_fallback_to_application() -> None:
    corpus_path = Path(__file__).with_name("corpus.v1.json")
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    output = deepcopy(corpus["cases"][0]["recorded_output"])
    source = corpus["cases"][0]["source"].replace(" Пишите @sample_contact", "")
    output["candidates"][0]["response_routes"] = []

    assert classifier_output_is_schema_valid(output, body=source)


def test_classifier_contract_preserves_unknown_optional_open_place_count() -> None:
    corpus_path = Path(__file__).with_name("corpus.v1.json")
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    output = deepcopy(corpus["cases"][0]["recorded_output"])
    source = corpus["cases"][0]["source"].replace(
        "Нужно одно место, защитник", "Ищем защитника"
    )
    candidate = output["candidates"][0]
    candidate["evidence"]["opportunity"] = "Ищем защитника"
    candidate["evidence"]["open_places"] = "Ищем защитника"
    candidate["open_places"] = None

    assert classifier_output_is_schema_valid(output, body=source)


def test_classifier_contract_accepts_a_source_stated_day_part() -> None:
    corpus_path = Path(__file__).with_name("corpus.v1.json")
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    output = deepcopy(corpus["cases"][0]["recorded_output"])
    source = corpus["cases"][0]["source"].replace(
        "25 сентября 2026 в 20:00", "25 сентября 2026 вечером"
    )
    candidate = output["candidates"][0]
    candidate["evidence"]["event_time"] = "25 сентября 2026 вечером"
    del candidate["event_time"]["exact_local_time"]
    candidate["event_time"]["day_part"] = "evening"

    assert classifier_output_is_schema_valid(output, body=source)
