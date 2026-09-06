from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class ProcessStatus(str, Enum):
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class LogSource(str, Enum):
    STDOUT = "STDOUT"
    STDERR = "STDERR"
    SYSTEM = "SYSTEM"


class ServiceType(str, Enum):
    REALTIME = "realtime"
    HISTORICAL = "historical"
    WRITER = "writer"


@dataclass(slots=True)
class LogEntry:
    timestamp: datetime
    text: str
    source: LogSource = LogSource.STDOUT

    def formatted_timestamp(self) -> str:
        ts = self.timestamp if self.timestamp.tzinfo else self.timestamp.replace(tzinfo=timezone.utc)
        return ts.strftime("%H:%M:%S")
