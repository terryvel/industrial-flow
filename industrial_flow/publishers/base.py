from __future__ import annotations

from abc import ABC, abstractmethod

from industrial_flow.models.event import TagEvent


class Publisher(ABC):
    @abstractmethod
    def publish_batch(self, events: list[TagEvent]) -> None:
        pass

    @abstractmethod
    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.flush()
