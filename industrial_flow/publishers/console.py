from __future__ import annotations

import json
from datetime import datetime, timezone

from industrial_flow.models.event import TagEvent
from industrial_flow.publishers.base import Publisher


class ConsolePublisher(Publisher):
    def publish_batch(self, events: list[TagEvent]) -> None:
        if not events:
            return
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        site_id = events[0].site if events else "unknown"
        server = events[0].server if events else "unknown"
        print(f"{timestamp} | {site_id} ({server}): published batch of {len(events)} events")

    def flush(self) -> None:
        return None
