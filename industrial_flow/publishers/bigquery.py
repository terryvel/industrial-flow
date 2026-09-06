from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
import threading

from rich.console import Console

from industrial_flow.config import BigQueryConfig, GCSConfig, ParquetConfig
from industrial_flow.models.event import TagEvent
from industrial_flow.publishers.base import Publisher


console = Console()


def industrial_partition_date(value: datetime | TagEvent | str) -> str:
    if isinstance(value, TagEvent):
        timestamp = value.timestamp
    elif isinstance(value, str):
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        timestamp = value

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.date().isoformat()


class BigQueryPublisher(Publisher):
    """Realtime publisher backed by the BigQuery JSON streaming API."""

    def __init__(self, config: BigQueryConfig):
        try:
            from google.cloud import bigquery
        except ImportError as exc:  # pragma: no cover - exercised via dependency checks
            raise RuntimeError(
                "Install BigQuery dependencies with: pip install 'industrial-flow[bigquery]'"
            ) from exc

        self.config = config
        self._client = None
        self._buffer: list[dict] = []

    def _get_client(self):
        if self._client is None:
            client_kwargs = {
                "project": self.config.project_id,
                "location": self.config.location,
            }
            if self.config.service_account_file:
                from google.oauth2 import service_account

                credentials = service_account.Credentials.from_service_account_file(
                    self.config.service_account_file
                )
                client_kwargs["credentials"] = credentials
            self._client = __import__("google.cloud.bigquery", fromlist=["Client"]).Client(**client_kwargs)
        return self._client

    @property
    def client(self):
        return self._get_client()

    @property
    def table_ref(self):
        return self.client.dataset(self.config.dataset).table(self.config.table)

    def _serialize_rows(self, events: list[TagEvent]) -> tuple[list[dict], list[str]]:
        rows: list[dict] = []
        row_ids: list[str] = []
        for event in events:
            rows.append(event.to_dict())
            row_ids.append(event.idempotency_key())
        return rows, row_ids

    def publish_batch(self, events: list[TagEvent]) -> None:
        if not events:
            return
        self._buffer.extend(events)
        if len(self._buffer) >= self.config.max_batch_rows:
            self.flush()

    def flush(self) -> None:
        if not self._buffer:
            return
        events = self._buffer
        self._buffer = []
        rows, row_ids = self._serialize_rows(events)
        errors = self.client.insert_rows_json(self.table_ref, rows, row_ids=row_ids)
        if errors:
            raise RuntimeError(f"BigQuery row insert failed: {errors}")

    def close(self) -> None:
        self.flush()


