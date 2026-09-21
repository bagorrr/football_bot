from __future__ import annotations

import json
import os
import pwd
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from apps import runtime_launcher
from apps.runtime_launcher import build_role_environment
from modules.t5_runtime_configuration import PRODUCTION_MASTER_ENV_PATH, project_role


def test_launcher_environment_contains_only_role_projection_and_os_basics() -> None:
    master = {
        "DATABASE_URL_APPLICATION": "postgresql://football_application@db/app",
        "DATABASE_URL_BOT_ASSISTANT": "postgresql://football_bot_assistant@db/app",
        "GEONAMES_USERNAME": "controlled-user",
        "LOCATIONIQ_ACCESS_TOKEN": "controlled-locationiq-token",
        "TELEGRAM_BOT_TOKEN": "123456:controlled-token",
        "TELEGRAM_ADMIN_USER_ID": "456789",
        "TELEGRAM_API_ID": "123456",
        "TELEGRAM_API_HASH": "controlled-hash",
        "TELEGRAM_SESSION_STRING": "controlled-session",
        "BOT_ASSISTANT_CODEX_HOME": "/var/lib/football-bot/bot_assistant/codex",
        "BOT_ASSISTANT_MODEL": "gpt-5.6-luna",
        "BOT_ASSISTANT_REASONING_EFFORT": "high",
        "BOT_ASSISTANT_SDK_SLOTS": "1",
    }

    application = build_role_environment(
        "application",
        project_role(master, "application"),
        python_prefix=Path("/opt/football-bot/venv"),
        home=Path("/var/lib/football-bot/application"),
    )
    assistant = build_role_environment(
        "bot_assistant",
        project_role(master, "bot_assistant"),
        python_prefix=Path("/opt/football-bot/venv"),
        home=Path("/var/lib/football-bot/bot_assistant"),
        notify_socket="/run/systemd/notify",
    )

    assert set(application) == {
        "PATH",
        "HOME",
        "TMPDIR",
        "LANG",
        "PYTHONUTF8",
        "DATABASE_URL_APPLICATION",
        "GEONAMES_USERNAME",
        "LOCATIONIQ_ACCESS_TOKEN",
    }
    assert "TELEGRAM_ADMIN_USER_ID" not in application
    assert "TELEGRAM_SESSION_STRING" not in application
    assert set(assistant) == {
        "PATH",
        "HOME",
        "TMPDIR",
        "LANG",
        "PYTHONUTF8",
        "NOTIFY_SOCKET",
        "DATABASE_URL_BOT_ASSISTANT",
        "GEONAMES_USERNAME",
        "LOCATIONIQ_ACCESS_TOKEN",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_ADMIN_USER_ID",
        "BOT_ASSISTANT_CODEX_HOME",
        "BOT_ASSISTANT_MODEL",
        "BOT_ASSISTANT_REASONING_EFFORT",
        "BOT_ASSISTANT_SDK_SLOTS",
    }
    assert assistant["HOME"] == "/var/lib/football-bot/bot_assistant"
    assert assistant["NOTIFY_SOCKET"] == "/run/systemd/notify"


