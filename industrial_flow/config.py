from __future__ import annotations

from pathlib import Path
from typing import Literal
import os

import yaml
from pydantic import BaseModel, Field, model_validator


class PIConfig(BaseModel):
    provider: Literal["piapi", "simulator"] = "simulator"
    server: str = "PI-SERVER-01"
    username: str | None = None
    password: str | None = None
    password_env: str | None = "PI_PASSWORD"
    site: str = "default-site"
    read_mode: Literal["interpolated", "snapshot"] = "interpolated"
    timestamp_format: str = "%d-%b-%y %H:%M:%S"

    @model_validator(mode="after")
    def load_password_from_env(self):
        if not self.password and self.password_env:
            self.password = os.getenv(self.password_env)
        return self


class ReadConfig(BaseModel):
    interval_seconds: int = 60
    window_seconds: int = 300
    tag_partition_size: int = 500
    max_workers: int = 8
    batch_size: int = 10000
    queue_max_size: int = 50
    checkpoint_file: str = ".checkpoints/industrial-flow.json"
    point_cache_file: str = ".cache/industrial-flow-pointids.json"
    digital_state_cache_file: str = ".cache/industrial-flow-digital-states.json"
    max_publish_retries: int = 3
    retry_sleep_seconds: float = 2.0


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


class FileConfig(BaseModel):
    output_path: str = "output/events.jsonl"


class PublisherConfig(BaseModel):
    type: Literal["kafka", "pubsub", "file", "console"] = "console"
    kafka: KafkaConfig = Field(default_factory=KafkaConfig)
    pubsub: PubSubConfig = Field(default_factory=PubSubConfig)
    file: FileConfig = Field(default_factory=FileConfig)

    def for_site(self, site: "SiteConfig") -> "PublisherConfig":
        """Return a per-site publisher config without mutating the global config."""
        cfg = self.model_copy(deep=True)
        if site.kafka_topic:
            cfg.kafka.topic = site.kafka_topic
        if site.pubsub_topic_id:
            cfg.pubsub.topic_id = site.pubsub_topic_id
        if site.file_output_path:
            cfg.file.output_path = site.file_output_path
        return cfg


class SiteConfig(BaseModel):
    id: str
    pi: PIConfig
    tags_file: str
    read: ReadConfig | None = None
    enabled: bool = True
    kafka_topic: str | None = None
    pubsub_topic_id: str | None = None
    file_output_path: str | None = None

    @model_validator(mode="after")
    def sync_site_id_to_pi_config(self):
        self.pi.site = self.id
        return self


class AppConfig(BaseModel):
    # Backward-compatible single-site fields.
    pi: PIConfig = Field(default_factory=PIConfig)
    tags_file: str = "config/tags.txt"

    # Multi-site configuration. When populated, it is the source of truth.
    sites: list[SiteConfig] = Field(default_factory=list)

    read: ReadConfig = Field(default_factory=ReadConfig)
    publisher: PublisherConfig = Field(default_factory=PublisherConfig)

    @model_validator(mode="after")
    def build_default_site_when_needed(self):
        if not self.sites:
            site_id = self.pi.site or "default-site"
            self.sites = [
                SiteConfig(
                    id=site_id,
                    pi=self.pi,
                    tags_file=self.tags_file,
                    read=None,
                )
            ]
        return self

    def enabled_sites(self) -> list[SiteConfig]:
        return [site for site in self.sites if site.enabled]

    def site_by_id(self, site_id: str) -> SiteConfig:
        for site in self.sites:
            if site.id == site_id:
                return site
        raise ValueError(f"Site not found in config: {site_id}")

    def read_for_site(self, site: SiteConfig) -> ReadConfig:
        return site.read or self.read


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as fp:
        raw = yaml.safe_load(fp) or {}
    return AppConfig.model_validate(raw)
