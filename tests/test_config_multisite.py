from datetime import datetime, timezone

import typer
from typer.testing import CliRunner

from industrial_flow.cli import _parse_tags, _validate_mode_publisher, app
from industrial_flow.config import (
    AppConfig,
    BigQueryConfig,
    GCSConfig,
    PIConfig,
    ParquetConfig,
    PublisherConfig,
    ReadConfig,
    SiteConfig,
    load_config,
)
from industrial_flow.engine import SiteEngine
from industrial_flow.utils.tags import load_tags
from industrial_flow.utils.time_windows import parse_datetime
from industrial_flow.models.event import TagEvent
from industrial_flow.pi.piapi import PIAPIReader
from industrial_flow.publishers.bigquery import ParquetGCSBigQueryPublisher, ParquetGCSPublisher, industrial_partition_date
from industrial_flow.publishers.factory import create_publisher


runner = CliRunner()


def test_load_tags_normalizes_to_uppercase(tmp_path):
    tags_file = tmp_path / "tags.txt"
    tags_file.write_text("sinusoid\nSINUSOID\nFlowRate\nflowrate\n# comment\n", encoding="utf-8")

    assert load_tags(tags_file) == ["SINUSOID", "FLOWRATE"]


def test_historical_cli_tags_are_uppercase_and_deduplicated():
    assert _parse_tags("sinusoid, FLOWRATE,Sinusoid") == ["SINUSOID", "FLOWRATE"]


def test_sites_are_required():
    import pytest

    with pytest.raises(ValueError):
        AppConfig(sites=[])


def test_site_config_has_no_legacy_publisher_fields():
    assert "file_output_path" not in SiteConfig.model_fields
    assert "kafka_topic" not in SiteConfig.model_fields
    assert "pubsub_topic_id" not in SiteConfig.model_fields


def test_validate_config_omits_default_top_level_pi_block():
    result = runner.invoke(app, ["validate-config", "--config", "config/config.yaml"])
    assert result.exit_code == 0, result.stdout
    assert "'provider': 'simulator'" not in result.stdout
    assert "'server': 'PI-SERVER-01'" not in result.stdout
    assert "'site': 'default-site'" not in result.stdout


def test_pi_config_uses_only_password_field(monkeypatch):
    monkeypatch.setenv("PI_PASSWORD", "secret-from-env")
    config = PIConfig(provider="piapi", server="PI-SERVER-1", username="user")
    assert config.password == "secret-from-env"
    assert not hasattr(config, "password_env")


def test_event_idempotency_key_uses_md5_site_tag_timestamp():
    event = TagEvent(
        source="piapi",
        server="PI-SERVER-01",
        site="site1",
        tag="sinusoid",
        timestamp=datetime(2026, 8, 26, 23, 50, 0, tzinfo=timezone.utc),
        value=42.0,
    )
    assert event.idempotency_key() == "5e281c2f64e9ddfd67af8bc6b29a399c"
    assert event.to_dict()["event_id"] == event.idempotency_key()


def test_event_idempotency_key_normalizes_equivalent_timestamps_to_utc():
    utc_event = TagEvent(
        source="piapi",
        server="PI-SERVER-01",
        site="casa",
        tag="SINUSOID",
        timestamp=datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc),
        value=1.0,
    )
    local_event = TagEvent(
        source="piapi",
        server="PI-SERVER-01",
        site="casa",
        tag="SINUSOID",
        timestamp=datetime.fromisoformat("2026-08-29T21:00:00-03:00"),
        value=1.0,
    )

    assert utc_event.idempotency_key() == local_event.idempotency_key()


def test_piapi_reader_reports_connection_status(monkeypatch):
    config = PIConfig(provider="piapi", server="PI-SERVER-1", username="user", password="secret")
    reader = PIAPIReader(config)

    class FakePIAPI:
        @staticmethod
        def piut_isconnected():
            return 1

    reader.piapi = FakePIAPI()
    assert reader.is_connected() is True

    class FakeDisconnectedPIAPI:
        @staticmethod
        def piut_isconnected():
            return 0

    reader.piapi = FakeDisconnectedPIAPI()
    assert reader.is_connected() is False


def test_piapi_reader_rejects_pending_commands_when_disconnected():
    config = PIConfig(provider="piapi", server="PI-SERVER-1", username="user", password="secret")
    reader = PIAPIReader(config)

    class FakeDisconnectedPIAPI:
        @staticmethod
        def piut_isconnected():
            return 0

    reader.piapi = FakeDisconnectedPIAPI()

    try:
        reader.cache_points(["tag1"])
        raise AssertionError("Expected PIAPIError when PI is disconnected")
    except RuntimeError as exc:
        assert "disconnected state" in str(exc).lower()


