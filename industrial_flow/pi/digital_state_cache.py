from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from industrial_flow.pi.digital_state import DigitalStateInfo


class DigitalStateCacheStore:
    """Persistent cache of resolved PI Digital State text.

    Cache key hierarchy:
    site -> pi_server -> digital_code

    The legacy PI API function pipt_digstate() receives the negative digital code
    directly, so this cache is intentionally keyed by the raw digital_code rather
    than only by digital_set_id/digital_state_id.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def _read_all(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        with self.path.open("r", encoding="utf-8") as fp:
            return json.load(fp)

    def _write_all(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            with tmp_path.open("w", encoding="utf-8") as fp:
                json.dump(data, fp, ensure_ascii=False, indent=2, sort_keys=True)
            tmp_path.replace(self.path)
        except PermissionError:
            # Windows can deny atomic replace when the target file is being held open by
            # another process or the antivirus is scanning it. Fall back to a direct write
            # instead of crashing the ingestion loop.
            with self.path.open("w", encoding="utf-8") as fp:
                json.dump(data, fp, ensure_ascii=False, indent=2, sort_keys=True)
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    @staticmethod
    def _server_key(server: str) -> str:
        return server.lower()

    @staticmethod
    def _code_key(digital_code: int) -> str:
        return str(int(digital_code))

    def load(self, site: str, server: str) -> dict[int, DigitalStateInfo]:
        with self._lock:
            data = self._read_all()

        site_data = data.get(site, {})
        server_data = site_data.get(self._server_key(server), {})
        result: dict[int, DigitalStateInfo] = {}

        for code_text, payload in server_data.items():
            info = DigitalStateInfo(
                digital_code=int(payload.get("digital_code", code_text)),
                digital_state_name=payload.get("digital_state_name"),
                digital_set_id=payload.get("digital_set_id"),
                digital_state_id=payload.get("digital_state_id"),
                source=payload.get("source", "cache"),
            )
            result[info.digital_code] = info

        return result

    def merge(self, site: str, server: str, states: dict[int, DigitalStateInfo]) -> None:
        if not states:
            return

        with self._lock:
            data = self._read_all()
            site_data = data.setdefault(site, {})
            server_data = site_data.setdefault(self._server_key(server), {})

            for digital_code, info in states.items():
                server_data[self._code_key(digital_code)] = info.to_dict()

            self._write_all(data)
