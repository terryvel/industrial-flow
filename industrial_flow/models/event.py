from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class TagEvent:
    source: str
    server: str
    site: str
    tag: str
    timestamp: datetime
    value: float | int | str | None
    quality: str = "GOOD"
    point_id: int | None = None
    value_type: str = "numeric"
    digital_code: int | None = None
    digital_set_id: int | None = None
    digital_state_id: int | None = None
    digital_state_name: str | None = None
    raw_istat: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        ts = self.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        payload["timestamp"] = ts.isoformat().replace("+00:00", "Z")
        return payload
