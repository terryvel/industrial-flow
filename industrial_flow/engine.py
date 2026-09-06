from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

from rich.console import Console

from industrial_flow.config import AppConfig, ReadConfig, SiteConfig
from industrial_flow.models.event import TagEvent
from industrial_flow.pi.factory import create_pi_reader
from industrial_flow.pi.point_cache import PointIdCacheStore
from industrial_flow.pi.digital_state_cache import DigitalStateCacheStore
from industrial_flow.publishers.bigquery import ParquetGCSBigQueryPublisher
from industrial_flow.publishers.factory import create_publisher
from industrial_flow.utils.batching import chunked
from industrial_flow.utils.tags import load_tags
from industrial_flow.utils.time_windows import build_historical_windows, floor_to_interval, local_now

console = Console()


class SiteEngine:
    """Processes one plant/site and one PI Server configuration."""

    def __init__(self, app_config: AppConfig, site: SiteConfig, publisher_type: str | None = None):
        self.app_config = app_config
        self.site = site
        self.tags = load_tags(site.tags_file)
        self.publisher_type = (publisher_type or app_config.realtime.type).lower()
        self.mode = "historical" if self.publisher_type in {"parquet", "parquet_gcs", "parquet_gcs_bigquery"} else "realtime"
        self.read_config: ReadConfig = app_config.read_for_site(site, self.mode)
        self.publisher = self._build_publisher()
        self.point_cache = PointIdCacheStore(app_config.cache.point_cache_file)
        self.digital_state_cache = DigitalStateCacheStore(app_config.cache.digital_state_cache_file)

    def _build_publisher(self):
        mode = "historical" if self.publisher_type in {"parquet", "parquet_gcs", "parquet_gcs_bigquery"} else "realtime"
        config = self.app_config.publisher_for_mode(mode).model_copy(deep=True)
        config.type = self.publisher_type
        config = config.for_site(self.site)
        return create_publisher(config)

    def _read_partition(self, tags: list[str], start: datetime, end: datetime) -> list[TagEvent]:
        reader = create_pi_reader(self.site.pi)
        reader.connect()
        if not reader.is_connected():
            raise RuntimeError(f"PI Server {self.site.pi.server} reports disconnected state.")
        cached_point_ids = self.point_cache.load(self.site.id, self.site.pi.server)
        reader.preload_point_cache({tag: cached_point_ids[tag] for tag in tags if tag in cached_point_ids})
        reader.preload_digital_state_cache(self.digital_state_cache.load(self.site.id, self.site.pi.server))
        reader.cache_points(tags)
        self.point_cache.merge(self.site.id, self.site.pi.server, reader.export_point_cache())
        events = reader.read_interpolated_values(
            tags=tags,
            start=start,
            end=end,
            interval_seconds=self.read_config.interval_seconds,
        )
        self.digital_state_cache.merge(
            self.site.id,
            self.site.pi.server,
            reader.export_digital_state_cache(),
        )
        return events

    def _publish_with_retry(self, events: list[TagEvent]) -> None:
        attempts = 0
        while True:
            try:
                self.publisher.publish_batch(events)
                return
            except Exception:
                attempts += 1
                if attempts > self.read_config.max_publish_retries:
                    raise
                time.sleep(self.read_config.retry_sleep_seconds * attempts)

    def process_window(self, start: datetime, end: datetime, emit_window_log: bool = True) -> int:
        partitions = list(chunked(self.tags, self.read_config.tag_partition_size))
        total_events = 0
        total_partitions = len(partitions)
        start_ts = time.monotonic()
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        if emit_window_log:
            console.print(
                f"[bold]{timestamp} | {self.site.id} ({self.site.pi.server}): "
                f"{start.isoformat()} -> {end.isoformat()} | "
                f"{len(self.tags)} tags | {total_partitions} partitions | "
                f"{self.read_config.max_workers} workers[/bold]"
            )

        with ThreadPoolExecutor(max_workers=self.read_config.max_workers) as executor:
            futures = {}
            for index, partition in enumerate(partitions, start=1):
                if emit_window_log:
                    console.print(
                        f"[cyan]{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} | "
                        f"{self.site.id} ({self.site.pi.server}): "
                        f"starting partition {index}/{total_partitions} "
                        f"({len(partition)} tags)[/cyan]"
                    )
                futures[executor.submit(self._read_partition, partition, start, end)] = (index, partition)

            completed = 0
            for future in as_completed(futures):
                index, partition = futures[future]
                events = future.result()
                total_events += len(events)
                for batch in chunked(events, self.read_config.batch_size):
                    self._publish_with_retry(batch)
                completed += 1
                elapsed = time.monotonic() - start_ts
                if emit_window_log:
                    console.print(
                        f"[green]{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} | "
                        f"{self.site.id} ({self.site.pi.server}): "
                        f"partition {index}/{total_partitions} done "
                        f"({len(partition)} tags, {len(events)} events, "
                        f"{elapsed:.1f}s elapsed)[/green]"
                    )

        self.publisher.flush()
        if emit_window_log:
            console.print(
                f"[green]{timestamp} | {self.site.id} ({self.site.pi.server}): "
                f"published {total_events} events[/green]"
            )
        return total_events

    def process_historical(self, start: datetime, end: datetime, tags: list[str] | None = None) -> None:
        selected_tags = self.tags if tags is None else tags
        windows = list(build_historical_windows(start, end, self.read_config.window_seconds))
        tag_partitions = list(chunked(selected_tags, self.read_config.tag_partition_size))
        tasks = [
            (partition, window_start, window_end)
            for window_start, window_end in windows
            for partition in tag_partitions
        ]
        completed_tasks = 0
        total_events = 0
        completed_successfully = False
        failed_task: tuple[list[str], datetime, datetime] | None = None
        def _execute_historical_task(p: list[str], ws: datetime, we: datetime) -> list[TagEvent]:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            console.print(
                f"[cyan]{ts} | {self.site.id} ({self.site.pi.server}): "
                f"starting historical read ({len(p)} tags) | {ws.isoformat()} -> {we.isoformat()}[/cyan]"
            )
            return self._read_partition(p, ws, we)

        try:
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            console.print(
                f"[bold]{timestamp} | {self.site.id} ({self.site.pi.server}): historical "
                f"{len(tag_partitions)} tag partitions x {len(windows)} windows = {len(tasks)} tasks | "
                f"{self.read_config.max_workers} workers[/bold]"
            )
            with ThreadPoolExecutor(max_workers=self.read_config.max_workers) as executor:
                futures = {
                    executor.submit(_execute_historical_task, partition, window_start, window_end):
                    (partition, window_start, window_end)
                    for partition, window_start, window_end in tasks
                }
                for future in as_completed(futures):
                    partition, window_start, window_end = futures[future]
                    failed_task = (partition, window_start, window_end)
                    events = future.result()
                    for batch in chunked(events, self.read_config.batch_size):
                        self._publish_with_retry(batch)
                    completed_tasks += 1
                    total_events += len(events)
                    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    console.print(
                        f"[cyan]{timestamp} | {self.site.id} ({self.site.pi.server}): "
                        f"completed historical task {completed_tasks}/{len(tasks)} | "
                        f"{window_start.isoformat()} -> {window_end.isoformat()} | "
                        f"{len(partition)} tags | {len(events)} events[/cyan]"
                    )

            self.publisher.flush()
            completed_successfully = True
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            console.print(
                f"[green]{timestamp} | {self.site.id} ({self.site.pi.server}): "
                f"completed historical processing with {total_events} events[/green]"
            )
        except Exception as exc:
            task_context = "unknown window"
            if failed_task:
                partition, window_start, window_end = failed_task
                task_context = (
                    f"{window_start.isoformat()} -> {window_end.isoformat()} "
                    f"for {len(partition)} tags"
                )
            raise RuntimeError(
                f"Historical task {completed_tasks + 1}/{len(tasks)} failed ({task_context}); "
                f"no BigQuery partition was reconciled: {exc}"
            ) from exc
        finally:
            if completed_successfully:
                self.publisher.close()

    def _process_historical_tag(self, tag: str, start: datetime, end: datetime) -> tuple[int, list[str]]:
        events = self._read_partition([tag], start, end)
        if not events:
            return 0, []

        publisher = self._build_publisher()
        publisher.publish_batch(events)
        if isinstance(publisher, ParquetGCSBigQueryPublisher):
            return len(events), publisher.upload_pending_files()
        publisher.close()
        return len(events), []

    def process_realtime_forever(self, stop_event: threading.Event | None = None) -> None:
        stop_event = stop_event or threading.Event()
        initial_now = local_now().astimezone(timezone.utc)
        last_end = floor_to_interval(
            initial_now - timedelta(seconds=self.read_config.window_seconds),
            self.read_config.interval_seconds,
        )
        last_retry_log_at: datetime | None = None
        last_restore_log_at: datetime | None = None
        in_outage = False
        last_failed_window: tuple[datetime, datetime] | None = None

        try:
            while not stop_event.is_set():
                try:
                    now_floor = floor_to_interval(
                        local_now().astimezone(timezone.utc),
                        self.read_config.interval_seconds,
                    )
                    next_end = min(last_end + timedelta(seconds=self.read_config.window_seconds), now_floor)
                    current_window = (last_end, next_end)

                    if next_end > last_end:
                        if in_outage and last_failed_window == current_window:
                            # Keep retrying the same failed window silently while the PI remains
                            # unreachable; only emit a restoration log after a successful retry.
                            try:
                                self.process_window(last_end, next_end, emit_window_log=False)
                            except Exception:
                                time.sleep(self.read_config.retry_sleep_seconds)
                                continue
                            else:
                                now = datetime.now(timezone.utc)
                                if last_restore_log_at is None or (now - last_restore_log_at).total_seconds() >= 60:
                                    timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
                                    console.print(
                                        f"[green]{timestamp} | {self.site.id} ({self.site.pi.server}): "
                                        f"PI connection restored successfully.[/green]"
                                    )
                                    last_restore_log_at = now
                                in_outage = False
                                last_failed_window = None
                                last_end = next_end
                                continue

                        self.process_window(last_end, next_end)
                        if in_outage:
                            now = datetime.now(timezone.utc)
                            if last_restore_log_at is None or (now - last_restore_log_at).total_seconds() >= 60:
                                timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
                                console.print(
                                    f"[green]{timestamp} | {self.site.id} ({self.site.pi.server}): "
                                    f"PI connection restored successfully.[/green]"
                                )
                                last_restore_log_at = now
                            in_outage = False
                            last_failed_window = None
                        last_end = next_end
                    else:
                        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                        console.print(
                            f"[dim]{timestamp} | {self.site.id} ({self.site.pi.server}): "
                            f"sleeping until next window for {self.read_config.interval_seconds} seconds.[/dim]"
                        )
                        time.sleep(self.read_config.interval_seconds)
                except Exception as exc:
                    retry_seconds = self.read_config.retry_sleep_seconds
                    now = datetime.now(timezone.utc)
                    if next_end > last_end:
                        last_failed_window = (last_end, next_end)
                    if not in_outage:
                        in_outage = True

                    connection_hint = ""
                    if self.site.pi.provider.lower() == "piapi" and "disconnected" in str(exc).lower():
                        connection_hint = " (PI API reports disconnected state)"

                    if last_retry_log_at is None or (now - last_retry_log_at).total_seconds() >= 60:
                        timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
                        console.print(
                            f"[red]{timestamp} | {self.site.id} ({self.site.pi.server}): "
                            f"PI read failed: {exc}{connection_hint}. Trying to reconnect in "
                            f"{retry_seconds} seconds.[/red]"
                        )
                        last_retry_log_at = now
                    time.sleep(retry_seconds)
        finally:
            self.publisher.close()


