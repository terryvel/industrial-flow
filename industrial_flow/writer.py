from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from rich.console import Console

from industrial_flow.config import AppConfig
from industrial_flow.pi.factory import create_pi_reader


console = Console()


@dataclass(frozen=True)
class WriteRequest:
    site: str
    tag: str
    timestamp: datetime
    value: float
    istat: int = 0
    wait: bool = True


def parse_write_request(payload: dict) -> WriteRequest:
    try:
        site = str(payload["site"]).strip()
        tag = str(payload["tag"]).strip().upper()
        timestamp = datetime.fromisoformat(str(payload["timestamp"]).replace("Z", "+00:00"))
        value = float(payload["value"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Writer payload requires site, tag, timestamp, and numeric value.") from exc
    if not site or not tag:
        raise ValueError("Writer payload requires non-empty site and tag.")
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return WriteRequest(
        site=site,
        tag=tag,
        timestamp=timestamp.astimezone(timezone.utc),
        value=value,
        istat=int(payload.get("istat", 0)),
        wait=bool(payload.get("wait", True)),
    )


class PIArchiveWriter:
    def __init__(self, config: AppConfig):
        self.config = config

    def write(self, request: WriteRequest) -> None:
        site = self.config.site_by_id(request.site)
        reader = create_pi_reader(site.pi)
        if not hasattr(reader, "write_archive_value"):
            raise ValueError(f"PI provider '{site.pi.provider}' does not support archive writes.")
        reader.connect()
        reader.write_archive_value(
            request.tag,
            request.timestamp,
            request.value,
            istat=request.istat,
            wait=request.wait,
        )


class PubSubPIArchiveWriter:
    def __init__(self, config: AppConfig):
        try:
            from google.cloud import pubsub_v1
        except ImportError as exc:
            raise RuntimeError("Install Pub/Sub dependencies with: pip install 'industrial-flow[pubsub]'") from exc

        self.config = config
        self.pubsub_v1 = pubsub_v1
        self.writer = PIArchiveWriter(config)

    def run(self) -> None:
        pubsub_config = self.config.writer.pubsub
        if not pubsub_config.project_id or not pubsub_config.subscription_id:
            raise ValueError("writer.pubsub.project_id and writer.pubsub.subscription_id are required.")
        client_kwargs = {}
        if pubsub_config.service_account_file:
            from google.oauth2 import service_account

            client_kwargs["credentials"] = service_account.Credentials.from_service_account_file(
                pubsub_config.service_account_file
            )
        subscriber = self.pubsub_v1.SubscriberClient(**client_kwargs)
        subscription = subscriber.subscription_path(pubsub_config.project_id, pubsub_config.subscription_id)

        def callback(message) -> None:
            try:
                request = parse_write_request(json.loads(message.data.decode("utf-8")))
                received_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                console.print(
                    f"[cyan]{received_at} | PI writer: Pub/Sub event received "
                    f"{message.message_id} | {request.site} {request.tag} "
                    f"{request.timestamp.isoformat()}[/cyan]"
                )
                self.writer.write(request)
            except Exception as exc:
                failed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                console.print(
                    f"[red]{failed_at} | PI writer: Pub/Sub event failed "
                    f"{message.message_id}: {exc}[/red]"
                )
                message.nack()
                return
            written_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            console.print(
                f"[green]{written_at} | PI writer: archive value written "
                f"{message.message_id} | {request.site} {request.tag} {request.value}[/green]"
            )
            message.ack()

        future = subscriber.subscribe(subscription, callback=callback)
        try:
            future.result()
        except KeyboardInterrupt:
            future.cancel()
            future.result()