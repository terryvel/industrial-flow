from __future__ import annotations

import hashlib
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
    event_id: str | None = None

    def __post_init__(self) -> None:
        if self.event_id is None:
            self.event_id = self.idempotency_key()

    def _identity_source(self) -> str:
        ts = self.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = ts.astimezone(timezone.utc)
        return f"{self.site}|{self.tag}|{ts.isoformat()}"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        ts = self.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        payload["timestamp"] = ts.isoformat().replace("+00:00", "Z")
        payload["event_id"] = self.idempotency_key()
        if payload.get("value") is not None and not isinstance(payload["value"], str):
            payload["value"] = str(payload["value"])
        for field in ("point_id", "digital_code", "digital_set_id", "digital_state_id", "raw_istat"):
            value = payload.get(field)
            if value is None:
                continue
            try:
                payload[field] = int(value)
            except (TypeError, ValueError):
                payload[field] = None
        return payload

    def idempotency_key(self) -> str:
        normalized = self._identity_source().encode("utf-8")
        return hashlib.md5(normalized).hexdigest()
