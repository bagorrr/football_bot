"""T5-owned master configuration parsing and least-privilege projections."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from os import R_OK, X_OK, access
from pathlib import Path
from stat import S_IMODE, S_ISDIR, S_ISREG
from types import MappingProxyType
from typing import cast

from psycopg.conninfo import conninfo_to_dict

_KEY_PATTERN = re.compile(r"[A-Z][A-Z0-9_]*\Z")
_UNQUOTED_COMMENT_PATTERN = re.compile(r"\s+#")

DATABASE_URL_INGESTION = "DATABASE_URL_INGESTION"
DATABASE_URL_APPLICATION = "DATABASE_URL_APPLICATION"
DATABASE_URL_CLASSIFICATION = "DATABASE_URL_CLASSIFICATION"
DATABASE_URL_RECOMMENDATION = "DATABASE_URL_RECOMMENDATION"
DATABASE_URL_BOT_ASSISTANT = "DATABASE_URL_BOT_ASSISTANT"

TELEGRAM_BOT_TOKEN = "TELEGRAM_BOT_TOKEN"
TELEGRAM_API_ID = "TELEGRAM_API_ID"
TELEGRAM_API_HASH = "TELEGRAM_API_HASH"
TELEGRAM_SESSION_STRING = "TELEGRAM_SESSION_STRING"
TELEGRAM_ADMIN_USER_ID = "TELEGRAM_ADMIN_USER_ID"

BOT_ASSISTANT_MODEL = "BOT_ASSISTANT_MODEL"
BOT_ASSISTANT_REASONING_EFFORT = "BOT_ASSISTANT_REASONING_EFFORT"
BOT_ASSISTANT_SDK_SLOTS = "BOT_ASSISTANT_SDK_SLOTS"
BOT_ASSISTANT_CODEX_HOME = "BOT_ASSISTANT_CODEX_HOME"

CLASSIFIER_MODEL = "CLASSIFIER_MODEL"
CLASSIFIER_REASONING_EFFORT = "CLASSIFIER_REASONING_EFFORT"
CLASSIFIER_CODEX_HOME = "CLASSIFIER_CODEX_HOME"

GEONAMES_USERNAME = "GEONAMES_USERNAME"
LOCATIONIQ_ACCESS_TOKEN = "LOCATIONIQ_ACCESS_TOKEN"

MASTER_CONFIGURATION_KEYS = frozenset(
    {
        DATABASE_URL_INGESTION,
        DATABASE_URL_APPLICATION,
        DATABASE_URL_CLASSIFICATION,
        DATABASE_URL_RECOMMENDATION,
        DATABASE_URL_BOT_ASSISTANT,
        TELEGRAM_BOT_TOKEN,
        TELEGRAM_API_ID,
        TELEGRAM_API_HASH,
        TELEGRAM_SESSION_STRING,
        TELEGRAM_ADMIN_USER_ID,
        BOT_ASSISTANT_MODEL,
        BOT_ASSISTANT_REASONING_EFFORT,
        BOT_ASSISTANT_SDK_SLOTS,
        BOT_ASSISTANT_CODEX_HOME,
        CLASSIFIER_MODEL,
        CLASSIFIER_REASONING_EFFORT,
        CLASSIFIER_CODEX_HOME,
        GEONAMES_USERNAME,
        LOCATIONIQ_ACCESS_TOKEN,
    }
)

DEPRECATED_CONFIGURATION_KEYS = frozenset(
    {
        "TELEGRAM_CHAT_ID",
        "TELEGRAM_ACCOUNT_USERNAME",
        "TELEGRAM_BOT_USERNAME",
        "WORKER_SSH_HOST",
        "WORKER_SSH_PORT",
        "WORKER_SSH_USER",
        "CLASSIFIER_RUNTIME",
        "CLASSIFIER_AUTH_MODE",
        "CLASSIFIER_CODEX_PATH",
        "CLASSIFIER_MAX_CONCURRENCY",
        "CLASSIFIER_TIMEOUT_SECONDS",
    }
)

ROLE_CONFIGURATION_KEYS: dict[str, frozenset[str]] = {
    "ingestion": frozenset(
        {
            DATABASE_URL_INGESTION,
            TELEGRAM_API_ID,
            TELEGRAM_API_HASH,
            TELEGRAM_SESSION_STRING,
            TELEGRAM_ADMIN_USER_ID,
        }
    ),
    "application": frozenset(
        {DATABASE_URL_APPLICATION, GEONAMES_USERNAME, LOCATIONIQ_ACCESS_TOKEN}
    ),
    "classification": frozenset(
        {
            DATABASE_URL_CLASSIFICATION,
            CLASSIFIER_MODEL,
            CLASSIFIER_REASONING_EFFORT,
            CLASSIFIER_CODEX_HOME,
        }
    ),
    "recommendation": frozenset({DATABASE_URL_RECOMMENDATION}),
    "bot_assistant": frozenset(
        {
            DATABASE_URL_BOT_ASSISTANT,
            GEONAMES_USERNAME,
            LOCATIONIQ_ACCESS_TOKEN,
            TELEGRAM_BOT_TOKEN,
            TELEGRAM_ADMIN_USER_ID,
            BOT_ASSISTANT_MODEL,
            BOT_ASSISTANT_REASONING_EFFORT,
            BOT_ASSISTANT_SDK_SLOTS,
            BOT_ASSISTANT_CODEX_HOME,
        }
    ),
    "sdk_worker": frozenset(
        {
            BOT_ASSISTANT_MODEL,
            BOT_ASSISTANT_REASONING_EFFORT,
            BOT_ASSISTANT_SDK_SLOTS,
            BOT_ASSISTANT_CODEX_HOME,
        }
    ),
}

ROLE_DATABASE_KEYS = {
    "ingestion": DATABASE_URL_INGESTION,
    "application": DATABASE_URL_APPLICATION,
    "classification": DATABASE_URL_CLASSIFICATION,
    "recommendation": DATABASE_URL_RECOMMENDATION,
    "bot_assistant": DATABASE_URL_BOT_ASSISTANT,
}
ROLE_REQUIRED_KEYS: dict[str, frozenset[str]] = {
    "ingestion": ROLE_CONFIGURATION_KEYS["ingestion"],
    "application": ROLE_CONFIGURATION_KEYS["application"],
    "classification": frozenset({DATABASE_URL_CLASSIFICATION, CLASSIFIER_CODEX_HOME}),
    "recommendation": ROLE_CONFIGURATION_KEYS["recommendation"],
    "bot_assistant": frozenset(
        {
            DATABASE_URL_BOT_ASSISTANT,
            GEONAMES_USERNAME,
            LOCATIONIQ_ACCESS_TOKEN,
            TELEGRAM_BOT_TOKEN,
            TELEGRAM_ADMIN_USER_ID,
            BOT_ASSISTANT_MODEL,
            BOT_ASSISTANT_REASONING_EFFORT,
            BOT_ASSISTANT_CODEX_HOME,
        }
    ),
    "sdk_worker": frozenset({BOT_ASSISTANT_CODEX_HOME}),
}

PRODUCTION_MASTER_ENV_PATH = Path("/etc/football-bot/football-bot.env")
PRODUCTION_MASTER_ENV_OWNER = "root"
PRODUCTION_MASTER_ENV_GROUP = "football-bot-config"
PRODUCTION_MASTER_ENV_MODE = 0o640
_PROTECTED_PATH_OWNERS = {
    CLASSIFIER_CODEX_HOME: "football-classification",
    BOT_ASSISTANT_CODEX_HOME: "football-bot-assistant",
}


class T5ConfigurationError(ValueError):
    """A redacted master or role configuration failure."""

    def __init__(self, *, key: str, status: str) -> None:
        self.key = key
        self.status = status
        super().__init__(f"T5 configuration {status}: {key}")


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    """Redacted configuration readiness for one runtime role."""

    role: str
    key_statuses: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "key_statuses",
            MappingProxyType(dict(self.key_statuses)),
        )

    @property
    def configuration_ready(self) -> bool:
        """Return whether each reported key is valid or code-defaulted."""
        return all(
            status in {"ready", "defaulted"} for status in self.key_statuses.values()
        )

    def to_public_dict(self) -> dict[str, object]:
        """Return statuses and key names only; never include configuration values."""
        return {
            "role": self.role,
            "configuration": "ready" if self.configuration_ready else "failed",
            "dependencies": "not_checked",
            "runtime": "not_started",
            "keys": dict(sorted(self.key_statuses.items())),
        }


def parse_master_env(text: str) -> dict[str, str]:
    """Parse supported dotenv assignments without logging or rewriting values."""
    if not isinstance(text, str):
        raise T5ConfigurationError(key="master", status="malformed")
    values: dict[str, str] = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        assignment = stripped.removeprefix("export ").strip()
        if "=" not in assignment:
            raise T5ConfigurationError(key=f"line_{line_number}", status="malformed")
        raw_key, raw_value = assignment.split("=", maxsplit=1)
        key = raw_key.strip()
        if _KEY_PATTERN.fullmatch(key) is None:
            raise T5ConfigurationError(key=f"line_{line_number}", status="malformed")
        if key in DEPRECATED_CONFIGURATION_KEYS:
            raise T5ConfigurationError(key=key, status="deprecated")
        if key not in MASTER_CONFIGURATION_KEYS:
            raise T5ConfigurationError(key=key, status="unknown_key")
        if key in values:
            raise T5ConfigurationError(key=key, status="duplicate")
        values[key] = _parse_dotenv_value(raw_value, key=key)
    return values


def project_role(values: Mapping[str, object], role: str) -> dict[str, str]:
    """Copy only the approved master keys for one named runtime role."""
    if role not in ROLE_CONFIGURATION_KEYS:
        raise T5ConfigurationError(key="role", status="role_unauthorized")
    for key, value in values.items():
        if not isinstance(key, str):
            raise T5ConfigurationError(key="master", status="malformed")
        if key in DEPRECATED_CONFIGURATION_KEYS:
            raise T5ConfigurationError(key=key, status="deprecated")
        if key not in MASTER_CONFIGURATION_KEYS:
            raise T5ConfigurationError(key=key, status="unknown_key")
        if not isinstance(value, str):
            raise T5ConfigurationError(key=key, status="malformed")
    allowed = ROLE_CONFIGURATION_KEYS[role]
    return {key: cast(str, value) for key, value in values.items() if key in allowed}


def read_master_env_file(
    path: Path = PRODUCTION_MASTER_ENV_PATH,
    *,
    expected_owner: str = PRODUCTION_MASTER_ENV_OWNER,
    expected_group: str = PRODUCTION_MASTER_ENV_GROUP,
    expected_mode: int = PRODUCTION_MASTER_ENV_MODE,
) -> dict[str, str]:
    """Read the canonical dotenv only after verifying its protected metadata."""
    import grp
    import pwd

    try:
        metadata = path.lstat()
    except OSError:
        raise T5ConfigurationError(key="master_file", status="inaccessible") from None
    if not S_ISREG(metadata.st_mode):
        raise T5ConfigurationError(key="master_file", status="malformed")
    try:
        owner_id = pwd.getpwnam(expected_owner).pw_uid
        group_id = grp.getgrnam(expected_group).gr_gid
    except (OSError, KeyError):
        raise T5ConfigurationError(key="master_file", status="inaccessible") from None
    if metadata.st_uid != owner_id or metadata.st_gid != group_id:
        raise T5ConfigurationError(key="master_file", status="identity_mismatch")
    if S_IMODE(metadata.st_mode) != expected_mode or expected_mode & 0o007:
        raise T5ConfigurationError(key="master_file", status="malformed")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise T5ConfigurationError(key="master_file", status="inaccessible") from None
    return parse_master_env(text)


def preflight_role(
    role: str,
    projection: Mapping[str, object],
    *,
    check_protected_paths: bool = True,
) -> ReadinessReport:
    """Validate one explicit role projection and return redacted readiness."""
    if role not in ROLE_CONFIGURATION_KEYS:
        return ReadinessReport(role, {"role": "role_unauthorized"})
    allowed = ROLE_CONFIGURATION_KEYS[role]
    statuses: dict[str, str] = {}
    for key, value in projection.items():
        if not isinstance(key, str):
            statuses["projection"] = "malformed"
        elif key in DEPRECATED_CONFIGURATION_KEYS:
            statuses[key] = "deprecated"
        elif key not in MASTER_CONFIGURATION_KEYS:
            statuses[key] = "unknown_key"
        elif key not in allowed:
            statuses[key] = "role_unauthorized"
        elif not isinstance(value, str):
            statuses[key] = "malformed"
        elif not value.strip():
            statuses[key] = "empty"
        else:
            statuses[key] = "ready"

    for key in ROLE_REQUIRED_KEYS[role]:
        statuses.setdefault(key, "missing")

    database_key = ROLE_DATABASE_KEYS.get(role)
    if database_key is not None and statuses.get(database_key) == "ready":
        statuses[database_key] = _database_url_status(
            cast(str, projection[database_key]), role=role
        )

    if role == "bot_assistant":
        _validate_telegram_bot_projection(projection, statuses)
        _validate_t3_settings(projection, statuses)
        _validate_protected_path(
            projection,
            key=BOT_ASSISTANT_CODEX_HOME,
            statuses=statuses,
            check=check_protected_paths,
        )
    elif role == "ingestion":
        _validate_telethon_projection(projection, statuses)
    elif role == "classification":
        _validate_t4_settings(projection, statuses)
        _validate_protected_path(
            projection,
            key=CLASSIFIER_CODEX_HOME,
            statuses=statuses,
            check=check_protected_paths,
        )
    elif role == "sdk_worker":
        _validate_t3_settings(projection, statuses)
        _validate_protected_path(
            projection,
            key=BOT_ASSISTANT_CODEX_HOME,
            statuses=statuses,
            check=check_protected_paths,
        )

    if (
        role in {"application", "bot_assistant"}
        and statuses.get(GEONAMES_USERNAME) == "ready"
    ):
        value = cast(str, projection[GEONAMES_USERNAME])
        if len(value) > 64 or value.strip() != value:
            statuses[GEONAMES_USERNAME] = "malformed"
    if (
        role in {"application", "bot_assistant"}
        and statuses.get(LOCATIONIQ_ACCESS_TOKEN) == "ready"
    ):
        value = cast(str, projection[LOCATIONIQ_ACCESS_TOKEN])
        if len(value) > 256 or value.strip() != value:
            statuses[LOCATIONIQ_ACCESS_TOKEN] = "malformed"
    return ReadinessReport(role, statuses)


def _database_url_status(value: str, *, role: str) -> str:
    try:
        connection = conninfo_to_dict(value)
    except Exception:
        return "unparseable"
    if connection.get("user") != f"football_{role}":
        return "identity_mismatch"
    return (
        "ready" if connection.get("dbname") or connection.get("host") else "malformed"
    )


def _validate_telegram_bot_projection(
    projection: Mapping[str, object], statuses: dict[str, str]
) -> None:
    from modules.bot_api import BotApiConfigurationError, T1BotApiProjection

    values = {
        key: projection[key]
        for key in (TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_USER_ID)
        if key in projection
    }
    try:
        T1BotApiProjection.from_mapping(values)
    except BotApiConfigurationError as error:
        statuses[error.key] = error.status


def _validate_telethon_projection(
    projection: Mapping[str, object], statuses: dict[str, str]
) -> None:
    from modules.telethon_ingestion import (
        T2TelethonProjection,
        TelethonConfigurationError,
    )

    values = {
        key: projection[key]
        for key in (
            TELEGRAM_API_ID,
            TELEGRAM_API_HASH,
            TELEGRAM_SESSION_STRING,
            TELEGRAM_ADMIN_USER_ID,
        )
        if key in projection
    }
    try:
        T2TelethonProjection.from_mapping(values)
    except TelethonConfigurationError as error:
        statuses[error.key] = error.status


def _validate_t3_settings(
    projection: Mapping[str, object], statuses: dict[str, str]
) -> None:
    from modules.codex_bot_assistant_adapter import (
        BOT_ASSISTANT_REASONING_EFFORT_KEY,
        BOT_ASSISTANT_SDK_SLOTS_KEY,
        MAX_BOT_ASSISTANT_SDK_SLOTS,
    )
    from modules.ports import (
        DEFAULT_BOT_ASSISTANT_MODEL,
        DEFAULT_BOT_ASSISTANT_REASONING_EFFORT,
    )

    for key, supported in (
        (BOT_ASSISTANT_MODEL, DEFAULT_BOT_ASSISTANT_MODEL),
        (BOT_ASSISTANT_REASONING_EFFORT_KEY, DEFAULT_BOT_ASSISTANT_REASONING_EFFORT),
    ):
        value = projection.get(key)
        if value is None:
            statuses.setdefault(key, "missing")
        elif statuses.get(key) in {"ready", "missing"} and value != supported:
            statuses[key] = "unsupported"
    slots = projection.get(BOT_ASSISTANT_SDK_SLOTS_KEY)
    if slots is None and BOT_ASSISTANT_SDK_SLOTS_KEY not in statuses:
        statuses[BOT_ASSISTANT_SDK_SLOTS_KEY] = "defaulted"
    elif statuses.get(BOT_ASSISTANT_SDK_SLOTS_KEY) in {"ready", "missing"} and (
        not isinstance(slots, str)
        or not slots.isascii()
        or not slots.isdecimal()
        or (len(slots) > 1 and slots.startswith("0"))
        or not 1 <= int(slots) <= MAX_BOT_ASSISTANT_SDK_SLOTS
    ):
        statuses[BOT_ASSISTANT_SDK_SLOTS_KEY] = "malformed"


def _validate_t4_settings(
    projection: Mapping[str, object], statuses: dict[str, str]
) -> None:
    from modules.classifier_configuration import (
        DEFAULT_CLASSIFIER_MODEL,
        DEFAULT_CLASSIFIER_REASONING_EFFORT,
    )

    model = projection.get(CLASSIFIER_MODEL)
    effort = projection.get(CLASSIFIER_REASONING_EFFORT)
    if (
        model is None
        and effort is None
        and CLASSIFIER_MODEL not in statuses
        and CLASSIFIER_REASONING_EFFORT not in statuses
    ):
        statuses[CLASSIFIER_MODEL] = "defaulted"
        statuses[CLASSIFIER_REASONING_EFFORT] = "defaulted"
        return
    if model is None and CLASSIFIER_MODEL not in statuses:
        statuses[CLASSIFIER_MODEL] = "missing"
    elif statuses.get(CLASSIFIER_MODEL) in {"ready", "missing"} and model != (
        DEFAULT_CLASSIFIER_MODEL
    ):
        statuses[CLASSIFIER_MODEL] = "unsupported"
    if effort is None and CLASSIFIER_REASONING_EFFORT not in statuses:
        statuses[CLASSIFIER_REASONING_EFFORT] = "missing"
    elif statuses.get(CLASSIFIER_REASONING_EFFORT) in {
        "ready",
        "missing",
    } and effort != (DEFAULT_CLASSIFIER_REASONING_EFFORT):
        statuses[CLASSIFIER_REASONING_EFFORT] = "unsupported"


def _validate_protected_path(
    projection: Mapping[str, object],
    *,
    key: str,
    statuses: dict[str, str],
    check: bool,
) -> None:
    if statuses.get(key) != "ready":
        return
    value = projection[key]
    if not isinstance(value, str) or not Path(value).is_absolute():
        statuses[key] = "malformed"
    elif check:
        import pwd

        try:
            metadata = Path(value).lstat()
            expected_uid = pwd.getpwnam(_PROTECTED_PATH_OWNERS[key]).pw_uid
        except (OSError, KeyError):
            statuses[key] = "inaccessible"
            return
        if (
            not S_ISDIR(metadata.st_mode)
            or metadata.st_uid != expected_uid
            or S_IMODE(metadata.st_mode) != 0o700
            or not access(value, R_OK | X_OK)
        ):
            statuses[key] = "inaccessible"


def _parse_dotenv_value(raw_value: str, *, key: str) -> str:
    value = raw_value.lstrip()
    if value.startswith(("'", '"')):
        return _parse_quoted_value(value, key=key)
    comment = _UNQUOTED_COMMENT_PATTERN.search(value)
    if comment is not None:
        value = value[: comment.start()]
    return value.rstrip()


def _parse_quoted_value(value: str, *, key: str) -> str:
    quote = value[0]
    decoded: list[str] = []
    index = 1
    closed = False
    escapes = {
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "\\": "\\",
        quote: quote,
    }
    while index < len(value):
        character = value[index]
        if character == quote:
            closed = True
            index += 1
            break
        if character == "\\" and index + 1 < len(value):
            following = value[index + 1]
            decoded.append(escapes.get(following, f"\\{following}"))
            index += 2
            continue
        decoded.append(character)
        index += 1
    if not closed:
        raise T5ConfigurationError(key=key, status="malformed")
    trailing = value[index:].strip()
    if trailing and not trailing.startswith("#"):
        raise T5ConfigurationError(key=key, status="malformed")
    return "".join(decoded)