def test_process_realtime_forever_retry_log_mentions_disconnected_status(monkeypatch):
    site = SiteConfig(
        id="site1",
        pi=PIConfig(provider="piapi", server="PI-SERVER-1"),
        tags_file="config/tags.txt",
    )
    cfg = AppConfig(sites=[site])
    engine = SiteEngine(cfg, site, publisher_type="console")
    stop_event = __import__("threading").Event()
    printed = []

    def fake_process_window(start, end):
        raise RuntimeError("PI Server PI-SERVER-1 reports disconnected state.")

    def fake_sleep(seconds):
        stop_event.set()

    monkeypatch.setattr(engine, "process_window", fake_process_window)
    monkeypatch.setattr("industrial_flow.engine.time.sleep", fake_sleep)
    monkeypatch.setattr("industrial_flow.engine.console.print", lambda *args, **kwargs: printed.append(" ".join(str(arg) for arg in args)))

    engine.process_realtime_forever(stop_event)
    assert any("PI API reports disconnected state" in msg for msg in printed)


def test_process_realtime_forever_retries_after_pi_failure(monkeypatch):
    site = SiteConfig(
        id="site1",
        pi=PIConfig(provider="simulator", server="PI-SERVER-1"),
        tags_file="config/tags.txt",
    )
    cfg = AppConfig(sites=[site])
    engine = SiteEngine(cfg, site, publisher_type="console")
    calls = {"count": 0}
    stop_event = __import__("threading").Event()

    def fake_process_window(start, end):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("PI unavailable")
        stop_event.set()
        return 1

    monkeypatch.setattr(engine, "process_window", fake_process_window)
    monkeypatch.setattr("industrial_flow.engine.time.sleep", lambda seconds: None)

    engine.process_realtime_forever(stop_event)
    assert calls["count"] >= 2


def test_process_realtime_forever_uses_retry_sleep_seconds_on_pi_failure(monkeypatch):
    site = SiteConfig(
        id="site1",
        pi=PIConfig(provider="simulator", server="PI-SERVER-1"),
        tags_file="config/tags.txt",
        read={
            "interval_seconds": 60,
            "retry_sleep_seconds": 2,
        },
    )
    cfg = AppConfig(sites=[site])
    engine = SiteEngine(cfg, site, publisher_type="console")
    stop_event = __import__("threading").Event()
    sleep_calls = []

    def fake_process_window(start, end):
        raise RuntimeError("PI unavailable")

    def fake_sleep(seconds):
        sleep_calls.append(seconds)
        stop_event.set()

    monkeypatch.setattr(engine, "process_window", fake_process_window)
    monkeypatch.setattr("industrial_flow.engine.time.sleep", fake_sleep)

    engine.process_realtime_forever(stop_event)
    assert sleep_calls == [2.0]


def test_process_realtime_forever_logs_retry_error_only_once_per_minute(monkeypatch):
    site = SiteConfig(
        id="site1",
        pi=PIConfig(provider="simulator", server="PI-SERVER-1"),
        tags_file="config/tags.txt",
        read={
            "interval_seconds": 60,
            "retry_sleep_seconds": 2,
        },
    )
    cfg = AppConfig(sites=[site])
    engine = SiteEngine(cfg, site, publisher_type="console")
    stop_event = __import__("threading").Event()
    printed = []
    attempts = {"count": 0}
    clock = {"now": datetime(2026, 8, 28, 20, 0, tzinfo=timezone.utc)}

    def fake_process_window(start, end):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("PI unavailable")
        if attempts["count"] == 2:
            clock["now"] = clock["now"] + __import__("datetime").timedelta(minutes=2)
            stop_event.set()
        return 1

    monkeypatch.setattr("industrial_flow.engine.time.sleep", lambda seconds: None)
    monkeypatch.setattr("industrial_flow.engine.local_now", lambda: clock["now"])
    monkeypatch.setattr("industrial_flow.engine.console.print", lambda *args, **kwargs: printed.append(" ".join(str(arg) for arg in args)))
    monkeypatch.setattr(engine, "process_window", fake_process_window)

    engine.process_realtime_forever(stop_event)
    assert sum("PI read failed" in msg for msg in printed) == 1


