from __future__ import annotations

from industrial_flow.config import PIConfig
from industrial_flow.pi.base import PIReader
from industrial_flow.pi.piapi import PIAPIReader
from industrial_flow.pi.simulator import SimulatedPIReader


def create_pi_reader(config: PIConfig) -> PIReader:
    if config.provider == "simulator":
        return SimulatedPIReader(config)
    if config.provider == "piapi":
        return PIAPIReader(config)
    raise ValueError(f"Unsupported PI provider: {config.provider}")
