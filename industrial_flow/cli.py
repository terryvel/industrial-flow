from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from industrial_flow.config import load_config
from industrial_flow.engine import MultiSiteEngine, SiteEngine
from industrial_flow.utils.tags import load_tags
from industrial_flow.utils.time_windows import parse_datetime
from industrial_flow.writer import PIArchiveWriter, PubSubPIArchiveWriter, parse_write_request

app = typer.Typer(help="industrial-flow: PI/PIMS data bridge for Kafka, Pub/Sub and data lakes.")
console = Console()

HISTORICAL_PIPELINES_MESSAGE = (
    "Historical mode always exports data as Parquet.\n\n"
    "Supported values:\n"
    "- parquet = PI → Parquet\n"
    "- parquet_gcs = PI → Parquet → GCS\n"
    "- parquet_gcs_bigquery = PI → Parquet → GCS → BigQuery Load Job\n\n"
    "Use realtime for: console, file, kafka, pubsub, bigquery."
)


def _raise_cli_error(message: str, *, exit_code: int = 1) -> None:
    typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(code=exit_code)


def _parse_sites(site: str | None) -> list[str] | None:
    if not site or site.lower() in {"all", "*"}:
        return None
    return [part.strip() for part in site.split(",") if part.strip()]


def _parse_tags(tags: str | None) -> list[str] | None:
    if tags is None:
        return None
    parsed = [tag.strip().upper() for tag in tags.split(",") if tag.strip()]
    if not parsed:
        raise ValueError("--tags must contain at least one comma-separated tag.")
    return list(dict.fromkeys(parsed))


def _validate_mode_publisher(cfg, mode: str, publisher: str | None) -> str:
    selected_cfg = cfg.publisher_for_mode(mode).model_copy(deep=True)
    chosen = (publisher or selected_cfg.type).lower()
    selected_cfg.type = chosen

    if mode == "historical":
        allowed = {"parquet", "parquet_gcs", "parquet_gcs_bigquery"}
        if chosen not in allowed:
            raise ValueError(HISTORICAL_PIPELINES_MESSAGE)
        if not selected_cfg.is_configured(chosen):
            raise ValueError(
                "Historical mode requires a Parquet export configuration. "
                "Configure historical.type as 'parquet', 'parquet_gcs' or 'parquet_gcs_bigquery'.\n\n"
                + HISTORICAL_PIPELINES_MESSAGE
            )
        return chosen

    allowed = {"console", "file", "kafka", "pubsub", "bigquery"}
    if chosen in {"parquet", "parquet_gcs_bigquery"}:
        raise ValueError(
            "Realtime supports: console, file, kafka, pubsub, bigquery.\n\n"
            + HISTORICAL_PIPELINES_MESSAGE
        )
    if chosen not in allowed:
        raise ValueError(f"Unsupported realtime publisher: {chosen}")
    if not selected_cfg.is_configured(chosen):
        raise ValueError(f"Realtime publisher '{chosen}' is not configured.")
    return chosen


@app.command()
def validate_config(config: Path = typer.Option("config/config.yaml", help="Path to YAML config.")):
    cfg = load_config(config)
    console.print(cfg.model_dump(exclude_defaults=True, exclude_none=True))
    for site in cfg.enabled_sites():
        tags = load_tags(site.tags_file)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        console.print(
            f"[bold]{timestamp} | {site.id} ({site.pi.server}): "
            f"{len(tags)} tags | PI Server: {site.pi.server}[/bold]"
        )