def test_process_realtime_forever_logs_restore_only_once_after_outage(monkeypatch):
    site = SiteConfig(
        id="site1",
        pi=PIConfig(provider="simulator", server="PI-SERVER-1"),
        tags_file="config/tags.txt",
        read={
            "interval_seconds": 60,
            "retry_sleep_seconds": 2,
        },
    )
    cfg = AppConfig(sites=[site])
    engine = SiteEngine(cfg, site, publisher_type="console")
    stop_event = __import__("threading").Event()
    printed = []
    attempts = {"count": 0}

    def fake_process_window(start, end):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("PI unavailable")
        stop_event.set()
        return 1

    monkeypatch.setattr(engine, "process_window", fake_process_window)
    monkeypatch.setattr("industrial_flow.engine.time.sleep", lambda seconds: None)
    monkeypatch.setattr("industrial_flow.engine.console.print", lambda *args, **kwargs: printed.append(" ".join(str(arg) for arg in args)))

    engine.process_realtime_forever(stop_event)
    assert sum("PI connection restored successfully" in msg for msg in printed) == 1


def test_process_realtime_forever_logs_restore_only_after_successful_window(monkeypatch):
    site = SiteConfig(
        id="site1",
        pi=PIConfig(provider="simulator", server="PI-SERVER-1"),
        tags_file="config/tags.txt",
        read={
            "interval_seconds": 60,
            "retry_sleep_seconds": 2,
        },
    )
    cfg = AppConfig(sites=[site])
    engine = SiteEngine(cfg, site, publisher_type="console")
    stop_event = __import__("threading").Event()
    printed = []
    attempts = {"count": 0}

    def fake_process_window(start, end):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("PI unavailable")
        stop_event.set()
        return 1

    monkeypatch.setattr(engine, "process_window", fake_process_window)
    monkeypatch.setattr("industrial_flow.engine.time.sleep", lambda seconds: None)
    monkeypatch.setattr("industrial_flow.engine.console.print", lambda *args, **kwargs: printed.append(" ".join(str(arg) for arg in args)))

    engine.process_realtime_forever(stop_event)
    assert printed[-1].endswith("PI connection restored successfully.")


def test_process_realtime_forever_retries_same_failed_window_silently(monkeypatch):
    site = SiteConfig(
        id="site1",
        pi=PIConfig(provider="simulator", server="PI-SERVER-1"),
        tags_file="config/tags.txt",
        read={
            "interval_seconds": 60,
            "retry_sleep_seconds": 2,
            "window_seconds": 120,
        },
    )
    cfg = AppConfig(sites=[site])
    engine = SiteEngine(cfg, site, publisher_type="console")
    stop_event = __import__("threading").Event()
    calls = {"count": 0}
    fixed_now = datetime(2026, 8, 28, 20, 46, 0, tzinfo=timezone.utc)

    monkeypatch.setattr("industrial_flow.engine.local_now", lambda: fixed_now)
    monkeypatch.setattr("industrial_flow.engine.floor_to_interval", lambda dt, seconds: fixed_now.replace(second=0, microsecond=0))

    def fake_process_window(start, end):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("PI unavailable")
        stop_event.set()
        return 1

    monkeypatch.setattr(engine, "process_window", fake_process_window)
    monkeypatch.setattr("industrial_flow.engine.time.sleep", lambda seconds: None)

    engine.process_realtime_forever(stop_event)
    assert calls["count"] == 2


def test_realtime_windows_are_normalized_to_utc_before_pi_read(monkeypatch):
    site = SiteConfig(
        id="site1",
        pi=PIConfig(provider="simulator", server="PI-SERVER-1"),
        tags_file="config/tags.txt",
        read={"interval_seconds": 60, "window_seconds": 120},
    )
    cfg = AppConfig(sites=[site])
    engine = SiteEngine(cfg, site, publisher_type="console")
    stop_event = __import__("threading").Event()
    calls = []
    sao_paulo_now = datetime.fromisoformat("2026-08-30T15:52:00-03:00")

    def fake_process_window(start, end, emit_window_log=True):
        calls.append((start, end))
        stop_event.set()
        return 1

    monkeypatch.setattr("industrial_flow.engine.local_now", lambda: sao_paulo_now)
    monkeypatch.setattr(engine, "process_window", fake_process_window)

    engine.process_realtime_forever(stop_event)

    assert len(calls) == 1
    start, end = calls[0]
    assert start.tzinfo is timezone.utc
    assert end.tzinfo is timezone.utc
    assert start.isoformat() == "2026-08-30T18:50:00+00:00"
    assert end.isoformat() == "2026-08-30T18:52:00+00:00"


