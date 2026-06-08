from __future__ import annotations

import json
from pathlib import Path

from industrial_flow.config import FileConfig
from industrial_flow.models.event import TagEvent
from industrial_flow.publishers.base import Publisher


class JsonlFilePublisher(Publisher):
    def __init__(self, config: FileConfig):
        self.path = Path(config.output_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fp = self.path.open("a", encoding="utf-8")

    def publish_batch(self, events: list[TagEvent]) -> None:
        for event in events:
            self._fp.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

    def flush(self) -> None:
        self._fp.flush()

    def close(self) -> None:
        self._fp.flush()
        self._fp.close()
