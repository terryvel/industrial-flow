from __future__ import annotations

import json
from pathlib import Path
from threading import Lock


class PointIdCacheStore:
    """Persistent cache for PI point IDs, isolated by site and PI Server.

    JSON structure:
    {
      "sites": {
        "site1": {
          "servers": {
            "PI-SERVER-1": {
              "tags": {
                "TAG_A": 12345
              }
            }
          }
        }
      }
    }
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def load(self, site_id: str, server: str) -> dict[str, int]:
        with self._lock:
            payload = self._read_payload()
            tags = (
                payload.get("sites", {})
                .get(site_id, {})
                .get("servers", {})
                .get(server, {})
                .get("tags", {})
            )
            return {str(tag): int(point_id) for tag, point_id in tags.items()}

    def merge(self, site_id: str, server: str, point_ids: dict[str, int]) -> None:
        # Only cache successfully resolved point IDs. Missing tags are not persisted so a
        # tag created later in PI can be resolved on the next execution.
        valid_point_ids = {
            str(tag): int(point_id)
            for tag, point_id in point_ids.items()
            if point_id is not None and int(point_id) >= 0
        }
        if not valid_point_ids:
            return

        with self._lock:
            payload = self._read_payload()
            sites = payload.setdefault("sites", {})
            site_payload = sites.setdefault(site_id, {})
            servers = site_payload.setdefault("servers", {})
            server_payload = servers.setdefault(server, {})
            tags = server_payload.setdefault("tags", {})
            tags.update(valid_point_ids)
            self._write_payload(payload)

    def _read_payload(self) -> dict:
        if not self.path.exists():
            return {"sites": {}}
        with self.path.open("r", encoding="utf-8") as fp:
            try:
                payload = json.load(fp)
            except json.JSONDecodeError:
                return {"sites": {}}
        if not isinstance(payload, dict):
            return {"sites": {}}
        payload.setdefault("sites", {})
        return payload

    def _write_payload(self, payload: dict) -> None:
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as fp:
            json.dump(payload, fp, indent=2, sort_keys=True)
        tmp.replace(self.path)