def test_historical_process_uses_requested_start_and_end_for_each_partition(monkeypatch):
    site = SiteConfig(
        id="site1",
        pi=PIConfig(provider="simulator", server="PI-SERVER-1"),
        tags_file="config/tags.txt",
    )
    cfg = AppConfig(sites=[site], historical=PublisherConfig(read=ReadConfig(window_seconds=7200)))
    engine = SiteEngine(cfg, site, publisher_type="parquet")
    engine.tags = ["TAG_A"]
    calls = []

    def fake_read_partition(tags, window_start, window_end):
        calls.append((tags, window_start, window_end))
        return []

    monkeypatch.setattr(engine, "_read_partition", fake_read_partition)

    start = datetime(2026, 8, 26, 10, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    engine.process_historical(start, end)

    assert calls == [(["TAG_A"], start, end)]


def test_historical_process_builds_tag_partition_by_time_window_tasks(monkeypatch):
    site = SiteConfig(
        id="site1",
        pi=PIConfig(provider="simulator", server="PI-SERVER-1"),
        tags_file="config/tags.txt",
        read={"tag_partition_size": 1, "max_workers": 2, "window_seconds": 86400},
    )
    cfg = AppConfig(sites=[site])
    engine = SiteEngine(cfg, site, publisher_type="parquet")
    engine.tags = ["TAG_A", "TAG_B"]
    calls = []

    def fake_read_partition(tags, window_start, window_end):
        calls.append((tags, window_start, window_end))
        return []

    monkeypatch.setattr(engine, "_read_partition", fake_read_partition)

    start = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 28, 6, 0, tzinfo=timezone.utc)
    engine.process_historical(start, end)

    assert sorted(calls) == sorted([
        (["TAG_A"], start, datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)),
        (["TAG_B"], start, datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)),
        (["TAG_A"], datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc), end),
        (["TAG_B"], datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc), end),
    ])


def test_mode_read_configs_are_independent():
    site = SiteConfig(id="site1", pi=PIConfig(), tags_file="config/tags.txt")
    cfg = AppConfig(
        sites=[site],
        realtime=PublisherConfig(read=ReadConfig(window_seconds=60, tag_partition_size=500, max_workers=4, batch_size=1000)),
        historical=PublisherConfig(read=ReadConfig(window_seconds=604800, tag_partition_size=50, max_workers=8, batch_size=10000)),
    )

    assert cfg.read_for_site(site, "realtime").window_seconds == 60
    assert cfg.read_for_site(site, "realtime").tag_partition_size == 500
    assert cfg.read_for_site(site, "historical").window_seconds == 604800
    assert cfg.read_for_site(site, "historical").max_workers == 8


def test_historical_one_tag_two_years_creates_seven_day_windows(monkeypatch):
    site = SiteConfig(id="site1", pi=PIConfig(), tags_file="config/tags.txt")
    cfg = AppConfig(sites=[site], historical=PublisherConfig(read=ReadConfig(window_seconds=604800, tag_partition_size=500, max_workers=8)))
    engine = SiteEngine(cfg, site, publisher_type="parquet")
    engine.tags = ["TAG_A"]
    calls = []
    monkeypatch.setattr(engine, "_read_partition", lambda tags, start, end: calls.append((tags, start, end)) or [])

    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 1, tzinfo=timezone.utc)
    engine.process_historical(start, end)

    assert len(calls) == 105
    assert calls[0] == (["TAG_A"], start, datetime(2024, 1, 8, tzinfo=timezone.utc))
    calls.sort(key=lambda call: call[1])
    assert calls[-1][2] == end
    assert all(calls[index][2] == calls[index + 1][1] for index in range(len(calls) - 1))


