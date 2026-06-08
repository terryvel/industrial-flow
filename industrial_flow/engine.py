from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

from rich.console import Console

from industrial_flow.config import AppConfig, ReadConfig, SiteConfig
from industrial_flow.models.event import TagEvent
from industrial_flow.pi.factory import create_pi_reader
from industrial_flow.pi.point_cache import PointIdCacheStore
from industrial_flow.pi.digital_state_cache import DigitalStateCacheStore
from industrial_flow.publishers.factory import create_publisher
from industrial_flow.utils.batching import chunked
from industrial_flow.utils.tags import load_tags
from industrial_flow.utils.time_windows import build_historical_windows, floor_to_interval, local_now

console = Console()


class SiteEngine:
    """Processes one plant/site and one PI Server configuration."""

    def __init__(self, app_config: AppConfig, site: SiteConfig):
        self.app_config = app_config
        self.site = site
        self.read_config: ReadConfig = app_config.read_for_site(site)
        self.tags = load_tags(site.tags_file)
        self.publisher = create_publisher(app_config.publisher.for_site(site))
        self.point_cache = PointIdCacheStore(self.read_config.point_cache_file)
        self.digital_state_cache = DigitalStateCacheStore(self.read_config.digital_state_cache_file)

    def _read_partition(self, tags: list[str], start: datetime, end: datetime) -> list[TagEvent]:
        reader = create_pi_reader(self.site.pi)
        reader.connect()
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

    def process_window(self, start: datetime, end: datetime) -> int:
        partitions = list(chunked(self.tags, self.read_config.tag_partition_size))
        total_events = 0

        console.print(
            f"[bold]{self.site.id}[/bold] {self.site.pi.server}: "
            f"{start.isoformat()} -> {end.isoformat()} | "
            f"{len(self.tags)} tags | {len(partitions)} partitions | "
            f"{self.read_config.max_workers} workers"
        )

        with ThreadPoolExecutor(max_workers=self.read_config.max_workers) as executor:
            futures = [executor.submit(self._read_partition, partition, start, end) for partition in partitions]
            for future in as_completed(futures):
                events = future.result()
                total_events += len(events)
                for batch in chunked(events, self.read_config.batch_size):
                    self._publish_with_retry(batch)

        self.publisher.flush()
        console.print(f"[green]{self.site.id}: published {total_events} events[/green]")
        return total_events

    def process_historical(self, start: datetime, end: datetime) -> None:
        try:
            for window_start, window_end in build_historical_windows(
                start,
                end,
                self.read_config.window_seconds,
            ):
                self.process_window(window_start, window_end)
        finally:
            self.publisher.close()

    def process_realtime_forever(self, stop_event: threading.Event | None = None) -> None:
        stop_event = stop_event or threading.Event()
        last_end = floor_to_interval(
            local_now() - timedelta(seconds=self.read_config.window_seconds),
            self.read_config.interval_seconds,
        )

        try:
            while not stop_event.is_set():
                now_floor = floor_to_interval(local_now(), self.read_config.interval_seconds)
                next_end = min(last_end + timedelta(seconds=self.read_config.window_seconds), now_floor)
                if next_end > last_end:
                    self.process_window(last_end, next_end)
                    last_end = next_end
                else:
                    time.sleep(self.read_config.interval_seconds)
        finally:
            self.publisher.close()


class MultiSiteEngine:
    """Coordinates multiple plant/site engines."""

    def __init__(self, config: AppConfig):
        self.config = config

    def _build_site_engines(self, site_ids: list[str] | None = None) -> list[SiteEngine]:
        sites = [self.config.site_by_id(site_id) for site_id in site_ids] if site_ids else self.config.enabled_sites()
        return [SiteEngine(self.config, site) for site in sites]

    def process_historical(
        self,
        start: datetime,
        end: datetime,
        site_ids: list[str] | None = None,
        parallel_sites: bool = True,
    ) -> None:
        engines = self._build_site_engines(site_ids)
        if not parallel_sites or len(engines) <= 1:
            for engine in engines:
                engine.process_historical(start, end)
            return

        with ThreadPoolExecutor(max_workers=len(engines)) as executor:
            futures = [executor.submit(engine.process_historical, start, end) for engine in engines]
            for future in as_completed(futures):
                future.result()

    def process_realtime_forever(
        self,
        site_ids: list[str] | None = None,
        parallel_sites: bool = True,
        stop_event: threading.Event | None = None,
    ) -> None:
        engines = self._build_site_engines(site_ids)
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
