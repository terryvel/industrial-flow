from __future__ import annotations

import math
import random
from datetime import datetime, timedelta

from industrial_flow.config import PIConfig
from industrial_flow.models.event import TagEvent
from industrial_flow.pi.base import PIReader
from industrial_flow.pi.digital_state import DigitalStateInfo


class SimulatedPIReader(PIReader):
    """PI reader for local development, tests and demos without PI Server access."""

    def __init__(self, config: PIConfig):
        self.config = config
        self._point_cache: dict[str, int] = {}
        self._digital_state_cache: dict[int, DigitalStateInfo] = {}


    def preload_point_cache(self, point_ids: dict[str, int]) -> None:
        self._point_cache.update({tag: int(point_id) for tag, point_id in point_ids.items()})

    def export_point_cache(self) -> dict[str, int]:
        return {tag: point_id for tag, point_id in self._point_cache.items() if point_id >= 0}

    def preload_digital_state_cache(self, states: dict[int, DigitalStateInfo]) -> None:
        self._digital_state_cache.update(states)

    def export_digital_state_cache(self) -> dict[int, DigitalStateInfo]:
        return dict(self._digital_state_cache)

    def connect(self) -> None:
        return None

    def cache_points(self, tags: list[str]) -> None:
        for tag in tags:
            if tag not in self._point_cache:
                self._point_cache[tag] = abs(hash(tag)) % 10_000_000

    def read_interpolated_values(
        self,
        tags: list[str],
        start: datetime,
        end: datetime,
        interval_seconds: int,
    ) -> list[TagEvent]:
        events: list[TagEvent] = []
        current = start
        while current < end:
            minute = int(current.timestamp() // 60)
            for tag in tags:
                base = (abs(hash(tag)) % 1000) / 10
                wave = math.sin(minute / 10) * 5
                noise = random.random()
                events.append(
                    TagEvent(
                        source="pi-simulator",
                        server=self.config.server,
                        site=self.config.site,
                        tag=tag,
                        timestamp=current,
                        value=round(base + wave + noise, 4),
                        quality="GOOD",
                        point_id=self._point_cache.get(tag),
                    )
                )
            current += timedelta(seconds=interval_seconds)
        return events