def test_historical_limits_pi_read_concurrency(monkeypatch):
    site = SiteConfig(id="site1", pi=PIConfig(), tags_file="config/tags.txt")
    cfg = AppConfig(sites=[site], historical=PublisherConfig(read=ReadConfig(window_seconds=60, tag_partition_size=1, max_workers=2)))
    engine = SiteEngine(cfg, site, publisher_type="parquet")
    engine.tags = ["TAG_A", "TAG_B"]
    gate = __import__("threading").Event()
    lock = __import__("threading").Lock()
    state = {"active": 0, "maximum": 0}

    def fake_read_partition(tags, start, end):
        with lock:
            state["active"] += 1
            state["maximum"] = max(state["maximum"], state["active"])
            if state["active"] == 2:
                gate.set()
        gate.wait(timeout=1)
        with lock:
            state["active"] -= 1
        return []

    monkeypatch.setattr(engine, "_read_partition", fake_read_partition)
    engine.process_historical(datetime(2026, 8, 26, tzinfo=timezone.utc), datetime(2026, 8, 26, 0, 2, tzinfo=timezone.utc))

    assert state["maximum"] == 2


def test_historical_read_failure_does_not_flush_partial_results(monkeypatch):
    site = SiteConfig(id="site1", pi=PIConfig(), tags_file="config/tags.txt")
    cfg = AppConfig(sites=[site], historical=PublisherConfig(read=ReadConfig(window_seconds=60, tag_partition_size=1)))
    engine = SiteEngine(cfg, site, publisher_type="parquet")
    engine.tags = ["TAG_A", "TAG_B"]
    flushed = []
    monkeypatch.setattr(engine.publisher, "flush", lambda: flushed.append(True))
    monkeypatch.setattr(engine, "_read_partition", lambda tags, start, end: (_ for _ in ()).throw(RuntimeError("PI unavailable")) if tags == ["TAG_B"] else [])

    try:
        engine.process_historical(datetime(2026, 8, 26, tzinfo=timezone.utc), datetime(2026, 8, 26, 0, 1, tzinfo=timezone.utc))
        raise AssertionError("Expected historical failure")
    except RuntimeError as exc:
        assert "2026-08-26T00:00:00+00:00" in str(exc)
    assert not flushed


def test_historical_logs_tag_progress_for_parquet_and_gcs(monkeypatch):
    site = SiteConfig(
        id="site1",
        pi=PIConfig(provider="simulator", server="PI-SERVER-1"),
        tags_file="config/tags.txt",
    )
    cfg = AppConfig(sites=[site], historical=PublisherConfig(read=ReadConfig(window_seconds=86400)))
    engine = SiteEngine(cfg, site, publisher_type="parquet_gcs")
    engine.tags = ["TAG_A", "TAG_B"]
    printed = []

    monkeypatch.setattr(engine, "_read_partition", lambda tags, start, end: [])
    monkeypatch.setattr(engine.publisher, "flush", lambda: None)
    monkeypatch.setattr("industrial_flow.engine.console.print", lambda *args, **kwargs: printed.append(" ".join(str(arg) for arg in args)))

    engine.process_historical(
        datetime(2026, 8, 26, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 27, 0, 0, tzinfo=timezone.utc),
    )

    assert any("1 tag partitions x 1 windows = 1 tasks" in message for message in printed)
    assert any("completed historical task 1/1" in message for message in printed)


def test_historical_merge_sql_filters_partition_columns_in_join():
    sql = ParquetGCSBigQueryPublisher._build_partition_replacement_sql(
        None,
        "demo-project.industrial.pi_data",
        "demo-project.industrial.pi_data__staging_20260826",
        partition_date="2026-08-26",
    )

    assert "ON target.event_id = staging.event_id" in sql
    assert "AND target.timestamp >= TIMESTAMP('2026-08-26T00:00:00+00:00')" in sql
    assert "AND target.timestamp < TIMESTAMP('2026-08-26T23:59:59.999999+00:00')" in sql
    assert "AND staging.timestamp >= TIMESTAMP('2026-08-26T00:00:00+00:00')" in sql
    assert "AND staging.timestamp < TIMESTAMP('2026-08-26T23:59:59.999999+00:00')" in sql


def test_site_engine_uses_mode_specific_bigquery_config():
    site = SiteConfig(
        id="site2",
        pi=PIConfig(provider="simulator", server="PI-SERVER-2"),
        tags_file="config/tags.txt",
    )
    cfg = AppConfig(
        sites=[site],
        realtime=PublisherConfig(
            type="bigquery",
            bigquery=BigQueryConfig(
                project_id="demo-project",
                dataset="industrial",
                table="pi_data",
                service_account_file="config/service-account.json",
            ),
        ),
    )
    engine = SiteEngine(cfg, site, publisher_type="bigquery")
    assert engine.publisher.config.service_account_file == "config/service-account.json"


