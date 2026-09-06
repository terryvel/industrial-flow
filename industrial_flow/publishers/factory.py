from __future__ import annotations

from industrial_flow.config import PublisherConfig
from industrial_flow.publishers.base import Publisher
from industrial_flow.publishers.bigquery import (
    BigQueryPublisher,
    ParquetGCSBigQueryPublisher,
    ParquetGCSPublisher,
    ParquetPublisher,
)
from industrial_flow.publishers.console import ConsolePublisher
from industrial_flow.publishers.file import JsonlFilePublisher
from industrial_flow.publishers.kafka import KafkaPublisher
from industrial_flow.publishers.pubsub import PubSubPublisher


def create_publisher(config: PublisherConfig) -> Publisher:
    if config.type == "console":
        return ConsolePublisher()
    if config.type == "file":
        return JsonlFilePublisher(config.file)
    if config.type == "kafka":
        return KafkaPublisher(config.kafka)
    if config.type == "pubsub":
        return PubSubPublisher(config.pubsub)
    if config.type == "bigquery":
        return BigQueryPublisher(config.bigquery)
    if config.type == "parquet":
        return ParquetPublisher(config.parquet)
    if config.type == "parquet_gcs":
        return ParquetGCSPublisher(config.bigquery, config.gcs, config.parquet)
    if config.type == "parquet_gcs_bigquery":
        return ParquetGCSBigQueryPublisher(config.bigquery, config.gcs, config.parquet)
    raise ValueError(f"Unsupported publisher: {config.type}")
