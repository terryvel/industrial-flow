from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from industrial_flow.utils.time_windows import parse_datetime


class CheckpointStore:
    """JSON checkpoint store with one independent checkpoint per site."""

    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read_payload(self) -> dict:
        if not self.path.exists():
            return {}
        with self.path.open("r", encoding="utf-8") as fp:
            return json.load(fp)

    def load(self, site_id: str = "default") -> datetime | None:
        payload = self._read_payload()

        # Backward compatibility with the original single-site checkpoint format.
        if "last_successful_end" in payload:
            value = payload.get("last_successful_end")
            return parse_datetime(value) if value else None

        value = payload.get("sites", {}).get(site_id, {}).get("last_successful_end")
        return parse_datetime(value) if value else None

    def save(self, last_successful_end: datetime, site_id: str = "default") -> None:
        payload = self._read_payload()
        if "sites" not in payload:
            payload = {"sites": {}}
        payload["sites"][site_id] = {"last_successful_end": last_successful_end.isoformat()}

        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as fp:
            json.dump(payload, fp, indent=2, sort_keys=True)
        tmp.replace(self.path)