def test_site_engine_uses_historical_config_for_parquet_gcs():
    site = SiteConfig(
        id="site2",
        pi=PIConfig(provider="simulator", server="PI-SERVER-2"),
        tags_file="config/tags.txt",
    )
    cfg = AppConfig(
        sites=[site],
        historical=PublisherConfig(
            type="parquet_gcs",
            parquet=ParquetConfig(output_dir="output/parquet"),
            gcs=GCSConfig(bucket="raw-industrial"),
        ),
    )
    engine = SiteEngine(cfg, site, publisher_type="parquet_gcs")
    assert engine.publisher.__class__.__name__ == "ParquetGCSPublisher"
    assert engine.publisher.gcs_config.bucket == "raw-industrial"


def test_parquet_gcs_uses_gcs_service_account_file_for_storage_client():
    publisher = ParquetGCSBigQueryPublisher(
        BigQueryConfig(project_id="demo-project", dataset="industrial", table="pi_data"),
        GCSConfig(bucket="raw-industrial", service_account_file="config/service-account.json"),
        ParquetConfig(output_dir="output/parquet"),
    )
    assert publisher.gcs_config.service_account_file == "config/service-account.json"


def test_gcs_config_deletes_local_parquet_after_upload_by_default():
    assert GCSConfig().delete_local_file_after_upload is True


def test_parquet_gcs_deletes_local_file_after_successful_upload(tmp_path, monkeypatch):
    publisher = ParquetGCSPublisher(
        BigQueryConfig(project_id="demo-project"),
        GCSConfig(bucket="demo-bucket"),
        ParquetConfig(output_dir=str(tmp_path)),
    )
    event = TagEvent(
        source="piapi",
        server="PI-SERVER-01",
        site="site1",
        tag="SINUSOID",
        timestamp=datetime(2026, 8, 26, 0, 0, tzinfo=timezone.utc),
        value=1.0,
    )
    monkeypatch.setattr(publisher, "_upload_to_gcs", lambda file_path: "gs://demo-bucket/export.jsonl")

    publisher.publish_batch([event])
    publisher.flush()

    assert not list(tmp_path.glob("industrial-flow-*.jsonl"))


def test_bigquery_publisher_factory_selection():
    config = PublisherConfig(type="bigquery", bigquery=BigQueryConfig(project_id="demo-project"))
    publisher = create_publisher(config)
    assert publisher.__class__.__name__ == "BigQueryPublisher"


def test_bigquery_config_accepts_service_account_file():
    config = BigQueryConfig(
        project_id="demo-project",
        dataset="industrial",
        table="pi_data",
        service_account_file="/path/to/service-account.json",
    )
    assert config.service_account_file == "/path/to/service-account.json"


def test_partition_date_uses_industrial_timestamp():
    event = TagEvent(
        source="piapi",
        server="PI-SERVER-01",
        site="site1",
        tag="sinusoid",
        timestamp=datetime(2026, 8, 26, 23, 50, 0, tzinfo=timezone.utc),
        value=42.0,
    )
    assert industrial_partition_date(event) == "2026-08-26"


def test_parse_datetime_preserves_utc_from_cli_input():
    value = parse_datetime("2026-08-26T00:00:00Z")
    assert value.isoformat() == "2026-08-26T00:00:00+00:00"
    assert value.date().isoformat() == "2026-08-26"


def test_historical_allows_pure_parquet_without_gcs_or_bigquery():
    cfg = load_config("config/config.yaml")
    assert _validate_mode_publisher(cfg, "historical", "parquet") == "parquet"


def test_pure_parquet_publisher_does_not_require_gcs(tmp_path):
    config = PublisherConfig(type="parquet", parquet=ParquetConfig(output_dir=str(tmp_path)))
    publisher = create_publisher(config)
    event = TagEvent(
        source="piapi",
        server="PI-SERVER-01",
        site="site1",
        tag="sinusoid",
        timestamp=datetime(2026, 8, 26, 23, 50, 0, tzinfo=timezone.utc),
        value=42.0,
    )
    publisher.publish_batch([event])
    publisher.flush()
    files = list(tmp_path.glob("industrial-flow-*.jsonl"))
    assert len(files) == 1
    assert "site1" in files[0].name
    assert "2026-08-26" in files[0].name