def test_t2_checkpoint_bootstrap_uses_t5_projection_and_role_drop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    master = {
        "DATABASE_URL_INGESTION": "postgresql://football_ingestion@db/app",
        "TELEGRAM_API_ID": "123456",
        "TELEGRAM_API_HASH": "controlled-hash",
        "TELEGRAM_SESSION_STRING": "controlled-session",
        "TELEGRAM_ADMIN_USER_ID": "456789",
        "TELEGRAM_BOT_TOKEN": "123456:controlled-token",
    }
    runtime_user = SimpleNamespace(
        pw_uid=1001,
        pw_gid=1002,
        pw_dir="/var/lib/football-bot/ingestion",
    )
    privilege_calls: list[tuple[str, object]] = []
    exec_calls: list[tuple[str, tuple[str, ...], dict[str, str]]] = []

    def read_master(path: Path) -> dict[str, str]:
        assert path == PRODUCTION_MASTER_ENV_PATH
        return master

    def get_runtime_user(name: str) -> SimpleNamespace:
        assert name == "football-ingestion"
        return runtime_user

    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(runtime_launcher, "read_master_env_file", read_master)
    monkeypatch.setattr(pwd, "getpwnam", get_runtime_user)
    monkeypatch.setattr(
        os,
        "setgroups",
        lambda groups: privilege_calls.append(("setgroups", groups)),
    )
    monkeypatch.setattr(
        os,
        "setgid",
        lambda gid: privilege_calls.append(("setgid", gid)),
    )
    monkeypatch.setattr(
        os,
        "setuid",
        lambda uid: privilege_calls.append(("setuid", uid)),
    )
    monkeypatch.setattr(os, "umask", lambda _mask: None)
    monkeypatch.setattr(os, "chdir", lambda _path: None)
    monkeypatch.setattr(
        os,
        "execve",
        lambda executable, arguments, environment: exec_calls.append(
            (executable, arguments, environment)
        ),
    )

    result = runtime_launcher.main(["--role", "ingestion", "--checkpoint-bootstrap"])

    assert result == 0
    assert privilege_calls == [
        ("setgroups", []),
        ("setgid", 1002),
        ("setuid", 1001),
    ]
    assert len(exec_calls) == 1
    executable, arguments, environment = exec_calls[0]
    assert executable == sys.executable
    assert arguments[-2:] == (
        "--apply",
        "--from-t5-launcher",
    )
    assert arguments[-3].endswith("/apps/t2_checkpoint_bootstrap.py")
    assert set(environment) == {
        "PATH",
        "HOME",
        "TMPDIR",
        "LANG",
        "PYTHONUTF8",
        "DATABASE_URL_INGESTION",
        "TELEGRAM_API_ID",
        "TELEGRAM_API_HASH",
        "TELEGRAM_SESSION_STRING",
        "TELEGRAM_ADMIN_USER_ID",
    }
    assert "TELEGRAM_BOT_TOKEN" not in environment


def test_preflight_only_checks_staged_master_without_starting_role(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    candidate = tmp_path / "candidate.env"
    projection = {
        "DATABASE_URL_APPLICATION": (
            "postgresql://football_application:protected-value@db/app"
        ),
        "GEONAMES_USERNAME": "protected-geonames-user",
        "LOCATIONIQ_ACCESS_TOKEN": "protected-locationiq-token",
    }
    read_paths: list[Path] = []

    def read_candidate(path: Path) -> dict[str, str]:
        read_paths.append(path)
        return projection

    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        runtime_launcher,
        "read_master_env_file",
        read_candidate,
    )
    monkeypatch.setattr(
        os,
        "execve",
        lambda *_args: pytest.fail("preflight-only must not start a runtime"),
    )

    result = runtime_launcher.main(
        [
            "--role",
            "application",
            "--preflight-only",
            "--config-file",
            str(candidate),
        ]
    )

    output = capsys.readouterr().out
    report = json.loads(output)
    assert result == 0
    assert read_paths == [candidate]
    assert report["configuration"] == "ready"
    assert report["dependencies"] == "not_checked"
    assert report["runtime"] == "not_started"
    assert "protected-value" not in output
    assert "protected-geonames-user" not in output


def test_runtime_cannot_override_the_canonical_master_file(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        runtime_launcher,
        "read_master_env_file",
        lambda _path: pytest.fail("noncanonical runtime config must be rejected"),
    )

    result = runtime_launcher.main(
        ["--role", "application", "--config-file", "/tmp/other.env"]
    )

    report = json.loads(capsys.readouterr().out)
    assert result == 78
    assert report["failure"]["status"] == "config_file_requires_preflight_only"


def test_systemd_template_starts_only_through_the_t5_launcher() -> None:
    unit = Path("deploy/systemd/football-bot-role@.service").read_text(encoding="utf-8")

    assert "Type=notify" in unit
    assert "WatchdogSec=240s" in unit
    assert (
        "ExecStart=/opt/football-bot/current/.venv/bin/python -I -B "
        "/opt/football-bot/current/apps/runtime_launcher.py --role %i"
    ) in unit
    assert "EnvironmentFile=" not in unit
    assert "CapabilityBoundingSet=CAP_SETUID CAP_SETGID CAP_DAC_READ_SEARCH" in unit
