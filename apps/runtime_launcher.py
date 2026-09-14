"""T5 protected configuration and least-privilege role launcher."""

from __future__ import annotations

import argparse
import json
import os
import pwd
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from modules.t5_runtime_configuration import (  # noqa: E402
    PRODUCTION_MASTER_ENV_PATH,
    ROLE_CONFIGURATION_KEYS,
    T5ConfigurationError,
    preflight_role,
    project_role,
    read_master_env_file,
)

SERVICE_ROLES = frozenset(
    {"ingestion", "application", "classification", "recommendation", "bot_assistant"}
)
ROLE_OS_USERS = {
    "ingestion": "football-ingestion",
    "application": "football-application",
    "classification": "football-classification",
    "recommendation": "football-recommendation",
    "bot_assistant": "football-bot-assistant",
}
_OPERATING_SYSTEM_ENVIRONMENT = frozenset(
    {"PATH", "HOME", "TMPDIR", "LANG", "PYTHONUTF8"}
)


def build_role_environment(
    role: str,
    projection: Mapping[str, str],
    *,
    python_prefix: Path,
    home: Path,
    notify_socket: str | None = None,
) -> dict[str, str]:
    """Build a fresh process environment from one T5-approved projection."""
    if role not in SERVICE_ROLES:
        raise T5ConfigurationError(key="role", status="role_unauthorized")
    if set(projection) - ROLE_CONFIGURATION_KEYS[role]:
        raise T5ConfigurationError(key="projection", status="role_unauthorized")
    if not all(isinstance(value, str) for value in projection.values()):
        raise T5ConfigurationError(key="projection", status="malformed")
    if not all(path.is_absolute() for path in (python_prefix, home)):
        raise T5ConfigurationError(key="launcher_paths", status="malformed")

    environment = {
        "PATH": f"{python_prefix / 'bin'}:/usr/local/bin:/usr/bin:/bin",
        "HOME": str(home),
        "TMPDIR": "/tmp",
        "LANG": "C.UTF-8",
        "PYTHONUTF8": "1",
    }
    if notify_socket:
        environment["NOTIFY_SOCKET"] = notify_socket
    environment.update(projection)
    unexpected_environment = (
        set(environment)
        - _OPERATING_SYSTEM_ENVIRONMENT
        - ROLE_CONFIGURATION_KEYS[role]
        - {"NOTIFY_SOCKET"}
    )
    if unexpected_environment:
        raise T5ConfigurationError(key="projection", status="role_unauthorized")
    return environment


def _emit_preflight(
    role: str,
    *,
    configuration: str,
    dependencies: str,
    runtime: str,
    failure: Mapping[str, str] | None = None,
    keys: Mapping[str, str] | None = None,
) -> None:
    payload: dict[str, object] = {
        "event": "launcher_preflight",
        "role": role,
        "configuration": configuration,
        "dependencies": dependencies,
        "runtime": runtime,
    }
    if failure is not None:
        payload["failure"] = dict(failure)
    if keys is not None:
        payload["keys"] = dict(sorted(keys.items()))
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")), flush=True)


def _run(
    role: str,
    *,
    preflight_only: bool,
    config_file: Path,
) -> int:
    if os.geteuid() != 0:
        _emit_preflight(
            role,
            configuration="not_checked",
            dependencies="failed",
            runtime="not_started",
            failure={"status": "launcher_requires_root"},
        )
        return 77
    if not preflight_only and config_file != PRODUCTION_MASTER_ENV_PATH:
        _emit_preflight(
            role,
            configuration="not_checked",
            dependencies="not_checked",
            runtime="not_started",
            failure={"status": "config_file_requires_preflight_only"},
        )
        return 78
    try:
        master_values = read_master_env_file(config_file)
        projection = project_role(master_values, role)
        report = preflight_role(role, projection)
    except T5ConfigurationError as error:
        _emit_preflight(
            role,
            configuration="failed",
            dependencies="not_checked",
            runtime="not_started",
            failure={"key": error.key, "status": error.status},
        )
        return 78
    if not report.configuration_ready:
        public = report.to_public_dict()
        _emit_preflight(
            role,
            configuration="failed",
            dependencies="not_checked",
            runtime="not_started",
            keys={
                str(key): str(status)
                for key, status in cast(dict[str, str], public["keys"]).items()
            },
        )
        return 78
    if preflight_only:
        public = report.to_public_dict()
        _emit_preflight(
            role,
            configuration="ready",
            dependencies="not_checked",
            runtime="not_started",
            keys={
                str(key): str(status)
                for key, status in cast(dict[str, str], public["keys"]).items()
            },
        )
        return 0

    try:
        runtime_user = pwd.getpwnam(ROLE_OS_USERS[role])
    except KeyError:
        _emit_preflight(
            role,
            configuration="ready",
            dependencies="failed",
            runtime="not_started",
            failure={"status": "runtime_user_unavailable"},
        )
        return 78
    environment = build_role_environment(
        role,
        projection,
        python_prefix=Path(sys.prefix),
        home=Path(runtime_user.pw_dir),
        notify_socket=os.environ.get("NOTIFY_SOCKET"),
    )
    service_path = REPOSITORY_ROOT / "apps" / "runtime_service.py"
    try:
        os.chdir(REPOSITORY_ROOT)
        os.umask(0o077)
        os.setgroups([])
        os.setgid(runtime_user.pw_gid)
        os.setuid(runtime_user.pw_uid)
        os.execve(
            sys.executable,
            (sys.executable, "-I", "-B", str(service_path), "--role", role),
            environment,
        )
    except OSError:
        _emit_preflight(
            role,
            configuration="ready",
            dependencies="failed",
            runtime="not_started",
            failure={"status": "privilege_drop_or_exec_failed"},
        )
        return 78
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=sorted(SERVICE_ROLES), required=True)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument(
        "--config-file",
        type=Path,
        default=PRODUCTION_MASTER_ENV_PATH,
    )
    arguments = parser.parse_args(argv)
    return _run(
        arguments.role,
        preflight_only=arguments.preflight_only,
        config_file=arguments.config_file,
    )


if __name__ == "__main__":
    raise SystemExit(main())
