from __future__ import annotations

from collections.abc import Callable, Mapping
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request

from modules.application import _resolve_source_location_across_supported_locales
from modules.domain import (
    ConversationStage,
    GeographicType,
    LocationResolutionQuery,
)
from modules.geonames_location_resolver import (
    GEONAMES_MAX_REQUESTS_PER_HOUR,
    GeoNamesHttpTransport,
    GeoNamesLocationResolverAdapter,
)
from modules.ports import LocationResolverError


class ScriptedGeoNamesTransport:
    def __init__(
        self,
        responses: Mapping[
            str,
            Mapping[str, object]
            | Callable[[Mapping[str, str | tuple[str, ...]]], Mapping[str, object]],
        ],
    ) -> None:
        self.responses = dict(responses)
        self.calls: list[tuple[str, dict[str, str | tuple[str, ...]], float]] = []

    def get_json(
        self,
        endpoint: str,
        *,
        params: Mapping[str, str | tuple[str, ...]],
        timeout_seconds: float,
    ) -> Mapping[str, object]:
        self.calls.append((endpoint, dict(params), timeout_seconds))
        response = self.responses[endpoint]
        return response(params) if callable(response) else response


def test_two_production_resolvers_stay_inside_geonames_daily_credit_budget() -> None:
    assert GEONAMES_MAX_REQUESTS_PER_HOUR * 2 * 24 <= 10_000


def test_geo_names_rate_limit_fails_closed_without_a_provider_retry() -> None:
    transport = ScriptedGeoNamesTransport({"searchJSON": {"geonames": []}})
    adapter = GeoNamesLocationResolverAdapter(
        username="controlled-user",
        transport=transport,
        requests_per_hour=1,
    )
    first_query = LocationResolutionQuery(
        text="first", locale="en", stage=ConversationStage.COUNTRY
    )
    second_query = LocationResolutionQuery(
        text="second", locale="en", stage=ConversationStage.COUNTRY
    )

    assert adapter.resolve(first_query).interpretations == ()
    try:
        adapter.resolve(second_query)
    except LocationResolverError as error:
        assert str(error) == "location provider rate limit is exhausted"
    else:
        raise AssertionError("request beyond local rate budget was accepted")
    assert len(transport.calls) == 1


def test_http_transport_repeats_geo_names_feature_class_parameters() -> None:
    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, _limit: int) -> bytes:
            return b'{"geonames": []}'

    requests: list[tuple[Request, float]] = []

    def opener(request: Request, *, timeout: float) -> Response:
        requests.append((request, timeout))
        return Response()

    transport = GeoNamesHttpTransport(opener=opener)
    transport.get_json(
        "searchJSON",
        params={
            "featureClass": ("A", "P", "S", "L", "H"),
            "username": "controlled-user",
        },
        timeout_seconds=3.0,
    )

    request, timeout = requests[0]
    assert timeout == 3.0
    assert parse_qs(urlsplit(request.full_url).query) == {
        "featureClass": ["A", "P", "S", "L", "H"],
        "username": ["controlled-user"],
    }


def test_country_candidate_uses_stable_geonames_identity_and_locale() -> None:
    transport = ScriptedGeoNamesTransport(
        {
            "searchJSON": {
                "geonames": [
                    {
                        "geonameId": 2510769,
                        "name": "España",
                        "toponymName": "Spain",
                        "countryCode": "ES",
                        "fcl": "A",
                        "fcode": "PCLI",
                    }
                ]
            }
        }
    )
    adapter = GeoNamesLocationResolverAdapter(
        username="controlled-user",
        transport=transport,
    )

    resolution = adapter.resolve(
        LocationResolutionQuery(
            text="España",
            locale="es",
            stage=ConversationStage.COUNTRY,
        )
    )

    assert len(resolution.interpretations) == 1
    candidate = resolution.interpretations[0].places[0]
    assert candidate.place_id == "geonames:2510769"
    assert candidate.country_id == candidate.place_id
    assert candidate.city_id is None
    assert candidate.geographic_type is GeographicType.COUNTRY
    assert dict(candidate.localized_display_names) == {
        "en": "Spain",
        "es": "España",
        "fr": "Spain",
        "ru": "Spain",
    }
    assert transport.calls == [
        (
            "searchJSON",
            {
                "featureCode": "PCLI",
                "lang": "es",
                "maxRows": "5",
                "q": "España",
                "username": "controlled-user",
            },
            3.0,
        )
    ]


