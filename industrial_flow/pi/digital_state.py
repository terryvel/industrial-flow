from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True, slots=True)
class DigitalStateRef:
    """Reference encoded in a negative PI istat value.

    In the legacy PI API, the negative istat value itself can be passed to
    pipt_digstate(digcode, ...). We also keep the decoded set/state numbers for
    troubleshooting and lineage because some legacy docs describe the high/low
    16-bit layout.
    """

    raw_istat: int
    digital_code: int
    digital_set_id: int
    digital_state_id: int


@dataclass(frozen=True, slots=True)
class DigitalStateInfo:
    """Resolved Digital State metadata used to enrich outgoing events."""

    digital_code: int
    digital_state_name: str | None = None
    digital_set_id: int | None = None
    digital_state_id: int | None = None
    source: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def decode_negative_istat(istat: int) -> DigitalStateRef | None:
    """
    Decode a negative PI istat value as a digital state reference.

    Important behavior for industrial-flow:
    - The original negative istat is preserved as digital_code.
    - For PI API environments that expose pipt_digstate(), digital_code should be
      passed directly to that function to retrieve the human-readable state text.
    - The 16-bit decomposition is retained as additional metadata only.
    """
    if istat >= 0:
        return None

    raw = abs(istat)
    return DigitalStateRef(
        raw_istat=istat,
        digital_code=istat,
        digital_set_id=(raw >> 16) & 0xFFFF,
        digital_state_id=raw & 0xFFFF,
    )


def unresolved_digital_state(ref: DigitalStateRef) -> DigitalStateInfo:
    """Preserve the full semantic reference even when the PI API cannot resolve the name."""
    return DigitalStateInfo(
        digital_code=ref.digital_code,
        digital_state_name=None,
        digital_set_id=ref.digital_set_id,
        digital_state_id=ref.digital_state_id,
        source="unresolved",
    )
