from __future__ import annotations

import json
from typing import Any

from industrial_flow.config import KafkaConfig
from industrial_flow.models.event import TagEvent
from industrial_flow.publishers.base import Publisher


class KafkaPublisher(Publisher):
    def __init__(self, config: KafkaConfig):
        try:
            from confluent_kafka import Producer
        except ImportError as exc:
            raise RuntimeError("Install Kafka dependencies with: pip install 'industrial-flow[kafka]'") from exc

        producer_config: dict[str, Any] = {
            "bootstrap.servers": config.bootstrap_servers,
            "client.id": config.client_id,
            "compression.type": config.compression_type,
            "linger.ms": config.linger_ms,
            "batch.num.messages": config.batch_num_messages,
            "message.timeout.ms": config.message_timeout_ms,
        }
        producer_config.update(config.extra)
        self.topic = config.topic
        self.producer = Producer(producer_config)
        self._errors: list[Exception] = []

    def _delivery_report(self, err, msg) -> None:
        if err is not None:
            self._errors.append(RuntimeError(f"Kafka delivery failed: {err}"))

    def publish_batch(self, events: list[TagEvent]) -> None:
        for event in events:
            payload = event.to_dict()
            self.producer.produce(
                self.topic,
                key=event.tag.encode("utf-8"),
                value=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                callback=self._delivery_report,
            )
            self.producer.poll(0)

        if self._errors:
            err = self._errors.pop(0)
            raise err

    def flush(self) -> None:
        self.producer.flush()
        if self._errors:
            err = self._errors.pop(0)
            raise err