class MultiSiteEngine:
    """Coordinates multiple plant/site engines."""

    def __init__(self, config: AppConfig):
        self.config = config

    def _build_site_engines(
        self,
        site_ids: list[str] | None = None,
        publisher_type: str | None = None,
    ) -> list[SiteEngine]:
        sites = [self.config.site_by_id(site_id) for site_id in site_ids] if site_ids else self.config.enabled_sites()
        return [SiteEngine(self.config, site, publisher_type=publisher_type) for site in sites]

    def process_historical(
        self,
        start: datetime,
        end: datetime,
        site_ids: list[str] | None = None,
        parallel_sites: bool = True,
        publisher_type: str | None = None,
        tags: list[str] | None = None,
    ) -> None:
        engines = self._build_site_engines(site_ids, publisher_type=publisher_type)
        if not parallel_sites or len(engines) <= 1:
            for engine in engines:
                engine.process_historical(start, end, tags=tags)
            return

        with ThreadPoolExecutor(max_workers=len(engines)) as executor:
            futures = [executor.submit(engine.process_historical, start, end, tags) for engine in engines]
            for future in as_completed(futures):
                future.result()

    def process_realtime_forever(
        self,
        site_ids: list[str] | None = None,
        parallel_sites: bool = True,
        stop_event: threading.Event | None = None,
        publisher_type: str | None = None,
    ) -> None:
        engines = self._build_site_engines(site_ids, publisher_type=publisher_type)
        stop_event = stop_event or threading.Event()
        if not parallel_sites or len(engines) <= 1:
            for engine in engines:
                engine.process_realtime_forever(stop_event)
            return

        with ThreadPoolExecutor(max_workers=len(engines)) as executor:
            futures = [executor.submit(engine.process_realtime_forever, stop_event) for engine in engines]
            for future in as_completed(futures):
                future.result()


# Backward-compatible alias used by older imports/tests.
IndustrialFlowEngine = SiteEngine