def test_pure_parquet_publisher_overwrites_same_file_name_in_place(tmp_path):
    config = PublisherConfig(type="parquet", parquet=ParquetConfig(output_dir=str(tmp_path)))
    publisher = create_publisher(config)
    first = TagEvent(
        source="piapi",
        server="PI-SERVER-01",
        site="site1",
        tag="sinusoid",
        timestamp=datetime(2026, 8, 26, 23, 50, 0, tzinfo=timezone.utc),
        value=42.0,
    )
    second = TagEvent(
        source="piapi",
        server="PI-SERVER-01",
        site="site1",
        tag="sinusoid",
        timestamp=datetime(2026, 8, 26, 23, 50, 0, tzinfo=timezone.utc),
        value=99.0,
    )

    publisher.publish_batch([first])
    publisher.flush()
    publisher.publish_batch([second])
    publisher.flush()

    files = sorted(tmp_path.glob("industrial-flow-*.jsonl"))
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8")
    assert '"value": 99.0' in content


def test_cli_publisher_override_has_priority_over_yaml_config():
    cfg = load_config("config/config.yaml")
    cfg.historical = PublisherConfig(type="parquet_gcs_bigquery")
    assert _validate_mode_publisher(cfg, "historical", "parquet") == "parquet"


def test_historical_requires_parquet_export_only():
    cfg = load_config("config/config.yaml")
    try:
        _validate_mode_publisher(cfg, "historical", "bigquery")
        raise AssertionError("Expected ValueError for realtime BigQuery publisher in historical mode")
    except ValueError as exc:
        assert "Historical mode always exports data as Parquet" in str(exc)


def test_realtime_accepts_streaming_publishers():
    cfg = load_config("config/config.yaml")
    assert _validate_mode_publisher(cfg, "realtime", "bigquery") == "bigquery"
    assert _validate_mode_publisher(cfg, "realtime", "kafka") == "kafka"


def test_realtime_invalid_historical_publisher_shows_supported_pipelines():
    cfg = load_config("config/config.yaml")
    try:
        _validate_mode_publisher(cfg, "realtime", "parquet")
        raise AssertionError("Expected ValueError for historical publisher in realtime mode")
    except ValueError as exc:
        assert "Supported values:" in str(exc)
        assert "- parquet = PI → Parquet" in str(exc)
        assert "- parquet_gcs_bigquery = PI → Parquet → GCS → BigQuery Load Job" in str(exc)


def test_mode_specific_type_is_used_when_cli_does_not_override():
    cfg = AppConfig(realtime=PublisherConfig(type="file"), historical=PublisherConfig(type="parquet"))
    assert _validate_mode_publisher(cfg, "realtime", None) == "file"
    assert _validate_mode_publisher(cfg, "historical", None) == "parquet"


def test_legacy_publisher_yaml_block_is_ignored(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "publisher:\n  type: \"bigquery\"\nrealtime:\n  type: \"console\"\nhistorical:\n  type: \"parquet\"\n",
        encoding="utf-8",
    )

    cfg = load_config(config_path)

    assert cfg.realtime.type == "console"
    assert cfg.historical.type == "parquet"
    assert "publisher" not in cfg.model_fields


def test_cli_handles_optional_dependency_error_from_publisher(monkeypatch):
    def fake_factory(*args, **kwargs):
        raise RuntimeError("Install Kafka dependencies with: pip install 'industrial-flow[kafka]'")

    monkeypatch.setattr("industrial_flow.engine.create_publisher", fake_factory)
    result = runner.invoke(app, ["realtime", "--config", "config/config.yaml", "--type", "kafka"])
    assert result.exit_code == 1
    assert "Install Kafka dependencies" in result.output
    assert "Traceback" not in result.output


def test_historical_publisher_writes_jsonl_without_pyarrow(tmp_path):
    publisher = ParquetGCSBigQueryPublisher(
        BigQueryConfig(project_id="demo-project", dataset="industrial", table="pi_data"),
        GCSConfig(bucket="demo-bucket"),
        ParquetConfig(output_dir=str(tmp_path)),
    )
    event = TagEvent(
        source="piapi",
        server="PI-SERVER-01",
        site="site1",
        tag="sinusoid",
        timestamp=datetime(2026, 8, 26, 23, 50, 0, tzinfo=timezone.utc),
        value=42.0,
    )
    path = publisher._write_parquet([event])
    assert path.endswith(".jsonl")
    with open(path, "r", encoding="utf-8") as fp:
        content = fp.read()
    assert '"tag": "sinusoid"' in content


