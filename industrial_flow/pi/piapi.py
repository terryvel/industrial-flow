from __future__ import annotations

import ctypes
import platform
from ctypes import byref, c_float, c_int, create_string_buffer, pointer
from datetime import datetime, timedelta
from threading import Lock

# Global lock to serialize all access to the legacy PI API DLL (which is not thread-safe)
_global_piapi_lock = Lock()

# Tracks which server is currently active in the process-wide DLL state
_active_server_in_dll: str | None = None

from industrial_flow.config import PIConfig
from industrial_flow.models.event import TagEvent
from industrial_flow.pi.base import PIReader
from industrial_flow.pi.digital_state import DigitalStateInfo, decode_negative_istat, unresolved_digital_state


class PIAPIError(RuntimeError):
    pass


class PIAPIReader(PIReader):
    """
    Windows PI API reader based on legacy PI API DLLs.

    Performance design:
    - point IDs are resolved once per reader and cached in _point_cache;
    - the engine creates independent readers by site and tag partition;
    - low-level DLL calls are protected by a per-reader lock because legacy PI API
      installations may not be safe for shared mutable calls.
    """

    def __init__(self, config: PIConfig):
        self.config = config
        self.piapi = None
        self._point_cache: dict[str, int] = {}
        self._digital_state_cache: dict[int, DigitalStateInfo] = {}

    def _ensure_active_server(self) -> None:
        """Ensure the process-wide active server node is set to this reader's target server.
        Must be called within the global lock.
        """
        global _active_server_in_dll
        if self.piapi is not None and _active_server_in_dll != self.config.server:
            if hasattr(self.piapi, "piut_setservernode"):
                server_buf = create_string_buffer(self.config.server.encode("utf-8"))
                self.piapi.piut_setservernode(pointer(server_buf))
            _active_server_in_dll = self.config.server

    @property
    def point_cache(self) -> dict[str, int]:
        return dict(self._point_cache)


    def preload_point_cache(self, point_ids: dict[str, int]) -> None:
        self._point_cache.update({tag: int(point_id) for tag, point_id in point_ids.items()})

    def export_point_cache(self) -> dict[str, int]:
        return {tag: point_id for tag, point_id in self._point_cache.items() if point_id >= 0}

    def preload_digital_state_cache(self, states: dict[int, DigitalStateInfo]) -> None:
        self._digital_state_cache.update(states)

    def export_digital_state_cache(self) -> dict[int, DigitalStateInfo]:
        return dict(self._digital_state_cache)

    def _decode_pi_string(self, raw: bytes) -> str:
        for encoding in ("utf-8", "mbcs", "latin-1"):
            try:
                return raw.decode(encoding).strip()
            except LookupError:
                continue
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace").strip()

    def _resolve_digital_state(self, digital_code: int, set_id: int | None = None, state_id: int | None = None) -> DigitalStateInfo | None:
        """Resolve a PI Digital State name through the legacy PI API.

        pipt_digstate receives the negative digital code returned in istat and
        writes the human-readable state text into the provided char buffer.
        Results are cached in memory and later persisted by the engine.
        """
        cached = self._digital_state_cache.get(digital_code)
        if cached:
            return cached

        if self.piapi is None or not hasattr(self.piapi, "pipt_digstate"):
            return None

        buffer_size = 256
        state_buffer = create_string_buffer(buffer_size)

        with _global_piapi_lock:
            self._ensure_active_server()
            status = self.piapi.pipt_digstate(
                c_int(digital_code),
                state_buffer,
                c_int(buffer_size),
            )

        if status != 0:
            return None

        state_name = self._decode_pi_string(state_buffer.value)
        info = DigitalStateInfo(
            digital_code=digital_code,
            digital_state_name=state_name or None,
            digital_set_id=set_id,
            digital_state_id=state_id,
            source="piapi.pipt_digstate",
        )
        self._digital_state_cache[digital_code] = info
        return info

    def connect(self) -> None:
        arch = platform.architecture()[0]
        if arch == "64bit":
            self.piapi = ctypes.windll.piapi
        elif arch == "32bit":
            self.piapi = ctypes.windll.piapi32
        else:
            raise PIAPIError(f"Unsupported architecture: {arch}")

        server = create_string_buffer(self.config.server.encode("utf-8"))
        username = create_string_buffer((self.config.username or "").encode("utf-8"))
        password = create_string_buffer((self.config.password or "").encode("utf-8"))
        valid = c_int(0)

        with _global_piapi_lock:
            global _active_server_in_dll
            self.piapi.piut_setservernode(pointer(server))
            _active_server_in_dll = self.config.server
            status = self.piapi.piut_login(pointer(username), pointer(password), pointer(valid))

        if status != 0 or valid.value == 0:
            raise PIAPIError(f"Failed to login to PI Server {self.config.server}. status={status}")

    def cache_points(self, tags: list[str]) -> None:
        if self.piapi is None:
            raise PIAPIError("PI API is not connected")

        missing = 0
        for tag in tags:
            if tag in self._point_cache:
                continue
            point_id = c_int()
            tag_buffer = create_string_buffer(tag.encode("utf-8"))
            with _global_piapi_lock:
                self._ensure_active_server()
                status = self.piapi.pipt_findpoint(tag_buffer, byref(point_id))
            if status == 0:
                self._point_cache[tag] = point_id.value
            else:
                missing += 1
                self._point_cache[tag] = -1
        if missing:
            # Intentionally not raising: one bad tag should not stop an entire plant ingestion.
            pass

    def _parse_time(self, value: datetime) -> c_int:
        assert self.piapi is not None
        timedate = c_int()
        text = value.strftime(self.config.timestamp_format).encode("utf-8")
        time_buffer = create_string_buffer(text)
        with _global_piapi_lock:
            self._ensure_active_server()
            status = self.piapi.pitm_parsetime(time_buffer, 1, byref(timedate))
        if status != 0:
            raise PIAPIError(f"Error parsing PI time {text!r}: {status}")
        return timedate

    def read_interpolated_values(
        self,
        tags: list[str],
        start: datetime,
        end: datetime,
        interval_seconds: int,
    ) -> list[TagEvent]:
        if self.piapi is None:
            raise PIAPIError("PI API is not connected")

        events: list[TagEvent] = []
        current = start
        while current < end:
            pi_time = self._parse_time(current)
            for tag in tags:
                point_id = self._point_cache.get(tag, -1)
                if point_id < 0:
                    events.append(
                        TagEvent(
                            source="piapi",
                            server=self.config.server,
                            site=self.config.site,
                            tag=tag,
                            timestamp=current,
                            value=None,
                            quality="BAD_POINT_NOT_FOUND",
                            point_id=None,
                        )
                    )
                    continue

                mode = c_int(3)
                rval = c_float()
                istats = c_int()
                point_id_c = c_int(point_id)

                with _global_piapi_lock:
                    self._ensure_active_server()
                    status = self.piapi.piar_value(
                        point_id_c,
                        byref(pi_time),
                        mode,
                        byref(rval),
                        byref(istats),
                    )

                value: float | int | str | None
                quality = "GOOD"
                value_type = "numeric"
                digital_set_id = None
                digital_state_id = None
                digital_code = None
                digital_state_name = None
                raw_istat = istats.value

                if status != 0:
                    value = None
                    quality = f"BAD_STATUS_{status}"
                    value_type = "error"
                else:
                    decoded = decode_negative_istat(istats.value)
                    if decoded:
                        resolved = self._resolve_digital_state(
                            decoded.digital_code,
                            decoded.digital_set_id,
                            decoded.digital_state_id,
                        )
                        if resolved is None:
                            resolved = unresolved_digital_state(decoded)
                            self._digital_state_cache[resolved.digital_code] = resolved

                        # Do not place the state ID in `value`; that would make a Digital State
                        # look like a numeric process measurement. Preserve the semantic fields.
                        value = resolved.digital_state_name
                        quality = "DIGITAL_STATE"
                        value_type = "digital"
                        digital_code = resolved.digital_code
                        digital_set_id = resolved.digital_set_id
                        digital_state_id = resolved.digital_state_id
                        digital_state_name = resolved.digital_state_name
                    else:
                        value = rval.value

                events.append(
                    TagEvent(
                        source="piapi",
                        server=self.config.server,
                        site=self.config.site,
                        tag=tag,
                        timestamp=current,
                        value=value,
                        quality=quality,
                        point_id=point_id,
                        value_type=value_type,
                        digital_set_id=digital_set_id,
                        digital_state_id=digital_state_id,
                        digital_code=digital_code,
                        digital_state_name=digital_state_name,
                        raw_istat=raw_istat,
                    )
                )
            current += timedelta(seconds=interval_seconds)

        return events
