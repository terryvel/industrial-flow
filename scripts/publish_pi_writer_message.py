from __future__ import annotations

import json
import random
from datetime import datetime, timezone

from google.cloud import pubsub_v1
from google.oauth2 import service_account


PROJECT_ID = "my-industrial-flow-project"
TOPIC_ID = "industrial-flow-pi-tags"
SERVICE_ACCOUNT_FILE = "config/gcp-service-account.json"

def main() -> None:
    credentials = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE)
    publisher = pubsub_v1.PublisherClient(credentials=credentials)
    topic_path = publisher.topic_path(PROJECT_ID, TOPIC_ID)
    payload = {
        "site": "site1",
        "tag": "TESTE_ESCRITA_01",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "value": round(random.uniform(0.0, 100.0), 2),
        "istat": 0,
        "wait": True,
    }
    data = json.dumps(payload).encode("utf-8")
    message_id = publisher.publish(topic_path, data).result()
    print(f"Published PI writer message: {message_id}")
    print(data)


if __name__ == "__main__":
    main()