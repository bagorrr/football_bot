from __future__ import annotations

import grp
import os
import pwd
import re
from pathlib import Path

import pytest

from modules.t5_runtime_configuration import (
    MASTER_CONFIGURATION_KEYS,
    ROLE_CONFIGURATION_KEYS,
    ReadinessReport,
    T5ConfigurationError,
    parse_master_env,
    preflight_role,
    project_role,
    read_master_env_file,
)


def test_env_example_is_an_empty_names_only_catalog() -> None:
    text = Path(".env.example").read_text(encoding="utf-8")
    assignments = re.findall(r"^([A-Z][A-Z0-9_]*)=(.*)$", text, re.MULTILINE)

    assert {key for key, _ in assignments} == MASTER_CONFIGURATION_KEYS
    assert len(assignments) == len(MASTER_CONFIGURATION_KEYS)
    assert all(value == "" for _, value in assignments)
    assert set(parse_master_env(text)) == MASTER_CONFIGURATION_KEYS


def test_dotenv_parser_preserves_quoted_session_value_without_truncation() -> None:
    session = 'prefix # with spaces; $dollar and quote " and slash \\' + ("x" * 4096)
    encoded_session = session.replace("\\", "\\\\").replace('"', '\\"')

    parsed = parse_master_env(
        f'TELEGRAM_SESSION_STRING="{encoded_session}"\n'
        'TELEGRAM_ADMIN_USER_ID="123456" # admin\n'
    )

    assert parsed["TELEGRAM_SESSION_STRING"] == session
    assert parsed["TELEGRAM_ADMIN_USER_ID"] == "123456"


@pytest.mark.parametrize(
    ("text", "status"),
    [
        ("TELEGRAM_API_ID 123\n", "malformed"),
        ('TELEGRAM_API_HASH="unbalanced\n', "malformed"),
        ("TELEGRAM_API_ID=123\nTELEGRAM_API_ID=456\n", "duplicate"),
        ("TELEGRAM_CHAT_ID=123\n", "deprecated"),
        ("UNLISTED_CONFIG=value\n", "unknown_key"),
    ],
)
def test_dotenv_parser_rejects_ambiguous_or_unsupported_assignments(
    text: str, status: str
) -> None:
    with pytest.raises(T5ConfigurationError) as error:
        parse_master_env(text)

    assert error.value.status == status
    assert "123" not in str(error.value)


def test_role_projections_are_explicit_and_never_share_telegram_credentials() -> None:
    master = {key: f"protected-{key}" for key in MASTER_CONFIGURATION_KEYS}
    expected_telegram = {
        "ingestion": {
            "TELEGRAM_API_ID",
            "TELEGRAM_API_HASH",
            "TELEGRAM_SESSION_STRING",
            "TELEGRAM_ADMIN_USER_ID",
        },
        "bot_assistant": {"TELEGRAM_BOT_TOKEN", "TELEGRAM_ADMIN_USER_ID"},
    }

    for role, allowed in ROLE_CONFIGURATION_KEYS.items():
        projected = project_role(master, role)
        assert set(projected) == allowed
        if role not in expected_telegram:
            assert not any(key.startswith("TELEGRAM_") for key in projected)
        else:
            assert {
                key for key in projected if key.startswith("TELEGRAM_")
            } == expected_telegram[role]


def test_t1_and_t2_receive_the_single_master_administrator_identity() -> None:
    master = {"TELEGRAM_ADMIN_USER_ID": "123456"}

    t1 = project_role(master, "bot_assistant")
    t2 = project_role(master, "ingestion")

    assert t1["TELEGRAM_ADMIN_USER_ID"] == t2["TELEGRAM_ADMIN_USER_ID"]


def test_role_preflight_rejects_unauthorized_configuration_keys() -> None:
    report = preflight_role(
        "application",
        {
            "DATABASE_URL_APPLICATION": (
                "postgresql://football_application:local@localhost/football"
            ),
            "GEONAMES_USERNAME": "controlled-user",
            "LOCATIONIQ_ACCESS_TOKEN": "controlled-locationiq-token",
            "TELEGRAM_ADMIN_USER_ID": "123456",
        },
        check_protected_paths=False,
    )

    assert isinstance(report, ReadinessReport)
    assert not report.configuration_ready
    assert report.key_statuses["TELEGRAM_ADMIN_USER_ID"] == "role_unauthorized"
    assert "123456" not in repr(report)


def test_role_preflight_checks_required_values_and_database_role_identity() -> None:
    report = preflight_role(
        "application",
        {
            "DATABASE_URL_APPLICATION": (
                "postgresql://football_recommendation:local@localhost/football"
            ),
            "GEONAMES_USERNAME": "",
            "LOCATIONIQ_ACCESS_TOKEN": "controlled-locationiq-token",
        },
        check_protected_paths=False,
    )

    assert not report.configuration_ready
    assert report.key_statuses == {
        "DATABASE_URL_APPLICATION": "identity_mismatch",
        "GEONAMES_USERNAME": "empty",
        "LOCATIONIQ_ACCESS_TOKEN": "ready",
    }
    public = report.to_public_dict()
    assert public["configuration"] == "failed"
    assert public["dependencies"] == "not_checked"
    assert "local" not in repr(public)


