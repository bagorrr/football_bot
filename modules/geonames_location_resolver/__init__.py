"""Fail-closed GeoNames implementation of the application location port."""

from __future__ import annotations

import json
import re
from collections import OrderedDict, deque
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from time import monotonic
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from modules.domain import (
    ConversationStage,
    GeographicType,
    LocationCandidate,
    LocationInterpretation,
    LocationResolution,
    LocationResolutionQuery,
)
from modules.ports import LocationResolverError

GEONAMES_RESOLVER_VERSION = "geonames-ws-v1"
GEONAMES_GLOSSARY_VERSION = "geonames-feature-map-v1"
GEONAMES_BASE_URL = "https://api.geonames.org/"
GEONAMES_MAX_ROWS = 5
GEONAMES_MAX_REQUESTS_PER_HOUR = 100
_MAX_CACHE_SIZE = 2_048
_MAX_CACHE_TTL_SECONDS = 86_400.0
_MAX_QUERY_LENGTH = 240
_MAX_SEARCH_AREA_PARTS = 8
_SUPPORTED_LOCALES = ("en", "es", "fr", "ru")
_LOCALE_PATTERN = re.compile(r"[a-z]{2,3}(?:-[a-z0-9]{2,8})*")
_ID_PATTERN = re.compile(r"geonames:([1-9][0-9]{0,11})")
_CITY_CODES = frozenset({"PPLC", "PPLA", "PPLA2", "PPLA3", "PPLA4", "PPLA5"})
_STATION_CODES = frozenset({"BUSTN", "MTRO", "RSTN", "STTN"})
_TRANSPORT_CODES = frozenset({"AIRF", "AIRP", "PRT"})
_LANDMARK_CODES = frozenset({"BLDG", "CH", "MUS", "PARK", "STDM", "THTR"})
_API_ENDPOINTS = frozenset({"getJSON", "hierarchyJSON", "searchJSON"})
_WHOLE_CITY_PHRASES = {
    "en": frozenset(
        {
            "whole city",
            "the whole city",
            "anywhere in the whole city",
            "anywhere in the whole city works",
        }
    ),
    "es": frozenset({"toda la ciudad", "toda la ciudad funciona"}),
    "fr": frozenset({"toute la ville", "toute la ville convient"}),
    "ru": frozenset({"весь город", "вся территория города"}),
}


class GeoNamesTransport(Protocol):
    """Small JSON boundary for deterministic adapter conformance tests."""

    def get_json(
        self,
        endpoint: str,
        *,
        params: Mapping[str, str | tuple[str, ...]],
        timeout_seconds: float,
    ) -> Mapping[str, object]:
        """Return one bounded GeoNames JSON response."""
        ...


class GeoNamesHttpTransport:
    """HTTPS-only, bounded standard-library client for GeoNames JSON APIs."""

    def __init__(
        self,
        *,
        opener: Callable[..., Any] = urlopen,
        max_response_bytes: int = 256_000,
    ) -> None:
        if type(max_response_bytes) is not int or max_response_bytes < 1:
            raise ValueError("GeoNames response limit must be positive")
        self._opener = opener
        self._max_response_bytes = max_response_bytes

    def get_json(
        self,
        endpoint: str,
        *,
        params: Mapping[str, str | tuple[str, ...]],
        timeout_seconds: float,
    ) -> Mapping[str, object]:
        """Fetch one allow-listed API response without retaining request data."""
        if endpoint not in _API_ENDPOINTS:
            raise LocationResolverError("location provider endpoint is unsupported")
        if not 0 < timeout_seconds <= 10:
            raise LocationResolverError("location provider timeout is invalid")
        request = Request(
            f"{GEONAMES_BASE_URL}{endpoint}?{urlencode(params, doseq=True)}",
            headers={
                "Accept": "application/json",
                "User-Agent": "football-bot-geonames-location-resolver/1.0",
            },
        )
        try:
            with self._opener(request, timeout=timeout_seconds) as response:
                payload = response.read(self._max_response_bytes + 1)
        except (HTTPError, URLError, TimeoutError, OSError):
            raise LocationResolverError("location provider request failed") from None
        if len(payload) > self._max_response_bytes:
            raise LocationResolverError("location provider response is oversized")
        try:
            decoded = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
            raise LocationResolverError(
                "location provider response is malformed"
            ) from None
        if not isinstance(decoded, dict) or "status" in decoded:
            raise LocationResolverError("location provider response is unavailable")
        return decoded


@dataclass(frozen=True, slots=True)
class _CachedResponse:
    expires_at: float
    value: Mapping[str, object]


