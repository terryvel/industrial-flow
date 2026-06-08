from __future__ import annotations

import json

from industrial_flow.config import PubSubConfig
from industrial_flow.models.event import TagEvent
from industrial_flow.publishers.base import Publisher


class PubSubPublisher(Publisher):
    def __init__(self, config: PubSubConfig):
        try:
            from google.cloud import pubsub_v1
        except ImportError as exc:
            raise RuntimeError("Install Pub/Sub dependencies with: pip install 'industrial-flow[pubsub]'") from exc

        self.config = config
        self.publisher = pubsub_v1.PublisherClient()
        self.topic_path = self.publisher.topic_path(config.project_id, config.topic_id)

    def publish_batch(self, events: list[TagEvent]) -> None:
        futures = []
        for event in events:
            payload = event.to_dict()
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            attrs = {
                "tag": event.tag,
                "site": event.site,
                "server": event.server,
                "quality": event.quality,
            }
            if self.config.ordering_key_by_tag:
                future = self.publisher.publish(
                    self.topic_path,
                    data,
                    ordering_key=event.tag,
                    **attrs,
                )
            else:
                future = self.publisher.publish(self.topic_path, data, **attrs)
            futures.append(future)

        for future in futures:
            future.result(timeout=self.config.timeout_seconds)

    def flush(self) -> None:
        return None
