"""Expose redacted systemd health and resource metrics for runtime roles."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.t5_runtime_configuration import ROLE_DATABASE_KEYS

_PROPERTY_NAMES = (
    "ActiveState",
    "SubState",
    "Result",
    "ExecMainStatus",
    "NRestarts",
    "CPUUsageNSec",
    "MemoryCurrent",
)
_STATUS_PATTERN = re.compile(r"[a-z][a-z0-9-]{0,31}\Z")


@dataclass(frozen=True, slots=True)
class RuntimeRoleHealth:
    """One low-cardinality, secret-free systemd role snapshot."""

    role: str
    active_state: str
    sub_state: str
    result: str
    main_status: int | None
    restart_count: int | None
    cpu_usage_ns: int | None
    memory_bytes: int | None
    failure: str | None = None

    @property
    def healthy(self) -> bool:
        """Require a running, notified role with a successful main process."""
        return (
            self.failure is None
            and self.active_state == "active"
            and self.sub_state == "running"
            and self.result == "success"
            and self.main_status == 0
        )

    def to_public_dict(self) -> dict[str, object]:
        """Return role state and systemd counters without arbitrary output."""
        result: dict[str, object] = {
            "role": self.role,
            "healthy": self.healthy,
            "active_state": self.active_state,
            "sub_state": self.sub_state,
            "result": self.result,
            "main_status": self.main_status,
            "restart_count": self.restart_count,
            "cpu_usage_ns": self.cpu_usage_ns,
            "memory_bytes": self.memory_bytes,
        }
        if self.failure is not None:
            result["failure"] = self.failure
        return result


def parse_systemd_show_output(role: str, output: str) -> RuntimeRoleHealth:
    """Parse only the fixed, nonsecret systemd health property allowlist."""
    if role not in ROLE_DATABASE_KEYS:
        return _unavailable("unknown", "runtime_role_unknown")
    properties: dict[str, str] = {}
    try:
        for line in output.splitlines():
            if "=" not in line:
                raise ValueError
            name, value = line.split("=", maxsplit=1)
            if name not in _PROPERTY_NAMES:
                continue
            if name in properties:
                raise ValueError
            properties[name] = value
        if set(properties) != set(_PROPERTY_NAMES):
            raise ValueError
        status_values = tuple(
            properties[name] for name in ("ActiveState", "SubState", "Result")
        )
        if any(_STATUS_PATTERN.fullmatch(value) is None for value in status_values):
            raise ValueError
        return RuntimeRoleHealth(
            role=role,
            active_state=properties["ActiveState"],
            sub_state=properties["SubState"],
            result=properties["Result"],
            main_status=_nonnegative_integer(properties["ExecMainStatus"]),
            restart_count=_nonnegative_integer(properties["NRestarts"]),
            cpu_usage_ns=_nonnegative_integer(properties["CPUUsageNSec"]),
            memory_bytes=_nonnegative_integer(properties["MemoryCurrent"]),
        )
    except (KeyError, ValueError):
        return _unavailable(role, "systemd_status_malformed")


def _nonnegative_integer(value: str) -> int:
    if not value.isascii() or not value.isdecimal() or len(value) > 20:
        raise ValueError
    return int(value)


def _unavailable(role: str, failure: str) -> RuntimeRoleHealth:
    return RuntimeRoleHealth(
        role=role,
        active_state="unknown",
        sub_state="unknown",
        result="unknown",
        main_status=None,
        restart_count=None,
        cpu_usage_ns=None,
        memory_bytes=None,
        failure=failure,
    )


def _query_role(role: str) -> RuntimeRoleHealth:
    properties = ",".join(_PROPERTY_NAMES)
    environment = {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}
    try:
        response = subprocess.run(
            (
                "/usr/bin/systemctl",
                "show",
                f"--property={properties}",
                f"football-bot-role@{role}.service",
            ),
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired):
        return _unavailable(role, "systemd_unavailable")
    if response.returncode != 0:
        return _unavailable(role, "systemd_unavailable")
    return parse_systemd_show_output(role, response.stdout)


def main() -> int:
    """Print one safe metrics snapshot and exit nonzero if any role is unhealthy."""
    roles = {
        role: _query_role(role).to_public_dict() for role in sorted(ROLE_DATABASE_KEYS)
    }
    healthy = all(bool(status["healthy"]) for status in roles.values())
    print(
        json.dumps(
            {"event": "runtime_health", "healthy": healthy, "roles": roles},
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