def test_city_candidate_requires_geonames_ancestry_and_installed_timezone() -> None:
    transport = ScriptedGeoNamesTransport(
        {
            "getJSON": {
                "geonameId": 100,
                "name": "Россия",
                "toponymName": "Russia",
                "countryCode": "RU",
                "fcl": "A",
                "fcode": "PCLI",
            },
            "searchJSON": {
                "geonames": [
                    {
                        "geonameId": 200,
                        "name": "Санкт-Петербург",
                        "toponymName": "Saint Petersburg",
                        "countryCode": "RU",
                        "fcl": "P",
                        "fcode": "PPLA",
                        "timezone": {"timeZoneId": "Europe/Moscow"},
                    }
                ]
            },
            "hierarchyJSON": {
                "geonames": [
                    {"geonameId": 999, "name": "Earth", "fcode": "AREA"},
                    {"geonameId": 998, "name": "Europe", "fcode": "CONT"},
                    {"geonameId": 100, "name": "Россия", "fcode": "PCLI"},
                    {"geonameId": 101, "name": "Северо-Запад", "fcode": "ADM1"},
                ]
            },
        }
    )
    adapter = GeoNamesLocationResolverAdapter(
        username="controlled-user",
        transport=transport,
    )

    resolution = adapter.resolve(
        LocationResolutionQuery(
            text="Санкт-Петербург",
            locale="ru",
            stage=ConversationStage.CITY,
            country_id="geonames:100",
        )
    )

    assert len(resolution.interpretations) == 1
    candidate = resolution.interpretations[0].places[0]
    assert candidate.place_id == "geonames:200"
    assert candidate.city_id == candidate.place_id
    assert candidate.country_id == "geonames:100"
    assert candidate.geographic_type is GeographicType.CITY
    assert candidate.verified_parent_ids == ("geonames:101", "geonames:100")
    assert candidate.parent_display_names == ("Северо-Запад", "Россия")
    assert candidate.iana_timezone == "Europe/Moscow"
    assert [call[0] for call in transport.calls] == [
        "getJSON",
        "searchJSON",
        "hierarchyJSON",
    ]


def test_search_area_keeps_city_and_country_as_verified_terminal_parents() -> None:
    transport = ScriptedGeoNamesTransport(
        {
            "getJSON": {
                "geonameId": 100,
                "name": "Russia",
                "toponymName": "Russia",
                "countryCode": "RU",
                "fcl": "A",
                "fcode": "PCLI",
            },
            "searchJSON": {
                "geonames": [
                    {
                        "geonameId": 300,
                        "name": "Komendantsky Prospekt",
                        "toponymName": "Komendantsky Prospekt",
                        "countryCode": "RU",
                        "fcl": "S",
                        "fcode": "STTN",
                    }
                ]
            },
            "hierarchyJSON": {
                "geonames": [
                    {"geonameId": 999, "name": "Earth", "fcode": "AREA"},
                    {"geonameId": 998, "name": "Europe", "fcode": "CONT"},
                    {"geonameId": 100, "name": "Russia", "fcode": "PCLI"},
                    {"geonameId": 101, "name": "Northwestern", "fcode": "ADM1"},
                    {"geonameId": 200, "name": "Saint Petersburg", "fcode": "PPLA"},
                    {"geonameId": 201, "name": "Primorsky", "fcode": "ADM2"},
                ]
            },
        }
    )
    adapter = GeoNamesLocationResolverAdapter(
        username="controlled-user",
        transport=transport,
    )

    resolution = adapter.resolve(
        LocationResolutionQuery(
            text="Komendantsky Prospekt",
            locale="en",
            stage=ConversationStage.SEARCH_AREA,
            country_id="geonames:100",
            city_id="geonames:200",
        )
    )

    assert len(resolution.interpretations) == 1
    candidate = resolution.interpretations[0].places[0]
    assert candidate.geographic_type is GeographicType.STATION
    assert candidate.verified_parent_ids[-2:] == (
        "geonames:200",
        "geonames:100",
    )
    assert candidate.parent_display_names[-2:] == (
        "Saint Petersburg",
        "Russia",
    )
    assert any(
        call[1].get("featureClass") == ("A", "P", "S", "L", "H")
        for call in transport.calls
    )