class ParquetPublisher(Publisher):
    """Historical publisher that writes JSONL batches to disk without GCS or BigQuery dependencies."""

    def __init__(self, parquet_config: ParquetConfig):
        self.parquet_config = parquet_config
        self._written_files: set[Path] = set()
        self._lock = threading.Lock()

    def _write_parquet_group(self, events: list[TagEvent]) -> str:
        output_dir = Path(self.parquet_config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        partition_date = industrial_partition_date(events[0])
        site = events[0].site
        filename = f"{self.parquet_config.file_prefix}-{partition_date}-{site}.jsonl"
        file_path = output_dir / filename

        with self._lock:
            mode = "a" if file_path in self._written_files else "w"
            with file_path.open(mode, encoding="utf-8") as fp:
                for event in events:
                    fp.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
            self._written_files.add(file_path)
        return str(file_path)

    def publish_batch(self, events: list[TagEvent]) -> None:
        if not events:
            return

        grouped: dict[tuple[str, str], list[TagEvent]] = {}
        for event in events:
            key = (industrial_partition_date(event), event.site)
            grouped.setdefault(key, []).append(event)
        for grouped_events in grouped.values():
            self._write_parquet_group(grouped_events)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.flush()


class ParquetGCSPublisher(Publisher):
    """Historical publisher that writes a portable batch file and uploads it to GCS without loading into BigQuery."""

    def __init__(self, bigquery_config: BigQueryConfig, gcs_config: GCSConfig, parquet_config: ParquetConfig):
        try:
            from google.cloud import storage
        except ImportError as exc:  # pragma: no cover - exercised via dependency checks
            raise RuntimeError(
                "Install GCS dependencies with: pip install 'industrial-flow[bigquery]'"
            ) from exc

        self.bigquery_config = bigquery_config
        self.gcs_config = gcs_config
        self.parquet_config = parquet_config
        self.storage = storage
        self._storage_client = None
        self._written_files: set[Path] = set()
        self._uploaded_files: set[Path] = set()
        self._lock = threading.Lock()

    def _get_storage_client(self):
        if self._storage_client is None:
            client_kwargs = {"project": self.bigquery_config.project_id}
            service_account_file = self.gcs_config.service_account_file or self.bigquery_config.service_account_file
            if service_account_file:
                from google.oauth2 import service_account

                credentials = service_account.Credentials.from_service_account_file(service_account_file)
                client_kwargs["credentials"] = credentials
            self._storage_client = self.storage.Client(**client_kwargs)
        return self._storage_client

    @property
    def storage_client(self):
        return self._get_storage_client()

    def _write_parquet(self, events: list[TagEvent]) -> str:
        output_dir = Path(self.parquet_config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        partition_date = industrial_partition_date(events[0])
        site = events[0].site
        filename = f"{self.parquet_config.file_prefix}-{partition_date}-{site}.jsonl"
        file_path = output_dir / filename

        with self._lock:
            mode = "a" if file_path in self._written_files else "w"
            with file_path.open(mode, encoding="utf-8") as fp:
                for event in events:
                    fp.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
            self._written_files.add(file_path)
        return str(file_path)

    def _upload_to_gcs(self, file_path: str, destination_name: str | None = None) -> str:
        if not self.gcs_config.bucket:
            raise ValueError("Google Cloud Storage bucket is required for parquet reconciliation.")

        bucket = self.storage_client.bucket(self.gcs_config.bucket)
        full_prefix = self.gcs_config.prefix.rstrip("/")
        name = destination_name or Path(file_path).name
        blob_path = f"{full_prefix}/{name}"
        blob = bucket.blob(blob_path)
        blob.upload_from_filename(file_path)
        return f"gs://{self.gcs_config.bucket}/{blob_path}"

    def publish_batch(self, events: list[TagEvent]) -> None:
        if not events:
            return

        grouped: dict[tuple[str, str], list[TagEvent]] = {}
        for event in events:
            key = (industrial_partition_date(event), event.site)
            grouped.setdefault(key, []).append(event)
        for grouped_events in grouped.values():
            self._write_parquet(grouped_events)

    def flush(self) -> None:
        for file_path in sorted(self._written_files - self._uploaded_files):
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            console.print(f"[cyan]{timestamp} | sending Parquet to GCS: {file_path}[/cyan]")
            self._upload_to_gcs(str(file_path))
            self._uploaded_files.add(file_path)
            if self.gcs_config.delete_local_file_after_upload:
                file_path.unlink(missing_ok=True)

    def close(self) -> None:
        self.flush()


class ParquetGCSBigQueryPublisher(Publisher):
    """Historical reconciliation publisher that writes a portable batch file, uploads it to GCS and loads it into BigQuery.

    The historical path intentionally avoids pyarrow to keep compatibility with Windows x32 environments
    while still producing a GCS object that BigQuery can load reliably.
    """

    def __init__(self, bigquery_config: BigQueryConfig, gcs_config: GCSConfig, parquet_config: ParquetConfig):
        try:
            from google.cloud import bigquery, storage
        except ImportError as exc:  # pragma: no cover - exercised via dependency checks
            raise RuntimeError(
                "Install BigQuery/GCS dependencies with: pip install 'industrial-flow[bigquery]'"
            ) from exc

        self.bigquery_config = bigquery_config
        self.gcs_config = gcs_config
        self.parquet_config = parquet_config
        self.bigquery = bigquery
        self.storage = storage
        self._client = None
        self._storage_client = None
        self._written_files: dict[Path, str] = {}
        self._uploaded_files: dict[Path, str] = {}
        self._lock = threading.Lock()

    def _get_client(self):
        if self._client is None:
            client_kwargs = {
                "project": self.bigquery_config.project_id,
                "location": self.bigquery_config.location,
            }
            if self.bigquery_config.service_account_file:
                from google.oauth2 import service_account

                credentials = service_account.Credentials.from_service_account_file(
                    self.bigquery_config.service_account_file
                )
                client_kwargs["credentials"] = credentials
            self._client = self.bigquery.Client(**client_kwargs)
        return self._client

    def _get_storage_client(self):
        if self._storage_client is None:
            client_kwargs = {"project": self.bigquery_config.project_id}
            service_account_file = self.gcs_config.service_account_file or self.bigquery_config.service_account_file
            if service_account_file:
                from google.oauth2 import service_account

                credentials = service_account.Credentials.from_service_account_file(service_account_file)
                client_kwargs["credentials"] = credentials
            self._storage_client = self.storage.Client(**client_kwargs)
        return self._storage_client

    @property
    def client(self):
        return self._get_client()

    @property
    def storage_client(self):
        return self._get_storage_client()

    def _write_parquet(self, events: list[TagEvent]) -> str:
        output_dir = Path(self.parquet_config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        partition_date = industrial_partition_date(events[0])
        site = events[0].site
        filename = f"{self.parquet_config.file_prefix}-{partition_date}-{site}.jsonl"
        file_path = output_dir / filename

        with self._lock:
            mode = "a" if file_path in self._written_files else "w"
            with file_path.open(mode, encoding="utf-8") as fp:
                for event in events:
                    fp.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
            self._written_files[file_path] = partition_date
        return str(file_path)

    def _upload_to_gcs(self, file_path: str, destination_name: str | None = None) -> str:
        if not self.gcs_config.bucket:
            raise ValueError("Google Cloud Storage bucket is required for parquet reconciliation.")

        bucket = self.storage_client.bucket(self.gcs_config.bucket)
        full_prefix = self.gcs_config.prefix.rstrip("/")
        name = destination_name or Path(file_path).name
        blob_path = f"{full_prefix}/{name}"
        blob = bucket.blob(blob_path)
        blob.upload_from_filename(file_path)
        return f"gs://{self.gcs_config.bucket}/{blob_path}"

    def _staging_schema(self):
        return [
            self.bigquery.SchemaField("source", "STRING"),
            self.bigquery.SchemaField("server", "STRING"),
            self.bigquery.SchemaField("site", "STRING"),
            self.bigquery.SchemaField("tag", "STRING"),
            self.bigquery.SchemaField("timestamp", "TIMESTAMP"),
            self.bigquery.SchemaField("value", "STRING"),
            self.bigquery.SchemaField("quality", "STRING"),
            self.bigquery.SchemaField("point_id", "INT64"),
            self.bigquery.SchemaField("value_type", "STRING"),
            self.bigquery.SchemaField("digital_code", "INT64"),
            self.bigquery.SchemaField("digital_set_id", "INT64"),
            self.bigquery.SchemaField("digital_state_id", "INT64"),
            self.bigquery.SchemaField("digital_state_name", "STRING"),
            self.bigquery.SchemaField("raw_istat", "INT64"),
            self.bigquery.SchemaField("event_id", "STRING"),
        ]

    def _build_partition_replacement_sql(self, target_table: str, staging_table: str, partition_date: str | None = None) -> str:
        if not partition_date:
            raise ValueError("partition_date is required for historicalBigQuery partition replacement")

        partition_start = f"TIMESTAMP('{partition_date}T00:00:00+00:00')"
        partition_end = f"TIMESTAMP('{partition_date}T23:59:59.999999+00:00')"

        return f"""
        MERGE `{target_table}` AS target
        USING `{staging_table}` AS staging
                ON target.event_id = staging.event_id
                    AND target.timestamp >= {partition_start}
                    AND target.timestamp < {partition_end}
                    AND staging.timestamp >= {partition_start}
                    AND staging.timestamp < {partition_end}
        WHEN MATCHED
          AND target.timestamp >= {partition_start}
          AND target.timestamp < {partition_end}
          AND target.value IS DISTINCT FROM CAST(staging.value AS STRING)
        THEN
          UPDATE SET
            target.value = CAST(staging.value AS STRING),
            target.quality = staging.quality,
            target.point_id = CAST(staging.point_id AS INT64),
            target.value_type = staging.value_type,
            target.digital_code = CAST(staging.digital_code AS INT64),
            target.digital_set_id = CAST(staging.digital_set_id AS INT64),
            target.digital_state_id = CAST(staging.digital_state_id AS INT64),
            target.digital_state_name = staging.digital_state_name,
            target.raw_istat = CAST(staging.raw_istat AS INT64),
            target.ingestion_timestamp = CURRENT_TIMESTAMP()
        WHEN NOT MATCHED
          AND staging.timestamp >= {partition_start}
          AND staging.timestamp < {partition_end}
        THEN
          INSERT (
            event_id,
            timestamp,
            source,
            server,
            site,
            tag,
            value,
            quality,
            point_id,
            value_type,
            digital_code,
            digital_set_id,
            digital_state_id,
            digital_state_name,
            raw_istat,
            ingestion_timestamp
          )
          VALUES (
            staging.event_id,
            staging.timestamp,
            staging.source,
            staging.server,
            staging.site,
            staging.tag,
            CAST(staging.value AS STRING),
            staging.quality,
            CAST(staging.point_id AS INT64),
            staging.value_type,
            CAST(staging.digital_code AS INT64),
            CAST(staging.digital_set_id AS INT64),
            CAST(staging.digital_state_id AS INT64),
            staging.digital_state_name,
            CAST(staging.raw_istat AS INT64),
            CURRENT_TIMESTAMP()
          )
        """

    def _replace_partition(self, partition_date: str, gcs_uris: list[str]) -> None:
        dataset_table = f"{self.bigquery_config.project_id}.{self.bigquery_config.dataset}.{self.bigquery_config.table}"
        staging_table = f"{self.bigquery_config.project_id}.{self.bigquery_config.dataset}.{self.bigquery_config.table}__staging_{partition_date.replace('-', '')}"

        temp_table_ref = self.client.dataset(self.bigquery_config.dataset).table(
            f"{self.bigquery_config.table}__staging_{partition_date.replace('-', '')}"
        )
        job_config = self.bigquery.LoadJobConfig(
            source_format=self.bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=self.bigquery.WriteDisposition.WRITE_TRUNCATE,
            schema=self._staging_schema(),
        )
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        console.print(
            f"[cyan]{timestamp} | loading {len(gcs_uris)} Parquet files into BigQuery staging table "
            f"for partition {partition_date}[/cyan]"
        )
        load_job = self.client.load_table_from_uri(
            gcs_uris,
            temp_table_ref,
            job_config=job_config,
        )
        load_job.result()

        replacement_sql = self._build_partition_replacement_sql(dataset_table, staging_table, partition_date=partition_date)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        console.print(f"[cyan]{timestamp} | reconciling BigQuery partition {partition_date}[/cyan]")
        self.client.query(replacement_sql).result()

        cleanup_sql = f"DROP TABLE `{staging_table}`"
        self.client.query(cleanup_sql).result()

    def publish_batch(self, events: list[TagEvent]) -> None:
        if not events:
            return

        grouped: dict[tuple[str, str], list[TagEvent]] = {}
        for event in events:
            key = (industrial_partition_date(event), event.site)
            grouped.setdefault(key, []).append(event)
        for grouped_events in grouped.values():
            self._write_parquet(grouped_events)

    def flush(self) -> None:
        gcs_uris_by_partition: dict[str, list[str]] = {}
        for file_path, partition_date in sorted(self._written_files.items()):
            if file_path in self._uploaded_files:
                continue
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            console.print(f"[cyan]{timestamp} | sending Parquet to GCS: {file_path}[/cyan]")
            gcs_uri = self._upload_to_gcs(str(file_path))
            if self.gcs_config.delete_local_file_after_upload:
                file_path.unlink(missing_ok=True)
            self._uploaded_files[file_path] = gcs_uri
            gcs_uris_by_partition.setdefault(partition_date, []).append(gcs_uri)
        for partition_date, gcs_uris in gcs_uris_by_partition.items():
            self._replace_partition(partition_date, gcs_uris)

    def upload_pending_files(self) -> list[str]:
        uploaded_uris: list[str] = []
        for file_path, partition_date in sorted(self._written_files.items()):
            if file_path in self._uploaded_files:
                continue
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            console.print(f"[cyan]{timestamp} | sending Parquet to GCS: {file_path}[/cyan]")
            gcs_uri = self._upload_to_gcs(str(file_path))
            if self.gcs_config.delete_local_file_after_upload:
                file_path.unlink(missing_ok=True)
            self._uploaded_files[file_path] = gcs_uri
            uploaded_uris.append(gcs_uri)
        return uploaded_uris

    def reconcile_partition(self, partition_date: str, gcs_uris: list[str]) -> None:
        if gcs_uris:
            self._replace_partition(partition_date, gcs_uris)

    def close(self) -> None:
        self.flush()


__all__ = [
    "BigQueryPublisher",
    "ParquetGCSBigQueryPublisher",
    "industrial_partition_date",
]
