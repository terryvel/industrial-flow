from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from tk.models import ServiceType
from tk.process_manager import ServiceSpec


def get_cache_path() -> Path:
    """Returns absolute path to the local services cache file."""
    cache_dir = Path(".cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "industrial-flow-tk-services.json"


class SavedService:
    """Represents a persisted service configuration."""

    def __init__(self, id_str: str, spec: ServiceSpec) -> None:
        self.id = id_str
        self.spec = spec

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "spec": {
                "service_type": self.spec.service_type.value,
                "config_path": self.spec.config_path,
                "output_type": self.spec.output_type,
                "site": self.spec.site,
                "start": self.spec.start,
                "end": self.spec.end,
                "tags": self.spec.tags,
                "tag": self.spec.tag,
                "timestamp": self.spec.timestamp,
                "value": self.spec.value,
                "istat": self.spec.istat,
                "wait": self.spec.wait,
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SavedService:
        spec_data = data.get("spec", {})
        spec = ServiceSpec(
            service_type=ServiceType(spec_data.get("service_type", "realtime")),
            config_path=spec_data.get("config_path", "config/config.yaml"),
            output_type=spec_data.get("output_type"),
            site=spec_data.get("site"),
            start=spec_data.get("start"),
            end=spec_data.get("end"),
            tags=spec_data.get("tags"),
            tag=spec_data.get("tag"),
            timestamp=spec_data.get("timestamp"),
            value=spec_data.get("value"),
            istat=spec_data.get("istat", 0),
            wait=spec_data.get("wait", True),
        )
        return cls(id_str=data.get("id", "01"), spec=spec)


class ServicesCacheStore:
    """Manages reading and writing saved services to .cache/industrial-flow-tk-services.json."""

    def __init__(self, cache_file: Path | None = None) -> None:
        self.cache_file = cache_file or get_cache_path()

    def load(self) -> list[SavedService]:
        if not self.cache_file.exists():
            return []
        try:
            with self.cache_file.open("r", encoding="utf-8") as fp:
                data = json.load(fp)
                if isinstance(data, list):
                    return [SavedService.from_dict(item) for item in data if isinstance(item, dict)]
        except Exception:
            pass
        return []

    def save(self, services: list[SavedService]) -> None:
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        data = [srv.to_dict() for srv in services]
        with self.cache_file.open("w", encoding="utf-8") as fp:
            json.dump(data, fp, indent=2, ensure_ascii=False)
