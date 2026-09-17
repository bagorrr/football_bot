from __future__ import annotations

from apps.runtime_health import parse_systemd_show_output


def test_runtime_health_exposes_low_cardinality_systemd_metrics() -> None:
    report = parse_systemd_show_output(
        "ingestion",
        "\n".join(
            (
                "ActiveState=active",
                "SubState=running",
                "Result=success",
                "ExecMainStatus=0",
                "NRestarts=2",
                "CPUUsageNSec=1200000",
                "MemoryCurrent=4096",
            )
        ),
    )

    assert report.healthy
    assert report.restart_count == 2
    assert report.cpu_usage_ns == 1_200_000
    assert report.memory_bytes == 4096
    assert report.to_public_dict() == {
        "role": "ingestion",
        "healthy": True,
        "active_state": "active",
        "sub_state": "running",
        "result": "success",
        "main_status": 0,
        "restart_count": 2,
        "cpu_usage_ns": 1_200_000,
        "memory_bytes": 4096,
    }


def test_runtime_health_preserves_inactive_state_with_unset_resource_counters() -> None:
    report = parse_systemd_show_output(
        "ingestion",
        "\n".join(
            (
                "ActiveState=inactive",
                "SubState=dead",
                "Result=success",
                "ExecMainStatus=0",
                "NRestarts=0",
                "CPUUsageNSec=[not set]",
                "MemoryCurrent=[not set]",
            )
        ),
    )

    assert not report.healthy
    assert report.failure is None
    assert report.active_state == "inactive"
    assert report.sub_state == "dead"
    assert report.result == "success"
    assert report.cpu_usage_ns is None
    assert report.memory_bytes is None


def test_runtime_health_fails_closed_and_redacts_malformed_systemd_output() -> None:
    report = parse_systemd_show_output(
        "bot_assistant",
        "ActiveState=failed\nSubState=failed\nResult=watchdog\n"
        "ExecMainStatus=secret\nNRestarts=1\nCPUUsageNSec=10\n"
        "MemoryCurrent=20\nDATABASE_URL=must-not-escape",
    )

    assert not report.healthy
    assert report.failure == "systemd_status_malformed"
    assert "secret" not in repr(report.to_public_dict())
    assert "must-not-escape" not in repr(report.to_public_dict())
