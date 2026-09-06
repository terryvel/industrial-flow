from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from industrial_flow.models.event import TagEvent
from industrial_flow.pi.digital_state import DigitalStateInfo


class PIReader(ABC):
    def is_connected(self) -> bool:
        """Return whether the underlying PI connection is currently considered active."""
        return True

    @abstractmethod
    def connect(self) -> None:
        pass

    @abstractmethod
    def cache_points(self, tags: list[str]) -> None:
        pass

    def preload_point_cache(self, point_ids: dict[str, int]) -> None:
        """Load previously resolved PI point IDs into the reader.

        Providers that do not use PI point IDs can ignore this method.
        """
        return None

    def export_point_cache(self) -> dict[str, int]:
        """Return point IDs resolved by this reader.

        Only successfully resolved point IDs should be returned.
        """
        return {}

    def preload_digital_state_cache(self, states: dict[int, DigitalStateInfo]) -> None:
        """Load cached Digital State names into the reader.

        Providers that cannot resolve Digital States can ignore this method, while
        still preserving Digital State IDs in the outgoing events.
        """
        return None

    def export_digital_state_cache(self) -> dict[int, DigitalStateInfo]:
        """Return Digital States resolved by this reader.

        Implementations should include only metadata that was actually resolved
        or intentionally loaded from configuration/cache.
        """
        return {}

    @abstractmethod
    def read_interpolated_values(
        self,
        tags: list[str],
        start: datetime,
        end: datetime,
        interval_seconds: int,
    ) -> list[TagEvent]:
        pass