def test_pure_parquet_publisher_groups_files_by_day_and_tag(tmp_path):
    config = PublisherConfig(type="parquet", parquet=ParquetConfig(output_dir=str(tmp_path), row_group_size=2))
    publisher = create_publisher(config)
    events = [
        TagEvent(
            source="piapi",
            server="PI-SERVER-01",
            site="site1",
            tag="SINUSOID",
            timestamp=datetime(2026, 8, 26, 0, 0, tzinfo=timezone.utc),
            value=1.0,
        ),
        TagEvent(
            source="piapi",
            server="PI-SERVER-01",
            site="site1",
            tag="SINUSOID",
            timestamp=datetime(2026, 8, 26, 0, 1, tzinfo=timezone.utc),
            value=2.0,
        ),
        TagEvent(
            source="piapi",
            server="PI-SERVER-01",
            site="site1",
            tag="FLOWRATE",
            timestamp=datetime(2026, 8, 26, 0, 0, tzinfo=timezone.utc),
            value=3.0,
        ),
    ]

    publisher.publish_batch(events)
    publisher.flush()

    files = sorted(tmp_path.glob("industrial-flow-*.jsonl"))
    assert len(files) == 2
    assert all("site1" in file.name for file in files)
    assert all("SINUSOID" in file.name or "FLOWRATE" in file.name for file in files)
    assert all("-site1-" in file.name for file in files)

    publisher.publish_batch(events)
    publisher.flush()

    remaining = sorted(tmp_path.glob("industrial-flow-*.jsonl"))
    assert len(remaining) == 2


def test_pure_parquet_publisher_appends_read_batches_to_one_day_tag_file(tmp_path):
    config = PublisherConfig(type="parquet", parquet=ParquetConfig(output_dir=str(tmp_path), row_group_size=1))
    publisher = create_publisher(config)
    first = TagEvent(
        source="piapi",
        server="PI-SERVER-01",
        site="site1",
        tag="SINUSOID",
        timestamp=datetime(2026, 8, 26, 0, 0, tzinfo=timezone.utc),
        value=1.0,
    )
    second = TagEvent(
        source="piapi",
        server="PI-SERVER-01",
        site="site1",
        tag="SINUSOID",
        timestamp=datetime(2026, 8, 26, 0, 1, tzinfo=timezone.utc),
        value=2.0,
    )

    publisher.publish_batch([first])
    publisher.publish_batch([second])
    publisher.flush()

    files = list(tmp_path.glob("industrial-flow-2026-08-26-site1-SINUSOID.jsonl"))
    assert len(files) == 1
    assert len(files[0].read_text(encoding="utf-8").splitlines()) == 2


def test_historical_publisher_builds_partition_replacement_sql_for_bigquery():
    publisher = ParquetGCSBigQueryPublisher(
        BigQueryConfig(project_id="demo-project", dataset="industrial", table="pi_data"),
        GCSConfig(bucket="demo-bucket"),
        ParquetConfig(output_dir="output/parquet"),
    )
    sql = publisher._build_partition_replacement_sql(
        "demo-project.industrial.pi_data",
        "demo-project.industrial.pi_data__staging_123",
        partition_date="2026-08-26",
    )
    assert "MERGE `demo-project.industrial.pi_data` AS target" in sql
    assert "USING `demo-project.industrial.pi_data__staging_123` AS staging" in sql
    assert "ON target.event_id = staging.event_id" in sql
    assert "WHEN MATCHED" in sql
    assert "target.value IS DISTINCT FROM CAST(staging.value AS STRING)" in sql
    assert "CAST(staging.value AS STRING)" in sql
    assert "CAST(staging.point_id AS INT64)" in sql
    assert "CAST(staging.digital_code AS INT64)" in sql
    assert "CAST(staging.digital_set_id AS INT64)" in sql
    assert "CAST(staging.digital_state_id AS INT64)" in sql
    assert "CAST(staging.raw_istat AS INT64)" in sql
    assert "WHEN NOT MATCHED" in sql
    assert "AND staging.timestamp >= TIMESTAMP('2026-08-26T00:00:00+00:00')" in sql


def test_historical_bigquery_staging_schema_keeps_value_as_string():
    publisher = ParquetGCSBigQueryPublisher(
        BigQueryConfig(project_id="demo-project", dataset="industrial", table="pi_data"),
        GCSConfig(bucket="demo-bucket"),
        ParquetConfig(output_dir="output/parquet"),
    )

    schema = publisher._staging_schema()

    assert next(field for field in schema if field.name == "value").field_type == "STRING"
    assert next(field for field in schema if field.name == "timestamp").field_type == "TIMESTAMP"