class GeoNamesLocationResolverAdapter:
    """Resolve stable candidates, admitting only verified GeoNames ancestry."""

    def __init__(
        self,
        *,
        username: str,
        transport: GeoNamesTransport | None = None,
        timeout_seconds: float = 3.0,
        requests_per_hour: int = GEONAMES_MAX_REQUESTS_PER_HOUR,
        cache_ttl_seconds: float = _MAX_CACHE_TTL_SECONDS,
        cache_capacity: int = _MAX_CACHE_SIZE,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if not isinstance(username, str) or not username.strip():
            raise ValueError("GeoNames username is required")
        if username.strip() != username or len(username) > 64:
            raise ValueError("GeoNames username is malformed")
        if not 0 < timeout_seconds <= 10:
            raise ValueError("GeoNames timeout must be between 0 and 10 seconds")
        if type(requests_per_hour) is not int or not 1 <= requests_per_hour <= (
            GEONAMES_MAX_REQUESTS_PER_HOUR
        ):
            raise ValueError("GeoNames request rate exceeds the provider limit")
        if not 0 < cache_ttl_seconds <= _MAX_CACHE_TTL_SECONDS:
            raise ValueError("GeoNames cache duration is outside the supported range")
        if (
            type(cache_capacity) is not int
            or not 1 <= cache_capacity <= _MAX_CACHE_SIZE
        ):
            raise ValueError("GeoNames cache capacity is outside the supported range")
        self._username = username
        self._transport = transport or GeoNamesHttpTransport()
        self._timeout_seconds = timeout_seconds
        self._requests_per_hour = requests_per_hour
        self._cache_ttl_seconds = cache_ttl_seconds
        self._cache_capacity = cache_capacity
        self._clock = clock
        self._cache: OrderedDict[
            tuple[str, tuple[tuple[str, str | tuple[str, ...]], ...]], _CachedResponse
        ] = OrderedDict()
        self._request_times: deque[float] = deque()

    def opportunity_revision_id(self, proposal_id: str) -> str:
        """Return a namespaced synthetic revision identity for the app port."""
        if (
            not isinstance(proposal_id, str)
            or not proposal_id
            or len(proposal_id) > 256
        ):
            raise ValueError("Opportunity proposal identity is invalid")
        return f"opportunity-revision:{proposal_id}"

    def resolve(self, query: LocationResolutionQuery) -> LocationResolution:
        """Return one or more provider-backed interpretations, or fail closed."""
        normalized = _validated_query(query)
        if normalized.stage is ConversationStage.COUNTRY:
            return self._resolve_country(normalized)
        country_code = self._country_code(normalized.country_id, normalized.locale)
        if country_code is None:
            return LocationResolution(interpretations=())
        if normalized.stage is ConversationStage.CITY:
            return self._resolve_city(normalized, country_code)
        if normalized.stage is ConversationStage.SEARCH_AREA:
            return self._resolve_search_area(normalized, country_code)
        raise LocationResolverError("location stage is unsupported")

    def _resolve_country(self, query: LocationResolutionQuery) -> LocationResolution:
        records = self._search(
            query,
            feature_code="PCLI",
        )
        candidates: list[LocationCandidate] = []
        for record in records:
            if record.get("fcode") != "PCLI":
                continue
            place_id = _place_id(record)
            name = _localized_name(record)
            if place_id is None or name is None:
                continue
            candidates.append(
                LocationCandidate(
                    place_id=place_id,
                    display_name=name,
                    geographic_type=GeographicType.COUNTRY,
                    country_id=place_id,
                    city_id=None,
                    verified_parent_ids=(),
                    parent_display_names=(),
                    iana_timezone=None,
                    resolver_version=GEONAMES_RESOLVER_VERSION,
                    glossary_version=GEONAMES_GLOSSARY_VERSION,
                    localized_display_names=_localized_names(record, query.locale),
                )
            )
        return LocationResolution(
            interpretations=tuple(
                LocationInterpretation(
                    places=(candidate,), glossary_version=GEONAMES_GLOSSARY_VERSION
                )
                for candidate in _unique_candidates(candidates)
            )
        )

    def _resolve_city(
        self, query: LocationResolutionQuery, country_code: str
    ) -> LocationResolution:
        records = self._search(
            query,
            country_code=country_code,
            feature_class="P",
        )
        candidates: list[LocationCandidate] = []
        for record in records:
            if record.get("fcode") not in _CITY_CODES:
                continue
            candidate = self._build_candidate(
                record,
                query,
                country_id=query.country_id or "",
                geographic_type=GeographicType.CITY,
                city_id=None,
            )
            if candidate is not None:
                candidates.append(candidate)
        return LocationResolution(
            interpretations=tuple(
                LocationInterpretation(
                    places=(candidate,), glossary_version=GEONAMES_GLOSSARY_VERSION
                )
                for candidate in _unique_candidates(candidates)
            )
        )

    def _resolve_search_area(
        self, query: LocationResolutionQuery, country_code: str
    ) -> LocationResolution:
        city_id = query.city_id or ""
        if _whole_city(query.text, query.locale):
            record = self._get(city_id, query.locale)
            if record is None or record.get("fcode") not in _CITY_CODES:
                return LocationResolution(interpretations=())
            city = self._build_candidate(
                record,
                query,
                country_id=query.country_id or "",
                geographic_type=GeographicType.CITY,
                city_id=None,
            )
            if city is None:
                return LocationResolution(interpretations=())
            return LocationResolution(
                interpretations=(
                    LocationInterpretation(
                        places=(city,),
                        glossary_version=GEONAMES_GLOSSARY_VERSION,
                        whole_city=True,
                    ),
                )
            )

        results: list[tuple[LocationCandidate, ...]] = []
        for phrase in _area_phrases(query.text):
            records = self._search(
                LocationResolutionQuery(
                    text=phrase,
                    locale=query.locale,
                    stage=query.stage,
                    country_id=query.country_id,
                    city_id=query.city_id,
                ),
                country_code=country_code,
                feature_class=("A", "P", "S", "L", "H"),
            )
            matches: list[LocationCandidate] = []
            for record in records:
                geographic_type = _sub_city_type(record)
                if geographic_type is None:
                    continue
                candidate = self._build_candidate(
                    record,
                    query,
                    country_id=query.country_id or "",
                    geographic_type=geographic_type,
                    city_id=city_id,
                )
                if candidate is not None:
                    matches.append(candidate)
            unique = _unique_candidates(matches)
            if not unique:
                return LocationResolution(interpretations=())
            results.append(unique)
        combinations = _candidate_combinations(results)
        return LocationResolution(
            interpretations=tuple(
                LocationInterpretation(
                    places=places,
                    glossary_version=GEONAMES_GLOSSARY_VERSION,
                )
                for places in combinations
            )
        )

    def _build_candidate(
        self,
        record: Mapping[str, object],
        query: LocationResolutionQuery,
        *,
        country_id: str,
        geographic_type: GeographicType,
        city_id: str | None,
    ) -> LocationCandidate | None:
        place_id = _place_id(record)
        name = _localized_name(record)
        if place_id is None or name is None or place_id == country_id:
            return None
        ancestors = self._ancestors(place_id, query.locale)
        if ancestors is None:
            return None
        parents = _parents_through_country(ancestors, country_id)
        if parents is None:
            return None
        resolved_city_id: str | None
        if geographic_type is GeographicType.CITY:
            resolved_city_id = place_id
        else:
            resolved_city_id = city_id
            city_index = next(
                (
                    index
                    for index, parent in enumerate(parents)
                    if parent.place_id == resolved_city_id
                ),
                None,
            )
            if resolved_city_id is None or city_index is None:
                return None
            parents = (*parents[: city_index + 1], parents[-1])
        timezone = (
            _timezone_name(record) if geographic_type is GeographicType.CITY else None
        )
        if geographic_type is GeographicType.CITY and not _installed_timezone(timezone):
            return None
        return LocationCandidate(
            place_id=place_id,
            display_name=name,
            geographic_type=geographic_type,
            country_id=country_id,
            city_id=resolved_city_id,
            verified_parent_ids=tuple(parent.place_id for parent in parents),
            parent_display_names=tuple(parent.name for parent in parents),
            iana_timezone=timezone,
            resolver_version=GEONAMES_RESOLVER_VERSION,
            glossary_version=GEONAMES_GLOSSARY_VERSION,
            localized_display_names=_localized_names(record, query.locale),
        )

    def _ancestors(self, place_id: str, locale: str) -> tuple[_Parent, ...] | None:
        raw_id = _numeric_id(place_id)
        if raw_id is None:
            return None
        response = self._request(
            "hierarchyJSON",
            {"geonameId": raw_id, "lang": _language_tag(locale)},
        )
        items = response.get("geonames")
        if not isinstance(items, list) or len(items) > 64:
            return None
        root_to_leaf: list[_Parent] = []
        for item in items:
            if not isinstance(item, dict):
                return None
            identifier = _place_id(item)
            name = _localized_name(item)
            if identifier is None or name is None:
                return None
            root_to_leaf.append(_Parent(identifier, name, str(item.get("fcode", ""))))
        return tuple(reversed(root_to_leaf))

    def _country_code(self, country_id: str | None, locale: str) -> str | None:
        if country_id is None:
            return None
        record = self._get(country_id, locale)
        if record is None or record.get("fcode") != "PCLI":
            return None
        country_code = record.get("countryCode")
        if (
            not isinstance(country_code, str)
            or re.fullmatch(r"[A-Z]{2}", country_code) is None
        ):
            return None
        return country_code

    def _get(self, place_id: str, locale: str) -> Mapping[str, object] | None:
        numeric_id = _numeric_id(place_id)
        if numeric_id is None:
            return None
        response = self._request(
            "getJSON",
            {"geonameId": numeric_id, "lang": _language_tag(locale)},
        )
        if _place_id(response) != place_id:
            return None
        return response

    def _search(
        self,
        query: LocationResolutionQuery,
        *,
        country_code: str | None = None,
        feature_class: str | tuple[str, ...] | None = None,
        feature_code: str | None = None,
    ) -> tuple[Mapping[str, object], ...]:
        params: dict[str, str | tuple[str, ...]] = {
            "lang": _language_tag(query.locale),
            "maxRows": str(GEONAMES_MAX_ROWS),
            "q": query.text,
        }
        if country_code is not None:
            params["country"] = country_code
        if feature_class is not None:
            params["featureClass"] = feature_class
        if feature_code is not None:
            params["featureCode"] = feature_code
        response = self._request("searchJSON", params)
        records = response.get("geonames")
        if not isinstance(records, list) or len(records) > GEONAMES_MAX_ROWS:
            return ()
        return tuple(record for record in records if isinstance(record, dict))

    def _request(
        self, endpoint: str, params: Mapping[str, str | tuple[str, ...]]
    ) -> Mapping[str, object]:
        request_params = {**params, "username": self._username}
        key = (endpoint, tuple(sorted(request_params.items())))
        now = self._clock()
        cached = self._cache.get(key)
        if cached is not None and cached.expires_at > now:
            self._cache.move_to_end(key)
            return deepcopy(cached.value)
        if cached is not None:
            del self._cache[key]
        while self._request_times and now - self._request_times[0] >= 3_600:
            self._request_times.popleft()
        if len(self._request_times) >= self._requests_per_hour:
            raise LocationResolverError("location provider rate limit is exhausted")
        self._request_times.append(now)
        try:
            response = self._transport.get_json(
                endpoint,
                params=request_params,
                timeout_seconds=self._timeout_seconds,
            )
        except LocationResolverError:
            raise
        except Exception:
            raise LocationResolverError("location provider request failed") from None
        if not isinstance(response, Mapping) or "status" in response:
            raise LocationResolverError("location provider response is unavailable")
        normalized = deepcopy(dict(response))
        self._cache[key] = _CachedResponse(
            expires_at=now + self._cache_ttl_seconds,
            value=normalized,
        )
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_capacity:
            self._cache.popitem(last=False)
        return deepcopy(normalized)


@dataclass(frozen=True, slots=True)
class _Parent:
    place_id: str
    name: str
    feature_code: str


def _validated_query(query: LocationResolutionQuery) -> LocationResolutionQuery:
    if not isinstance(query, LocationResolutionQuery):
        raise LocationResolverError("location query is malformed")
    if (
        not isinstance(query.text, str)
        or not query.text.strip()
        or len(query.text) > _MAX_QUERY_LENGTH
        or query.text.strip() != query.text
        or any(ord(character) < 32 for character in query.text)
        or not isinstance(query.locale, str)
        or _LOCALE_PATTERN.fullmatch(query.locale) is None
    ):
        raise LocationResolverError("location query is malformed")
    if query.stage is ConversationStage.COUNTRY:
        if query.country_id is not None or query.city_id is not None:
            raise LocationResolverError("country query has unexpected parent context")
    elif query.stage is ConversationStage.CITY:
        if query.country_id is None or query.city_id is not None:
            raise LocationResolverError("city query has invalid parent context")
    elif query.stage is ConversationStage.SEARCH_AREA:
        if query.country_id is None or query.city_id is None:
            raise LocationResolverError("area query has incomplete parent context")
    else:
        raise LocationResolverError("location stage is unsupported")
    return query


def _place_id(record: Mapping[str, object]) -> str | None:
    value = record.get("geonameId")
    if type(value) is not int or not 1 <= value <= 999_999_999_999:
        return None
    return f"geonames:{value}"


def _numeric_id(place_id: str) -> str | None:
    match = _ID_PATTERN.fullmatch(place_id)
    return match.group(1) if match is not None else None


def _localized_name(record: Mapping[str, object]) -> str | None:
    name = record.get("name")
    if not isinstance(name, str) or not name or len(name) > 200 or name.strip() != name:
        name = record.get("toponymName")
    if not isinstance(name, str) or not name or len(name) > 200 or name.strip() != name:
        return None
    return name


def _localized_names(
    record: Mapping[str, object], locale: str
) -> tuple[tuple[str, str], ...]:
    requested_name = _localized_name(record) or ""
    canonical_name = record.get("toponymName")
    fallback = (
        canonical_name
        if isinstance(canonical_name, str) and canonical_name.strip()
        else requested_name
    )
    return tuple(
        (
            supported_locale,
            requested_name if supported_locale == _language_tag(locale) else fallback,
        )
        for supported_locale in _SUPPORTED_LOCALES
    )


def _language_tag(locale: str) -> str:
    return locale.split("-", 1)[0]


def _parents_through_country(
    ancestors: tuple[_Parent, ...], country_id: str
) -> tuple[_Parent, ...] | None:
    index = next(
        (
            position
            for position, parent in enumerate(ancestors)
            if parent.place_id == country_id
        ),
        None,
    )
    if index is None or ancestors[index].feature_code != "PCLI":
        return None
    return ancestors[: index + 1]


def _timezone_name(record: Mapping[str, object]) -> str | None:
    timezone = record.get("timezone")
    if not isinstance(timezone, dict):
        return None
    value = timezone.get("timeZoneId")
    return value if isinstance(value, str) else None


def _installed_timezone(timezone: str | None) -> bool:
    if not timezone:
        return False
    try:
        ZoneInfo(timezone)
    except (ValueError, ZoneInfoNotFoundError):
        return False
    return True


def _sub_city_type(record: Mapping[str, object]) -> GeographicType | None:
    feature_class = record.get("fcl")
    feature_code = record.get("fcode")
    if not isinstance(feature_class, str) or not isinstance(feature_code, str):
        return None
    if feature_class == "A" and re.fullmatch(r"ADM[1-4]", feature_code):
        return GeographicType.ADMINISTRATIVE_DISTRICT
    if feature_class == "P" and feature_code == "PPLX":
        return GeographicType.NEIGHBORHOOD
    if feature_class == "P" and feature_code in _CITY_CODES:
        return GeographicType.LOCALITY
    if feature_class == "S" and feature_code in _STATION_CODES:
        return GeographicType.STATION
    if feature_class == "S" and feature_code in _TRANSPORT_CODES:
        return GeographicType.TRANSPORT_HUB
    if feature_class in {"H", "L", "S"} and feature_code in _LANDMARK_CODES:
        return GeographicType.LANDMARK
    return None


def _whole_city(text: str, locale: str) -> bool:
    normalized = " ".join(text.casefold().split())
    language = _language_tag(locale)
    return normalized in _WHOLE_CITY_PHRASES.get(language, frozenset())


def _area_phrases(text: str) -> tuple[str, ...]:
    parts = tuple(
        phrase.strip(" \t,;.")
        for phrase in re.split(
            r"\s*(?:,|;|\band\b|\by\b|\bet\b|\bи\b)\s*", text, flags=re.IGNORECASE
        )
    )
    if (
        not parts
        or len(parts) > _MAX_SEARCH_AREA_PARTS
        or any(not phrase or len(phrase) > _MAX_QUERY_LENGTH for phrase in parts)
    ):
        raise LocationResolverError("location area query is unsupported")
    return parts


def _unique_candidates(
    candidates: list[LocationCandidate],
) -> tuple[LocationCandidate, ...]:
    unique: dict[str, LocationCandidate] = {}
    for candidate in candidates:
        unique.setdefault(candidate.place_id, candidate)
    return tuple(unique.values())


def _candidate_combinations(
    candidate_sets: list[tuple[LocationCandidate, ...]],
) -> tuple[tuple[LocationCandidate, ...], ...]:
    combinations: list[tuple[LocationCandidate, ...]] = [()]
    for candidate_set in candidate_sets:
        next_combinations = [
            (*prefix, candidate)
            for prefix in combinations
            for candidate in candidate_set
            if all(existing.place_id != candidate.place_id for existing in prefix)
        ]
        combinations = next_combinations[:GEONAMES_MAX_ROWS]
        if not combinations:
            return ()
    return tuple(combinations)
