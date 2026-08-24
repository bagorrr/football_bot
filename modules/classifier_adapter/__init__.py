"""Shared classifier-adapter implementation details."""

from __future__ import annotations

import re
from collections.abc import Mapping

from modules.ports import (
    ClassifierAuthenticationError,
    ClassifierProviderError,
    ClassifierQuotaError,
    ClassifierTransientError,
)


def classifier_provider_error_from_metadata(
    metadata: object,
) -> ClassifierProviderError | None:
    """Map provider metadata to a typed, body-free classifier failure."""
    if isinstance(metadata, ClassifierProviderError):
        return metadata
    tokens = _classifier_provider_tokens(metadata)
    joined = " ".join(tokens)
    status_code = _classifier_provider_status_code(metadata)
    retry_after_seconds = _classifier_provider_retry_after_seconds(metadata)
    if status_code in {401, 403} or _contains_provider_marker(
        joined,
        (
            "authentication",
            "authentication_required",
            "unauthorized",
            "unauthorised",
            "invalid_api_key",
            "invalid_api_token",
            "login_required",
            "not_authenticated",
            "token_expired",
            "credential",
            "401",
        ),
    ):
        return ClassifierAuthenticationError()
    if status_code == 429 or _contains_provider_marker(
        joined,
        (
            "quota",
            "rate_limit",
            "rate_limited",
            "too_many_requests",
            "usage_limit",
            "insufficient_quota",
            "subscription",
            "billing",
            "429",
        ),
    ):
        return ClassifierQuotaError(retry_after_seconds=retry_after_seconds)
    if (
        status_code is not None and 500 <= status_code <= 599
    ) or _contains_provider_marker(
        joined,
        (
            "provider_error",
            "provider_failure",
            "server_error",
            "internal_server_error",
            "bad_gateway",
            "service_unavailable",
            "gateway_timeout",
            "upstream_error",
            "temporarily_unavailable",
            "transient",
            "5xx",
        ),
    ):
        return ClassifierTransientError(retry_after_seconds=retry_after_seconds)
    return None


_CLASSIFIER_PROVIDER_STATUS_KEYS = {
    "status",
    "status_code",
    "http_status",
    "http_status_code",
    "http_code",
    "code",
}
_CLASSIFIER_PROVIDER_RETRY_KEYS = {
    "retry_after",
    "retry_after_seconds",
    "retryafter",
}
_CLASSIFIER_PROVIDER_IGNORED_KEYS = {"output"}


def _normalize_classifier_provider_key(value: str) -> str:
    normalized = re.sub(r"(?<!^)(?=[A-Z])", "_", value)
    normalized = normalized.casefold().replace("-", "_").replace(" ", "_")
    return re.sub(r"_+", "_", normalized)


def _classifier_provider_tokens(value: object, *, depth: int = 0) -> list[str]:
    if depth > 4:
        return []
    if isinstance(value, Mapping):
        tokens: list[str] = []
        for key, nested in value.items():
            if isinstance(key, str):
                normalized_key = _normalize_classifier_provider_key(key)
                if normalized_key in _CLASSIFIER_PROVIDER_IGNORED_KEYS:
                    continue
                tokens.append(normalized_key)
            tokens.extend(_classifier_provider_tokens(nested, depth=depth + 1))
        return tokens
    if isinstance(value, BaseException):
        tokens = [_normalize_classifier_provider_key(type(value).__name__)]
        for argument in value.args:
            tokens.extend(_classifier_provider_tokens(argument, depth=depth + 1))
        for attribute in (
            "status",
            "status_code",
            "code",
            "headers",
            "response",
            "retry_after",
            "retry_after_seconds",
        ):
            nested = getattr(value, attribute, None)
            if nested is not None:
                tokens.extend(_classifier_provider_tokens(nested, depth=depth + 1))
        return tokens
    if isinstance(value, str):
        return [_normalize_classifier_provider_key(value)]
    if isinstance(value, int) and not isinstance(value, bool):
        return [str(value)]
    return []


def _classifier_provider_status_code(value: object, *, depth: int = 0) -> int | None:
    if depth > 4:
        return None
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized_key = (
                _normalize_classifier_provider_key(key) if isinstance(key, str) else ""
            )
            if normalized_key in _CLASSIFIER_PROVIDER_IGNORED_KEYS:
                continue
            if normalized_key in _CLASSIFIER_PROVIDER_STATUS_KEYS:
                status_code = _classifier_provider_integer(nested)
                if status_code is not None:
                    return status_code
            status_code = _classifier_provider_status_code(nested, depth=depth + 1)
            if status_code is not None:
                return status_code
    elif isinstance(value, BaseException):
        for argument in value.args:
            status_code = _classifier_provider_status_code(argument, depth=depth + 1)
            if status_code is not None:
                return status_code
        for attribute in ("status", "status_code", "code", "response"):
            nested = getattr(value, attribute, None)
            status_code = _classifier_provider_status_code(nested, depth=depth + 1)
            if status_code is not None:
                return status_code
    elif isinstance(value, str):
        match = re.search(r"\b([45][0-9]{2})\b", value)
        if match is not None:
            return int(match.group(1))
    return None


def _classifier_provider_retry_after_seconds(
    value: object, *, depth: int = 0
) -> int | None:
    if depth > 4:
        return None
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized_key = (
                _normalize_classifier_provider_key(key) if isinstance(key, str) else ""
            )
            if normalized_key in _CLASSIFIER_PROVIDER_IGNORED_KEYS:
                continue
            if normalized_key in _CLASSIFIER_PROVIDER_RETRY_KEYS:
                retry_after = _classifier_provider_integer(nested)
                if retry_after is not None and retry_after >= 0:
                    return retry_after
            retry_after = _classifier_provider_retry_after_seconds(
                nested, depth=depth + 1
            )
            if retry_after is not None:
                return retry_after
    elif isinstance(value, BaseException):
        for argument in value.args:
            retry_after = _classifier_provider_retry_after_seconds(
                argument, depth=depth + 1
            )
            if retry_after is not None:
                return retry_after
        for attribute in (
            "retry_after",
            "retry_after_seconds",
            "headers",
            "response",
        ):
            retry_after = _classifier_provider_retry_after_seconds(
                getattr(value, attribute, None), depth=depth + 1
            )
            if retry_after is not None:
                return retry_after
    elif isinstance(value, str):
        match = re.search(r"retry[_ -]?after[^0-9]{0,20}(\d+)", value.casefold())
        if match is not None:
            return int(match.group(1))
    return None


def _classifier_provider_integer(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _contains_provider_marker(value: str, needles: tuple[str, ...]) -> bool:
    return any(needle in value for needle in needles)
