from __future__ import annotations

import json

from industrial_flow.models.event import TagEvent
from industrial_flow.publishers.base import Publisher


class ConsolePublisher(Publisher):
    def publish_batch(self, events: list[TagEvent]) -> None:
        for event in events:
            print(json.dumps(event.to_dict(), ensure_ascii=False))

    def flush(self) -> None:
        return None
