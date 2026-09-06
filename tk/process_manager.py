from __future__ import annotations

import asyncio
import os
import sys
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from tk.models import LogEntry, LogSource, ProcessStatus, ServiceType


def get_workspace_root() -> Path:
    """Find the root directory of industrial-flow containing run.py."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "run.py").exists():
            return parent
    return Path.cwd()


@dataclass
class ServiceSpec:
    service_type: ServiceType
    config_path: str = "config/config.yaml"
    output_type: str | None = None
    site: str | None = None
    start: str | None = None
    end: str | None = None
    tags: str | None = None
    tag: str | None = None
    timestamp: str | None = None
    value: float | None = None
    istat: int = 0
    wait: bool = True

    def build_command_args(self) -> list[str]:
        root = get_workspace_root()
        run_py = str(root / "run.py")
        args = [sys.executable, run_py, self.service_type.value]

        args.extend(["--config", self.config_path])

        if self.service_type == ServiceType.REALTIME:
            if self.output_type:
                args.extend(["--type", self.output_type])
            if self.site:
                args.extend(["--site", self.site])

        elif self.service_type == ServiceType.HISTORICAL:
            if self.start:
                args.extend(["--start", self.start])
            if self.end:
                args.extend(["--end", self.end])
            if self.output_type:
                args.extend(["--type", self.output_type])
            if self.site:
                args.extend(["--site", self.site])
            if self.tags:
                args.extend(["--tags", self.tags])

        elif self.service_type == ServiceType.WRITER:
            if self.site:
                args.extend(["--site", self.site])
            if self.tag:
                args.extend(["--tag", self.tag])
            if self.timestamp:
                args.extend(["--timestamp", self.timestamp])
            if self.value is not None:
                args.extend(["--value", str(self.value)])
            if self.istat != 0:
                args.extend(["--istat", str(self.istat)])
            if not self.wait:
                args.append("--no-wait")

        return args

    def target_summary(self) -> str:
        if self.service_type == ServiceType.WRITER:
            return self.tag or "-"
        return self.output_type or "default"


class ManagedProcess:
    """Represents an asynchronous subprocess execution managed by the GUI."""

    def __init__(
        self,
        id_str: str,
        spec: ServiceSpec,
        log_callback: Callable[[ManagedProcess, LogEntry], None] | None = None,
        status_callback: Callable[[ManagedProcess], None] | None = None,
        max_log_lines: int = 2000,
    ):
        self.id = id_str
        self.spec = spec
        self.status = ProcessStatus.STARTING
        self.started_at: datetime = datetime.now(timezone.utc)
        self.ended_at: datetime | None = None
        self.pid: int | None = None
        self.returncode: int | None = None
        self.command_args = spec.build_command_args()
        self.log_entries: deque[LogEntry] = deque(maxlen=max_log_lines)
        self.log_callback = log_callback
        self.status_callback = status_callback
        self._process: asyncio.subprocess.Process | None = None
        self._reader_tasks: list[asyncio.Task] = []

    def set_status(self, new_status: ProcessStatus) -> None:
        self.status = new_status
        if self.status_callback:
            try:
                self.status_callback(self)
            except Exception:
                pass

    def add_log(self, text: str, source: LogSource = LogSource.STDOUT) -> None:
        entry = LogEntry(timestamp=datetime.now(timezone.utc), text=text, source=source)
        self.log_entries.append(entry)
        if self.log_callback:
            try:
                self.log_callback(self, entry)
            except Exception:
                pass

    def runtime_seconds(self) -> float:
        end = self.ended_at or datetime.now(timezone.utc)
        return (end - self.started_at).total_seconds()

    def formatted_runtime(self) -> str:
        secs = int(self.runtime_seconds())
        hrs = secs // 3600
        mins = (secs % 3600) // 60
        s = secs % 60
        if hrs > 0:
            return f"{hrs:02d}:{mins:02d}:{s:02d}"
        return f"{mins:02d}:{s:02d}"

    def formatted_started(self) -> str:
        ts = self.started_at.astimezone(timezone.utc)
        return ts.strftime("%H:%M:%S")

    async def start(self) -> None:
        self.set_status(ProcessStatus.STARTING)
        self.add_log(f"Executing: {' '.join(self.command_args)}", LogSource.SYSTEM)
        try:
            cwd = str(get_workspace_root())
            self._process = await asyncio.create_subprocess_exec(
                *self.command_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            self.pid = self._process.pid
            self.set_status(ProcessStatus.RUNNING)
            self.add_log(f"Started subprocess PID {self.pid}", LogSource.SYSTEM)

            t_out = asyncio.create_task(self._read_stream(self._process.stdout, LogSource.STDOUT))
            t_err = asyncio.create_task(self._read_stream(self._process.stderr, LogSource.STDERR))
            t_wait = asyncio.create_task(self._wait_process())
            self._reader_tasks = [t_out, t_err, t_wait]

        except Exception as exc:
            self.set_status(ProcessStatus.FAILED)
            self.ended_at = datetime.now(timezone.utc)
            self.add_log(f"Failed to launch process: {exc}", LogSource.SYSTEM)

    async def _read_stream(self, stream: asyncio.StreamReader | None, source: LogSource) -> None:
        if not stream:
            return
        while True:
            line = await stream.readline()
            if not line:
                break
            decoded = line.decode("utf-8", errors="replace").rstrip("\r\n")
            if decoded:
                self.add_log(decoded, source)

    async def _wait_process(self) -> None:
        if not self._process:
            return
        returncode = await self._process.wait()
        self.returncode = returncode
        self.ended_at = datetime.now(timezone.utc)
        if self.status in (ProcessStatus.STOPPING, ProcessStatus.STOPPED):
            self.set_status(ProcessStatus.STOPPED)
            self.add_log(f"Process stopped with return code {returncode}", LogSource.SYSTEM)
        elif returncode == 0:
            self.set_status(ProcessStatus.COMPLETED)
            self.add_log("Process completed successfully (return code 0)", LogSource.SYSTEM)
        else:
            self.set_status(ProcessStatus.FAILED)
            self.add_log(f"Process failed with return code {returncode}", LogSource.SYSTEM)

    async def stop(self, force: bool = False) -> None:
        if not self._process or self.status in (ProcessStatus.COMPLETED, ProcessStatus.FAILED, ProcessStatus.STOPPED):
            return

        self.set_status(ProcessStatus.STOPPING)
        pid = self.pid
        if pid is None:
            return

        if force:
            self.add_log(f"Force-killing process tree PID {pid}", LogSource.SYSTEM)
            self._force_kill(pid)
        else:
            self.add_log(f"Stopping process PID {pid} gracefully", LogSource.SYSTEM)
            try:
                if sys.platform == "win32":
                    # On Windows, taskkill /PID gracefully requests termination
                    os.system(f"taskkill /PID {pid} /T >NUL 2>&1")
                else:
                    self._process.terminate()
            except Exception as exc:
                self.add_log(f"Error terminating process: {exc}", LogSource.SYSTEM)

            # Give process up to 3 seconds to terminate gracefully, then force kill
            try:
                await asyncio.wait_for(self._process.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                self.add_log(f"Process PID {pid} did not exit in 3s; force killing", LogSource.SYSTEM)
                self._force_kill(pid)

    def _force_kill(self, pid: int) -> None:
        try:
            if sys.platform == "win32":
                os.system(f"taskkill /F /T /PID {pid} >NUL 2>&1")
            else:
                if self._process:
                    self._process.kill()
        except Exception:
            pass


class ProcessManager:
    """Manages multiple parallel subprocess executions."""

    def __init__(self, max_log_lines: int = 2000):
        self.max_log_lines = max_log_lines
        self.processes: dict[str, ManagedProcess] = {}
        self._next_id = 1
        self._log_listeners: list[Callable[[ManagedProcess, LogEntry], None]] = []
        self._status_listeners: list[Callable[[ManagedProcess], None]] = []

    def add_log_listener(self, callback: Callable[[ManagedProcess, LogEntry], None]) -> None:
        self._log_listeners.append(callback)

    def add_status_listener(self, callback: Callable[[ManagedProcess], None]) -> None:
        self._status_listeners.append(callback)

    def _on_log(self, proc: ManagedProcess, entry: LogEntry) -> None:
        for listener in self._log_listeners:
            try:
                listener(proc, entry)
            except Exception:
                pass

    def _on_status(self, proc: ManagedProcess) -> None:
        for listener in self._status_listeners:
            try:
                listener(proc)
            except Exception:
                pass

    async def start_service(self, spec: ServiceSpec) -> ManagedProcess:
        id_str = f"{self._next_id:02d}"
        self._next_id += 1
        proc = ManagedProcess(
            id_str=id_str,
            spec=spec,
            log_callback=self._on_log,
            status_callback=self._on_status,
            max_log_lines=self.max_log_lines,
        )
        self.processes[id_str] = proc
        await proc.start()
        return proc

    async def restart_service(self, id_str: str) -> ManagedProcess | None:
        old_proc = self.processes.get(id_str)
        if not old_proc:
            return None
        await old_proc.stop(force=True)
        return await self.start_service(old_proc.spec)

    async def stop_service(self, id_str: str, force: bool = False) -> None:
        proc = self.processes.get(id_str)
        if proc:
            await proc.stop(force=force)

    async def stop_all(self, force: bool = False) -> None:
        tasks = [proc.stop(force=force) for proc in self.processes.values()]
        if tasks:
            await asyncio.gather(*tasks)

    def active_count(self) -> int:
        return sum(
            1 for proc in self.processes.values()
            if proc.status in (ProcessStatus.STARTING, ProcessStatus.RUNNING, ProcessStatus.STOPPING)
        )

    def get_process(self, id_str: str) -> ManagedProcess | None:
        return self.processes.get(id_str)

    def list_processes(self) -> list[ManagedProcess]:
        return sorted(self.processes.values(), key=lambda p: p.id)
