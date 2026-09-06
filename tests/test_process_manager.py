from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tk.config_store import ConfigStore
from tk.models import LogSource, ProcessStatus, ServiceType
from tk.process_manager import ManagedProcess, ProcessManager, ServiceSpec


def test_service_spec_builds_correct_cli_arguments():
    realtime_spec = ServiceSpec(
        service_type=ServiceType.REALTIME,
        config_path="config/config.yaml",
        output_type="bigquery",
        site="casa",
    )
    args = realtime_spec.build_command_args()
    assert "realtime" in args
    assert "--config" in args
    assert "config/config.yaml" in args
    assert "--type" in args
    assert "bigquery" in args
    assert "--site" in args
    assert "casa" in args

    historical_spec = ServiceSpec(
        service_type=ServiceType.HISTORICAL,
        config_path="config/config.yaml",
        start="2026-09-01T00:00:00Z",
        end="2026-09-02T00:00:00Z",
        output_type="parquet",
        site="casa",
        tags="SINUSOID,TAG001",
    )
    args_hist = historical_spec.build_command_args()
    assert "historical" in args_hist
    assert "--start" in args_hist
    assert "2026-09-01T00:00:00Z" in args_hist
    assert "--end" in args_hist
    assert "2026-09-02T00:00:00Z" in args_hist
    assert "--tags" in args_hist
    assert "SINUSOID,TAG001" in args_hist

    writer_spec = ServiceSpec(
        service_type=ServiceType.WRITER,
        config_path="config/config.yaml",
        site="casa",
        tag="SINUSOID",
        timestamp="2026-09-04T15:00:00-03:00",
        value=42.5,
        istat=0,
        wait=False,
    )
    args_writer = writer_spec.build_command_args()
    assert "writer" in args_writer
    assert "--site" in args_writer
    assert "--tag" in args_writer
    assert "--timestamp" in args_writer
    assert "--value" in args_writer
    assert "42.5" in args_writer
    assert "--no-wait" in args_writer


def test_managed_process_executes_and_captures_stdout_stderr(tmp_path):
    async def run_test():
        spec = ServiceSpec(service_type=ServiceType.REALTIME, config_path="config/config.yaml")
        proc = ManagedProcess(id_str="01", spec=spec)
        proc.command_args = [
            __import__("sys").executable,
            "-c",
            "import sys; print('stdout test'); sys.stderr.write('stderr test\\n')",
        ]

        await proc.start()
        await asyncio.sleep(0.5)

        assert proc.status == ProcessStatus.COMPLETED
        assert proc.returncode == 0
        logs = list(proc.log_entries)
        text_list = [entry.text for entry in logs]
        assert any("stdout test" in text for text in text_list)
        assert any("stderr test" in text for text in text_list)

    asyncio.run(run_test())


def test_process_manager_starts_and_stops_parallel_processes():
    async def run_test():
        manager = ProcessManager()
        spec1 = ServiceSpec(service_type=ServiceType.REALTIME, config_path="config/config.yaml")
        spec2 = ServiceSpec(service_type=ServiceType.REALTIME, config_path="config/config.yaml")

        proc1 = ManagedProcess("01", spec1)
        proc1.command_args = [__import__("sys").executable, "-c", "import time; time.sleep(5)"]

        proc2 = ManagedProcess("02", spec2)
        proc2.command_args = [__import__("sys").executable, "-c", "import time; time.sleep(5)"]

        manager.processes["01"] = proc1
        manager.processes["02"] = proc2

        await proc1.start()
        await proc2.start()

        assert manager.active_count() == 2

        await manager.stop_service("01", force=True)
        await manager.stop_service("02", force=True)

        await asyncio.sleep(0.3)
        assert manager.active_count() == 0

    asyncio.run(run_test())


def test_config_store_prevents_saving_invalid_yaml(tmp_path):
    config_file = tmp_path / "config.yaml"
    valid_yaml = (
        "sites:\n"
        "  - id: casa\n"
        "    pi:\n"
        "      provider: piapi\n"
        "      server: winos\n"
        "    tags_file: config/tags.txt\n"
    )
    config_file.write_text(valid_yaml, encoding="utf-8")

    store = ConfigStore(config_file)
    store.data["historical"] = {"type": "invalid_type_name"}

    with pytest.raises(Exception):
        store.save()

    # Original file must remain untouched
    content = config_file.read_text(encoding="utf-8")
    assert "invalid_type_name" not in content