@app.command()
def historical(
    start: str = typer.Option(..., help="Start datetime. Example: 2026-06-01T00:00:00Z"),
    end: str = typer.Option(..., help="End datetime. Example: 2026-06-01T01:00:00Z"),
    config: Path = typer.Option("config/config.yaml", help="Path to YAML config."),
    site: str | None = typer.Option(None, help="Site id, comma-separated site ids, or all."),
    tags: str | None = typer.Option(None, help="Comma-separated PI tags; overrides the configured tags file for this run."),
    parallel_sites: bool = typer.Option(True, help="Run different sites in parallel."),
    output_type: str | None = typer.Option(
        None,
        "--type",
        help=(
            "Historical output type. Supported values: "
            "parquet=PI -> Parquet; "
            "parquet_gcs=PI -> Parquet -> GCS; "
            "parquet_gcs_bigquery=PI -> Parquet -> GCS -> BigQuery Load Job. "
            "Realtime values: console, file, kafka, pubsub, bigquery."
        ),
    ),
):
    try:
        cfg = load_config(config)
        publisher_type = _validate_mode_publisher(cfg, "historical", output_type)
        engine = MultiSiteEngine(cfg)
        engine.process_historical(
            parse_datetime(start),
            parse_datetime(end),
            site_ids=_parse_sites(site),
            parallel_sites=parallel_sites,
            publisher_type=publisher_type,
            tags=_parse_tags(tags),
        )
    except (RuntimeError, ValueError, ImportError) as exc:
        _raise_cli_error(str(exc))


@app.command()
def realtime(
    config: Path = typer.Option("config/config.yaml", help="Path to YAML config."),
    site: str | None = typer.Option(None, help="Site id, comma-separated site ids, or all."),
    parallel_sites: bool = typer.Option(True, help="Run different sites in parallel."),
    output_type: str | None = typer.Option(
        None,
        "--type",
        help=(
            "Realtime output type. Supported values: console, file, kafka, pubsub, bigquery. "
            "Historical pipeline uses parquet, parquet_gcs or parquet_gcs_bigquery."
        ),
    ),
):
    try:
        cfg = load_config(config)
        publisher_type = _validate_mode_publisher(cfg, "realtime", output_type)
        engine = MultiSiteEngine(cfg)
        engine.process_realtime_forever(
            site_ids=_parse_sites(site),
            parallel_sites=parallel_sites,
            publisher_type=publisher_type,
        )
    except (RuntimeError, ValueError, ImportError) as exc:
        _raise_cli_error(str(exc))


@app.command()
def writer(
    config: Path = typer.Option("config/config.yaml", help="Path to YAML config."),
    site: str | None = typer.Option(None, help="Target site id for console writes."),
    tag: str | None = typer.Option(None, help="PI tag for console writes."),
    timestamp: str | None = typer.Option(None, help="Timestamp in ISO 8601 format for console writes."),
    value: float | None = typer.Option(None, help="Numeric value in engineering units for console writes."),
    istat: int = typer.Option(0, help="PI integer status for console writes."),
    wait: bool = typer.Option(True, help="Wait for PI archive write confirmation, up to 30 seconds."),
):
    try:
        cfg = load_config(config)
        if cfg.writer.type == "pubsub":
            PubSubPIArchiveWriter(cfg).run()
            return
        if site is None or tag is None or timestamp is None or value is None:
            raise ValueError("Console writer requires --site, --tag, --timestamp, and --value.")
        request = parse_write_request(
            {"site": site, "tag": tag, "timestamp": timestamp, "value": value, "istat": istat, "wait": wait}
        )
        PIArchiveWriter(cfg).write(request)
        console.print(
            f"[green]PI archive value written: {request.site} {request.tag} "
            f"{request.timestamp.isoformat()} = {request.value}[/green]"
        )
    except (RuntimeError, ValueError, ImportError) as exc:
        _raise_cli_error(str(exc))


@app.command(name="gui")
def gui(
    config: Path = typer.Option("config/config.yaml", help="Path to YAML config."),
):
    """Launch the Tkinter GUI for service management and configuration editing."""
    try:
        from tk.app import IndustrialFlowTkApp
        tk_app = IndustrialFlowTkApp(config_path=config)
        tk_app.root.mainloop()
    except (RuntimeError, ValueError, ImportError) as exc:
        _raise_cli_error(str(exc))


if __name__ == "__main__":
    app()
