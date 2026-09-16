from __future__ import annotations

from collections.abc import Callable, Mapping
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request

import modules.domain as domain
from modules.application import _resolve_source_location_across_supported_locales
from modules.domain import (
    ConversationStage,
    GeographicType,
    LocationCandidate,
    LocationResolutionQuery,
)
from modules.geonames_location_resolver import (
    GEONAMES_MAX_REQUESTS_PER_HOUR,
    GeoNamesHttpTransport,
    GeoNamesLocationResolverAdapter,
    LocationIQHttpTransport,
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


class ScriptedLocationIQTransport:
    def __init__(self, response: list[Mapping[str, object]]) -> None:
        self.response = response
        self.calls: list[tuple[dict[str, str], float]] = []

    def get_json(
        self,
        *,
        params: Mapping[str, str],
        timeout_seconds: float,
    ) -> list[Mapping[str, object]]:
        self.calls.append((dict(params), timeout_seconds))
        return self.response


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
    assert urlsplit(request.full_url).hostname == "secure.geonames.org"
    assert parse_qs(urlsplit(request.full_url).query) == {
        "featureClass": ["A", "P", "S", "L", "H"],
        "username": ["controlled-user"],
    }


def test_locationiq_http_transport_bounds_and_encodes_structured_search() -> None:
    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, _limit: int) -> bytes:
            return b'[{"osm_type":"node","osm_id":1}]'

    requests: list[tuple[Request, float]] = []

    def opener(request: Request, *, timeout: float) -> Response:
        requests.append((request, timeout))
        return Response()

    transport = LocationIQHttpTransport(opener=opener)
    response = transport.get_json(
        params={
            "format": "json",
            "key": "controlled-token",
            "street": "221B Baker Street",
        },
        timeout_seconds=3.0,
    )

    assert response == [{"osm_type": "node", "osm_id": 1}]
    request, timeout = requests[0]
    assert timeout == 3.0
    assert parse_qs(urlsplit(request.full_url).query) == {
        "format": ["json"],
        "key": ["controlled-token"],
        "street": ["221B Baker Street"],
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

    query = LocationResolutionQuery(
        text="España",
        locale="es",
        stage=ConversationStage.COUNTRY,
    )
    resolution = adapter.resolve(query)

    assert len(resolution.interpretations) == 1
    candidate = resolution.interpretations[0].places[0]
    assert type(candidate) is domain.SearchAreaCandidate
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
    search_area_interpretations = adapter.resolve_search_area(query)
    assert len(search_area_interpretations) == 1
    assert search_area_interpretations[0].candidates == (candidate,)
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

    query = LocationResolutionQuery(
        text="Санкт-Петербург",
        locale="ru",
        stage=ConversationStage.CITY,
        country_id="geonames:100",
    )
    resolution = adapter.resolve(query)

    assert len(resolution.interpretations) == 1
    candidate = resolution.interpretations[0].places[0]
    assert type(candidate) is domain.SearchAreaCandidate
    assert candidate.place_id == "geonames:200"
    assert candidate.city_id == candidate.place_id
    assert candidate.country_id == "geonames:100"
    assert candidate.geographic_type is GeographicType.CITY
    assert candidate.verified_parent_ids == ("geonames:101", "geonames:100")
    assert candidate.parent_display_names == ("Северо-Запад", "Россия")
    assert candidate.iana_timezone == "Europe/Moscow"
    search_area_interpretations = adapter.resolve_search_area(query)
    assert len(search_area_interpretations) == 1
    assert search_area_interpretations[0].candidates == (candidate,)
    assert [call[0] for call in transport.calls] == [
        "getJSON",
        "searchJSON",
        "hierarchyJSON",
    ]


def test_search_area_uses_its_own_candidate_model_and_verified_parents() -> None:
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

    interpretations = adapter.resolve_search_area(
        LocationResolutionQuery(
            text="Komendantsky Prospekt",
            locale="en",
            stage=ConversationStage.SEARCH_AREA,
            country_id="geonames:100",
            city_id="geonames:200",
        )
    )

    assert len(interpretations) == 1
    candidate = interpretations[0].candidates[0]
    assert type(candidate) is domain.SearchAreaCandidate
    assert not isinstance(candidate, LocationCandidate)
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


def test_bare_street_resolution_includes_source_message_path() -> None:
    def search(
        params: Mapping[str, str | tuple[str, ...]],
    ) -> Mapping[str, object]:
        if (
            params.get("q") not in {"Baker Street", "221B Baker Street"}
            or params.get("featureClass") != "R"
            or params.get("featureCode") != "ST"
        ):
            return {"geonames": []}
        return {
            "geonames": [
                {
                    "geonameId": 300,
                    "name": "Baker Street",
                    "toponymName": "Baker Street",
                    "countryCode": "RU",
                    "fcl": "R",
                    "fcode": "ST",
                }
            ]
        }

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
            "searchJSON": search,
            "hierarchyJSON": {
                "geonames": [
                    {"geonameId": 999, "name": "Earth", "fcode": "AREA"},
                    {"geonameId": 998, "name": "Europe", "fcode": "CONT"},
                    {"geonameId": 100, "name": "Russia", "fcode": "PCLI"},
                    {"geonameId": 101, "name": "Northwestern", "fcode": "ADM1"},
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

    bare_interpretations = adapter.resolve_search_area(
        LocationResolutionQuery(
            text="Baker Street",
            locale="en",
            stage=ConversationStage.SEARCH_AREA,
            country_id="geonames:100",
            city_id="geonames:200",
        )
    )

    assert len(bare_interpretations) == 1
    candidate = bare_interpretations[0].candidates[0]
    assert type(candidate) is domain.SearchAreaCandidate
    assert candidate.place_id == "geonames:300"
    assert candidate.geographic_type.value == "street"
    assert candidate.localized_display_names == tuple(
        (locale, "Baker Street") for locale in ("en", "es", "fr", "ru")
    )
    assert candidate.verified_parent_ids[-2:] == (
        "geonames:200",
        "geonames:100",
    )
    assert candidate.parent_display_names[-2:] == ("Saint Petersburg", "Russia")
    legacy_bare = adapter.resolve(
        LocationResolutionQuery(
            text="Baker Street",
            locale="en",
            stage=ConversationStage.SEARCH_AREA,
            country_id="geonames:100",
            city_id="geonames:200",
        )
    )
    assert type(legacy_bare.interpretations[0].places[0]) is domain.SearchAreaCandidate
    assert legacy_bare.interpretations[0].places[0].geographic_type.value == "street"
    calls_before_numbered_query = len(transport.calls)
    numbered_interpretations = adapter.resolve_search_area(
        LocationResolutionQuery(
            text="221B Baker Street",
            locale="en",
            stage=ConversationStage.SEARCH_AREA,
            country_id="geonames:100",
            city_id="geonames:200",
        )
    )
    assert numbered_interpretations == ()
    numbered_search_calls = transport.calls[calls_before_numbered_query:]
    assert not any(call[0] == "searchJSON" for call in numbered_search_calls)
    legacy_numbered = adapter.resolve(
        LocationResolutionQuery(
            text="221B Baker Street",
            locale="en",
            stage=ConversationStage.SEARCH_AREA,
            country_id="geonames:100",
            city_id="geonames:200",
        )
    )
    assert legacy_numbered.interpretations == ()

    message_interpretations = adapter.resolve_location_mention(
        LocationResolutionQuery(
            text="Baker Street",
            locale="en",
            stage=ConversationStage.SEARCH_AREA,
            country_id="geonames:100",
            city_id="geonames:200",
        )
    ).interpretations

    assert len(message_interpretations) == 1
    message_candidate = message_interpretations[0].places[0]
    assert type(message_candidate) is LocationCandidate
    assert message_candidate.place_id == "geonames:300"
    assert message_candidate.geographic_type is GeographicType.STREET
    assert message_candidate.verified_parent_ids == (
        "geonames:200",
        "geonames:100",
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

    query = LocationResolutionQuery(
        text="Anywhere in the whole city works",
        locale="en",
        stage=ConversationStage.SEARCH_AREA,
        country_id="geonames:100",
        city_id="geonames:200",
    )
    resolution = adapter.resolve(query)

    assert len(resolution.interpretations) == 1
    interpretation = resolution.interpretations[0]
    assert type(interpretation.places[0]) is domain.SearchAreaCandidate
    assert interpretation.whole_city is True
    assert len(interpretation.places) == 1
    assert interpretation.places[0].place_id == "geonames:200"
    search_area_interpretations = adapter.resolve_search_area(query)
    assert len(search_area_interpretations) == 1
    assert search_area_interpretations[0].candidates == ()
    assert search_area_interpretations[0].whole_city is True
    assert search_area_interpretations[0].resolver_version == "geonames-ws-v1"
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
    assert type(candidate) is LocationCandidate
    assert candidate.geographic_type is GeographicType.STATION
    assert candidate.glossary_version == "location-glossary-v1"
    assert candidate.verified_parent_ids == (city_id, country_id)
    assert city_labels == dict.fromkeys(("en", "es", "fr", "ru"), "Saint Petersburg")


def test_explicit_address_requires_provider_verified_point_and_city_timezone() -> None:
    geo_names = ScriptedGeoNamesTransport(
        {
            "getJSON": lambda params: (
                {
                    "geonameId": 100,
                    "name": "Russia",
                    "toponymName": "Russia",
                    "countryCode": "RU",
                    "fcl": "A",
                    "fcode": "PCLI",
                }
                if params["geonameId"] == "100"
                else {
                    "geonameId": 200,
                    "name": "Saint Petersburg",
                    "toponymName": "Saint Petersburg",
                    "countryCode": "RU",
                    "fcl": "P",
                    "fcode": "PPLA",
                    "timezone": {"timeZoneId": "Europe/Moscow"},
                }
            ),
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
    location_iq = ScriptedLocationIQTransport(
        [
            {
                "osm_type": "way",
                "osm_id": 12345,
                "display_name": "221B Baker Street, Saint Petersburg, Russia",
                "lat": "59.9386",
                "lon": "30.3141",
                "address": {
                    "house_number": "221B",
                    "road": "Baker Street",
                    "city": "Saint Petersburg",
                    "country_code": "ru",
                },
                "matchquality": {
                    "matchcode": "exact",
                    "matchtype": "point",
                    "matchlevel": "building",
                },
            }
        ]
    )
    adapter = GeoNamesLocationResolverAdapter(
        username="controlled-user",
        transport=geo_names,
        locationiq_access_token="controlled-locationiq-token",
        locationiq_transport=location_iq,
    )
    query = LocationResolutionQuery(
        text="221B Baker Street",
        locale="en",
        stage=ConversationStage.SEARCH_AREA,
        country_id="geonames:100",
        city_id="geonames:200",
    )

    search_area = adapter.resolve_search_area(query)
    assert len(search_area) == 1
    area = search_area[0].candidates[0]
    assert type(area) is domain.SearchAreaCandidate
    assert area.place_id == "osm:way:12345"
    assert area.geographic_type is GeographicType.ADDRESS
    assert area.verified_parent_ids == ("geonames:200", "geonames:100")
    assert area.iana_timezone == "Europe/Moscow"
    assert location_iq.calls[0][0] == {
        "accept-language": "en",
        "addressdetails": "1",
        "city": "Saint Petersburg",
        "countrycodes": "ru",
        "format": "json",
        "key": "controlled-locationiq-token",
        "limit": "5",
        "matchquality": "1",
        "normalizeaddress": "1",
        "normalizecity": "1",
        "source": "nom",
        "street": "221B Baker Street",
    }

    source = adapter.resolve_location_mention(query).interpretations
    assert len(source) == 1
    source_candidate = source[0].places[0]
    assert type(source_candidate) is LocationCandidate
    assert source_candidate.geographic_type is GeographicType.ADDRESS
    assert source_candidate.iana_timezone == "Europe/Moscow"

    mismatched_road = ScriptedLocationIQTransport(
        [
            {
                **location_iq.response[0],
                "address": {
                    "house_number": "221B",
                    "road": "Wrong Road",
                    "city": "Saint Petersburg",
                    "country_code": "ru",
                },
            }
        ]
    )
    unresolved_mismatched_road = GeoNamesLocationResolverAdapter(
        username="controlled-user",
        transport=geo_names,
        locationiq_access_token="controlled-locationiq-token",
        locationiq_transport=mismatched_road,
    ).resolve_search_area(query)
    assert unresolved_mismatched_road == ()

    interpolation = ScriptedLocationIQTransport(
        [
            {
                **location_iq.response[0],
                "matchquality": {
                    "matchcode": "exact",
                    "matchtype": "interpolated",
                    "matchlevel": "building",
                },
            }
        ]
    )
    unresolved = GeoNamesLocationResolverAdapter(
        username="controlled-user",
        transport=geo_names,
        locationiq_access_token="controlled-locationiq-token",
        locationiq_transport=interpolation,
    ).resolve_search_area(query)
    assert unresolved == ()
    assert not any(call[0] == "searchJSON" for call in geo_names.calls)
