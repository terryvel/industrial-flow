from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from industrial_flow.checkpoint import CheckpointStore
from industrial_flow.config import load_config
from industrial_flow.engine import MultiSiteEngine, SiteEngine
from industrial_flow.utils.tags import load_tags
from industrial_flow.utils.time_windows import parse_datetime

app = typer.Typer(help="industrial-flow: PI/PIMS data bridge for Kafka, Pub/Sub and data lakes.")
console = Console()


def _parse_sites(site: str | None) -> list[str] | None:
    if not site or site.lower() in {"all", "*"}:
        return None
    return [part.strip() for part in site.split(",") if part.strip()]


@app.command()
def validate_config(config: Path = typer.Option("config/config.yaml", help="Path to YAML config.")):
    cfg = load_config(config)
    console.print(cfg.model_dump())
    for site in cfg.enabled_sites():
        tags = load_tags(site.tags_file)
        console.print(f"[bold]{site.id}[/bold]: {len(tags)} tags | PI Server: {site.pi.server}")


@app.command()
def historical(
    start: str = typer.Option(..., help="Start datetime. Example: 2026-06-01T00:00:00Z"),
    end: str = typer.Option(..., help="End datetime. Example: 2026-06-01T01:00:00Z"),
    config: Path = typer.Option("config/config.yaml", help="Path to YAML config."),
    site: str | None = typer.Option(None, help="Site id, comma-separated site ids, or all."),
    parallel_sites: bool = typer.Option(True, help="Run different sites in parallel."),
):
    cfg = load_config(config)
    engine = MultiSiteEngine(cfg)
    engine.process_historical(
        parse_datetime(start),
        parse_datetime(end),
        site_ids=_parse_sites(site),
        parallel_sites=parallel_sites,
    )


@app.command()
def realtime(
    config: Path = typer.Option("config/config.yaml", help="Path to YAML config."),
    site: str | None = typer.Option(None, help="Site id, comma-separated site ids, or all."),
    parallel_sites: bool = typer.Option(True, help="Run different sites in parallel."),
):
    cfg = load_config(config)
    engine = MultiSiteEngine(cfg)
    engine.process_realtime_forever(site_ids=_parse_sites(site), parallel_sites=parallel_sites)


@app.command()
def once(
    config: Path = typer.Option("config/config.yaml", help="Path to YAML config."),
    site: str | None = typer.Option(None, help="Site id, comma-separated site ids, or all."),
):
    cfg = load_config(config)
    selected_sites = _parse_sites(site)
    sites = [cfg.site_by_id(site_id) for site_id in selected_sites] if selected_sites else cfg.enabled_sites()

    for site_cfg in sites:
        read_cfg = cfg.read_for_site(site_cfg)
        checkpoint = CheckpointStore(read_cfg.checkpoint_file)
        last = checkpoint.load(site_cfg.id)
        if last is None:
            last = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        end = last + timedelta(seconds=read_cfg.window_seconds)
        engine = SiteEngine(cfg, site_cfg)
        engine.process_historical(last, end)
        checkpoint.save(end, site_cfg.id)


if __name__ == "__main__":
    app()