def test_whole_city_phrase_uses_confirmed_city_without_searching_its_name() -> None:
    def place_by_id(
        params: Mapping[str, str | tuple[str, ...]],
    ) -> Mapping[str, object]:
        if params["geonameId"] == "100":
            return {
                "geonameId": 100,
                "name": "Russia",
                "toponymName": "Russia",
                "countryCode": "RU",
                "fcl": "A",
                "fcode": "PCLI",
            }
        return {
            "geonameId": 200,
            "name": "Saint Petersburg",
            "toponymName": "Saint Petersburg",
            "countryCode": "RU",
            "fcl": "P",
            "fcode": "PPLA",
            "timezone": {"timeZoneId": "Europe/Moscow"},
        }

    transport = ScriptedGeoNamesTransport(
        {
            "getJSON": place_by_id,
            "hierarchyJSON": {
                "geonames": [{"geonameId": 100, "name": "Russia", "fcode": "PCLI"}]
            },
        }
    )
    adapter = GeoNamesLocationResolverAdapter(
        username="controlled-user",
        transport=transport,
    )

    resolution = adapter.resolve(
        LocationResolutionQuery(
            text="Anywhere in the whole city works",
            locale="en",
            stage=ConversationStage.SEARCH_AREA,
            country_id="geonames:100",
            city_id="geonames:200",
        )
    )

    assert len(resolution.interpretations) == 1
    interpretation = resolution.interpretations[0]
    assert interpretation.whole_city is True
    assert len(interpretation.places) == 1
    assert interpretation.places[0].place_id == "geonames:200"
    assert [call[0] for call in transport.calls] == [
        "getJSON",
        "getJSON",
        "hierarchyJSON",
    ]


def test_nonempty_geonames_result_passes_application_location_contract() -> None:
    country_id = "geonames:100"
    city_id = "geonames:200"
    place_id = "geonames:300"
    transport = ScriptedGeoNamesTransport(
        {
            "getJSON": lambda _params: {
                "geonameId": 100,
                "name": "Russia",
                "toponymName": "Russia",
                "countryCode": "RU",
                "fcl": "A",
                "fcode": "PCLI",
            },
            "searchJSON": {
                "geonames": [
                    {
                        "geonameId": 300,
                        "name": "Komendantsky Prospekt",
                        "toponymName": "Komendantsky Prospekt",
                        "countryCode": "RU",
                        "fcl": "S",
                        "fcode": "STTN",
                    }
                ]
            },
            "hierarchyJSON": {
                "geonames": [
                    {"geonameId": 100, "name": "Russia", "fcode": "PCLI"},
                    {
                        "geonameId": 200,
                        "name": "Saint Petersburg",
                        "fcode": "PPLA",
                    },
                ]
            },
        }
    )
    adapter = GeoNamesLocationResolverAdapter(
        username="controlled-user",
        transport=transport,
    )

    accepted = _resolve_source_location_across_supported_locales(
        adapter,
        mention="Komendantsky Prospekt",
        country_id=country_id,
        city_id=city_id,
    )

    assert accepted is not None
    candidate, city_labels = accepted
    assert candidate.place_id == place_id
    assert candidate.geographic_type is GeographicType.STATION
    assert candidate.glossary_version == "location-glossary-v1"
    assert candidate.verified_parent_ids == (city_id, country_id)
    assert city_labels == dict.fromkeys(("en", "es", "fr", "ru"), "Saint Petersburg")
