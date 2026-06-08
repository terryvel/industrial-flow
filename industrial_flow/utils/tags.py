from __future__ import annotations

from pathlib import Path


def load_tags(path: str | Path) -> list[str]:
    tags_path = Path(path)
    with tags_path.open("r", encoding="utf-8") as fp:
        tags = [line.strip() for line in fp if line.strip() and not line.strip().startswith("#")]
    return list(dict.fromkeys(tags))
