from __future__ import annotations

from pathlib import Path
from typing import Literal
import os

import yaml
from pydantic import BaseModel, Field, model_validator


class PIConfig(BaseModel):
    provider: Literal["piapi", "simulator"] = "simulator"
    server: str = "PI-SERVER-01"
    pi_timezone: str = "America/Sao_Paulo"
    username: str | None = None
    password: str | None = None
    site: str = "default-site"
    read_mode: Literal["interpolated", "snapshot"] = "interpolated"

    @model_validator(mode="after")
    def load_password_from_env(self):
        if not self.password:
            self.password = os.getenv("PI_PASSWORD")
        return self


class ReadConfig(BaseModel):
    interval_seconds: int = 60
    window_seconds: int = 300
    tag_partition_size: int = 500
    max_workers: int = 8
    batch_size: int = 10000
    queue_max_size: int = 50
    max_publish_retries: int = 3
    retry_sleep_seconds: float = 2.0


class CacheConfig(BaseModel):
    point_cache_file: str = ".cache/industrial-flow-pointids.json"
    digital_state_cache_file: str = ".cache/industrial-flow-digital-states.json"


class KafkaConfig(BaseModel):
    bootstrap_servers: str = "localhost:9092"
    topic: str = "industrial-flow.pi-tags"
    client_id: str = "industrial-flow"
    compression_type: str = "snappy"
    linger_ms: int = 50
    batch_num_messages: int = 10000
    message_timeout_ms: int = 300000
    extra: dict[str, str | int | float | bool] = Field(default_factory=dict)


class PubSubConfig(BaseModel):
    project_id: str = "my-gcp-project"
    topic_id: str = "industrial-flow-pi-tags"
    ordering_key_by_tag: bool = False
    timeout_seconds: float = 60.0


class WriterPubSubConfig(BaseModel):
    project_id: str | None = None
    subscription_id: str | None = None
    service_account_file: str | None = None


class WriterConfig(BaseModel):
    type: Literal["console", "pubsub"] = "console"
    pubsub: WriterPubSubConfig = Field(default_factory=WriterPubSubConfig)


class FileConfig(BaseModel):
    output_path: str = "output/events.jsonl"


class BigQueryConfig(BaseModel):
    project_id: str | None = None
    dataset: str = "industrial"
    table: str = "pi_data"
    location: str | None = None
    service_account_file: str | None = None
    max_batch_rows: int = 1000
    timeout_seconds: float = 60.0


class GCSConfig(BaseModel):
    bucket: str | None = None
    prefix: str = "industrial-flow/parquet"
    temp_prefix: str = "industrial-flow/temp"
    service_account_file: str | None = None
    delete_local_file_after_upload: bool = True
    timeout_seconds: float = 60.0


class ParquetConfig(BaseModel):
    output_dir: str = "output/parquet"
    file_prefix: str = "industrial-flow"
    compression: str = "snappy"
    row_group_size: int = 10000


class PublisherConfig(BaseModel):
    type: Literal["kafka", "pubsub", "file", "console", "bigquery", "parquet", "parquet_gcs", "parquet_gcs_bigquery"] = "console"
    read: ReadConfig | None = None
    kafka: KafkaConfig = Field(default_factory=KafkaConfig)
    pubsub: PubSubConfig = Field(default_factory=PubSubConfig)
    file: FileConfig = Field(default_factory=FileConfig)
    bigquery: BigQueryConfig = Field(default_factory=BigQueryConfig)
    gcs: GCSConfig = Field(default_factory=GCSConfig)
    parquet: ParquetConfig = Field(default_factory=ParquetConfig)

    def is_configured(self, publisher_type: str | None = None) -> bool:
        selected = (publisher_type or self.type or "console").lower()
        if selected == "console":
            return True
        if selected == "file":
            return bool(self.file.output_path)
        if selected == "kafka":
            return bool(self.kafka.bootstrap_servers and self.kafka.topic)
        if selected == "pubsub":
            return bool(self.pubsub.project_id and self.pubsub.topic_id)
        if selected == "bigquery":
            return bool(self.bigquery.project_id and self.bigquery.dataset and self.bigquery.table)
        if selected == "parquet":
            return bool(self.parquet.output_dir)
        if selected == "parquet_gcs":
            return bool(self.parquet.output_dir) and bool(self.gcs.bucket)
        if selected == "parquet_gcs_bigquery":
            return (
                bool(self.parquet.output_dir)
                and bool(self.gcs.bucket)
                and bool(self.bigquery.project_id)
                and bool(self.bigquery.dataset)
                and bool(self.bigquery.table)
            )
        return False


class SiteConfig(BaseModel):
    id: str
    pi: PIConfig
    tags_file: str
    read: ReadConfig | None = None
    enabled: bool = True

    @model_validator(mode="after")
    def sync_site_id_to_pi_config(self):
        self.pi.site = self.id
        return self


class AppConfig(BaseModel):
    # Site configuration. At least one site must be defined under `sites:`.
    sites: list[SiteConfig] = Field(default_factory=list)

    read: ReadConfig = Field(default_factory=ReadConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    writer: WriterConfig = Field(default_factory=WriterConfig)
    realtime: PublisherConfig = Field(default_factory=PublisherConfig)
    historical: PublisherConfig = Field(
        default_factory=lambda: PublisherConfig(type="parquet")
    )

    @model_validator(mode="after")
    def require_at_least_one_site(self):
        if not self.sites:
            raise ValueError("At least one site must be defined under 'sites:'")
        return self

    def enabled_sites(self) -> list[SiteConfig]:
        return [site for site in self.sites if site.enabled]

    def site_by_id(self, site_id: str) -> SiteConfig:
        for site in self.sites:
            if site.id == site_id:
                return site
        raise ValueError(f"Site not found in config: {site_id}")

    def read_for_site(self, site: SiteConfig, mode: Literal["realtime", "historical"]) -> ReadConfig:
        mode_read = self.publisher_for_mode(mode).read
        return mode_read or site.read or self.read

    def publisher_for_mode(self, mode: Literal["realtime", "historical"]) -> PublisherConfig:
        if mode == "realtime":
            return self.realtime
        if mode == "historical":
            return self.historical
        raise ValueError(f"Unsupported mode: {mode}")


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as fp:
        raw = yaml.safe_load(fp) or {}
    return AppConfig.model_validate(raw)