@pytest.mark.parametrize(
    ("key", "value", "expected_status"),
    [
        ("BOT_ASSISTANT_MODEL", None, "missing"),
        ("BOT_ASSISTANT_MODEL", "", "empty"),
        ("BOT_ASSISTANT_MODEL", 123, "malformed"),
        ("BOT_ASSISTANT_MODEL", "gpt-5.6-sol", "unsupported"),
        ("BOT_ASSISTANT_REASONING_EFFORT", None, "missing"),
        ("BOT_ASSISTANT_REASONING_EFFORT", "", "empty"),
        ("BOT_ASSISTANT_REASONING_EFFORT", 123, "malformed"),
        ("BOT_ASSISTANT_REASONING_EFFORT", "max", "unsupported"),
    ],
)
def test_bot_assistant_policy_must_be_explicit_and_validated(
    key: str, value: object, expected_status: str
) -> None:
    projection: dict[str, object] = {
        "DATABASE_URL_BOT_ASSISTANT": (
            "postgresql://football_bot_assistant:local@localhost/football"
        ),
        "GEONAMES_USERNAME": "controlled-user",
        "LOCATIONIQ_ACCESS_TOKEN": "controlled-locationiq-token",
        "TELEGRAM_BOT_TOKEN": "123456:controlled-token",
        "TELEGRAM_ADMIN_USER_ID": "123456",
        "BOT_ASSISTANT_CODEX_HOME": "/var/lib/football-bot/bot_assistant/codex",
        "BOT_ASSISTANT_SDK_SLOTS": "1",
    }
    if value is not None:
        projection[key] = value

    report = preflight_role("bot_assistant", projection, check_protected_paths=False)

    assert report.key_statuses[key] == expected_status
    assert not report.configuration_ready


def test_classifier_policy_must_be_explicit() -> None:
    report = preflight_role(
        "classification",
        {
            "DATABASE_URL_CLASSIFICATION": (
                "postgresql://football_classification:local@localhost/football"
            ),
            "CLASSIFIER_CODEX_HOME": "/var/lib/football-bot/classification/codex",
        },
        check_protected_paths=False,
    )

    assert report.key_statuses["CLASSIFIER_MODEL"] == "missing"
    assert report.key_statuses["CLASSIFIER_REASONING_EFFORT"] == "missing"
    assert not report.configuration_ready


def test_project_role_rejects_unknown_role_without_exposing_values() -> None:
    with pytest.raises(T5ConfigurationError) as error:
        project_role({"TELEGRAM_BOT_TOKEN": "secret-token"}, "unknown")

    assert error.value.status == "role_unauthorized"
    assert "secret-token" not in str(error.value)


def test_master_loader_checks_owner_group_mode_and_regular_file(tmp_path: Path) -> None:
    path = tmp_path / "master.env"
    path.write_text("GEONAMES_USERNAME=controlled-user\n", encoding="utf-8")
    os.chmod(path, 0o640)
    owner = pwd.getpwuid(os.getuid()).pw_name
    group = grp.getgrgid(os.getgid()).gr_name

    parsed = read_master_env_file(
        path,
        expected_owner=owner,
        expected_group=group,
    )

    assert parsed == {"GEONAMES_USERNAME": "controlled-user"}
    os.chmod(path, 0o644)
    with pytest.raises(T5ConfigurationError) as error:
        read_master_env_file(
            path,
            expected_owner=owner,
            expected_group=group,
        )
    assert error.value.status == "malformed"


def test_master_loader_rejects_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "target.env"
    target.write_text("GEONAMES_USERNAME=controlled-user\n", encoding="utf-8")
    link = tmp_path / "master.env"
    link.symlink_to(target)

    with pytest.raises(T5ConfigurationError) as error:
        read_master_env_file(link)

    assert error.value.status == "malformed"


def test_codex_home_must_be_role_owned_private_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "codex"
    home.mkdir(mode=0o700)
    monkeypatch.setattr(
        pwd,
        "getpwnam",
        lambda _name: type("Passwd", (), {"pw_uid": os.geteuid()})(),
    )

    report = preflight_role(
        "classification",
        {
            "DATABASE_URL_CLASSIFICATION": (
                "postgresql://football_classification:local@localhost/football"
            ),
            "CLASSIFIER_CODEX_HOME": str(home),
        },
    )

    assert report.key_statuses["CLASSIFIER_CODEX_HOME"] == "ready"


def test_codex_home_rejects_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    home = tmp_path / "codex"
    home.symlink_to(target)
    monkeypatch.setattr(
        pwd,
        "getpwnam",
        lambda _name: type("Passwd", (), {"pw_uid": os.geteuid()})(),
    )

    report = preflight_role(
        "classification",
        {
            "DATABASE_URL_CLASSIFICATION": (
                "postgresql://football_classification:local@localhost/football"
            ),
            "CLASSIFIER_CODEX_HOME": str(home),
        },
    )

    assert report.key_statuses["CLASSIFIER_CODEX_HOME"] == "inaccessible"


@pytest.mark.parametrize("mode", [0o755, 0o750, 0o700])
def test_codex_home_rejects_wrong_mode_or_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: int
) -> None:
    home = tmp_path / "codex"
    home.mkdir(mode=0o700)
    os.chmod(home, mode)
    monkeypatch.setattr(
        pwd,
        "getpwnam",
        lambda _name: type("Passwd", (), {"pw_uid": os.geteuid() + (mode == 0o700)})(),
    )

    report = preflight_role(
        "classification",
        {
            "DATABASE_URL_CLASSIFICATION": (
                "postgresql://football_classification:local@localhost/football"
            ),
            "CLASSIFIER_CODEX_HOME": str(home),
        },
    )

    assert report.key_statuses["CLASSIFIER_CODEX_HOME"] == "inaccessible"
