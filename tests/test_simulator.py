from datetime import datetime, timezone

from industrial_flow.config import PIConfig
from industrial_flow.pi.simulator import SimulatedPIReader


def test_simulator_reader_generates_events():
    reader = SimulatedPIReader(PIConfig(provider="simulator"))
    tags = ["A", "B"]
    reader.connect()
    reader.cache_points(tags)
    events = reader.read_interpolated_values(
        tags,
        datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc),
        60,
    )
    assert len(events) == 4
    assert events[0].tag in tags
