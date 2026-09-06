from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Iterable
import shutil

from industrial_flow.config import AppConfig, load_config

try:
    from ruamel.yaml import YAML
    from ruamel.yaml.comments import CommentedMap, CommentedSeq
    _HAS_RUAMEL = True
except ImportError:
    import yaml
    _HAS_RUAMEL = False
    CommentedMap = dict
    CommentedSeq = list


DEFAULT_SITE = {
    "id": "site1",
    "enabled": True,
    "pi": {
        "provider": "piapi",
        "server": "PI-SERVER-01",
        "pi_timezone": "America/Sao_Paulo",
        "username": "",
        "password": "",
        "read_mode": "interpolated",
    },
    "tags_file": "config/tags.txt",
}


class ConfigStore:
    """Manages loading, validating, editing, and saving config/config.yaml for the GUI."""

    def __init__(self, path: str | Path = "config/config.yaml"):
        self.path = Path(path)
        self.data: dict[str, Any] = {}
        self.app_config: AppConfig | None = None
        self.load()

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            raise FileNotFoundError(f"Configuration file not found: {self.path}")

        if _HAS_RUAMEL:
            yaml_obj = YAML()
            yaml_obj.preserve_quotes = True
            with self.path.open("r", encoding="utf-8") as fp:
                loaded = yaml_obj.load(fp) or {}
                self.data = dict(loaded) if not isinstance(loaded, dict) else loaded
        else:
            import yaml
            with self.path.open("r", encoding="utf-8") as fp:
                self.data = yaml.safe_load(fp) or {}

        # Validate against Pydantic schema
        self.app_config = AppConfig.model_validate(self.data)
        return self.data

    def validate_in_memory(self, candidate_data: dict[str, Any] | None = None) -> AppConfig:
        data = candidate_data if candidate_data is not None else self.data
        return AppConfig.model_validate(data)

    def validate_file(self) -> AppConfig:
        return load_config(self.path)

    def save(self) -> None:
        # Validate BEFORE writing
        validated = self.validate_in_memory()
        self.app_config = validated

        self.path.parent.mkdir(parents=True, exist_ok=True)
        backup_path = self.path.with_suffix(self.path.suffix + ".bak")
        if self.path.exists():
            try:
                shutil.copy2(self.path, backup_path)
            except Exception:
                pass

        if _HAS_RUAMEL:
            yaml_obj = YAML()
            yaml_obj.preserve_quotes = True
            yaml_obj.indent(mapping=2, sequence=4, offset=2)
            with self.path.open("w", encoding="utf-8") as fp:
                yaml_obj.dump(self.data, fp)
        else:
            import yaml
            with self.path.open("w", encoding="utf-8") as fp:
                yaml.safe_dump(self.data, fp, sort_keys=False)

    def get_sites(self) -> list[dict[str, Any]]:
        return self.data.get("sites", [])

    def add_site(self, site_dict: dict[str, Any] | None = None) -> int:
        if "sites" not in self.data or not isinstance(self.data["sites"], list):
            self.data["sites"] = []
        new_site = copy.deepcopy(site_dict) if site_dict is not None else copy.deepcopy(DEFAULT_SITE)
        self.data["sites"].append(new_site)
        return len(self.data["sites"]) - 1

    def update_site(self, index: int, site_dict: dict[str, Any]) -> None:
        sites = self.get_sites()
        if 0 <= index < len(sites):
            sites[index] = site_dict

    def delete_site(self, index: int) -> None:
        sites = self.get_sites()
        if 0 <= index < len(sites):
            sites.pop(index)

    def get_site(self, index: int) -> dict[str, Any]:
        sites = self.get_sites()
        if 0 <= index < len(sites):
            return sites[index]
        return {}

    def get_value_by_path(self, key_path: str, default: Any = None) -> Any:
        keys = key_path.split(".")
        current = self.data
        for k in keys:
            if isinstance(current, dict) and k in current:
                current = current[k]
            else:
                return default
        return current

    def set_value_by_path(self, key_path: str, value: Any) -> None:
        keys = key_path.split(".")
        current = self.data
        for k in keys[:-1]:
            if k not in current or not isinstance(current[k], dict):
                current[k] = {}
            current = current[k]
        current[keys[-1]] = value
        return value

    @classmethod
    def set_path(cls, root: CommentedMap, path: Iterable[str], value: Any) -> None:
        parts = list(path)
        current = root
        for part in parts[:-1]:
            current = cls.ensure_map(current, part)
        current[parts[-1]] = value

    @classmethod
    def _to_commented(cls, value: Any) -> Any:
        if isinstance(value, dict):
            mapped = CommentedMap()
            for key, child in value.items():
                mapped[key] = cls._to_commented(child)
            return mapped
        if isinstance(value, list):
            return CommentedSeq(cls._to_commented(child) for child in value)
        return value
