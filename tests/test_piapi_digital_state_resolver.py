from industrial_flow.config import PIConfig
from industrial_flow.pi.piapi import PIAPIReader


class FakePIAPI:
    def __init__(self):
        self.calls = 0

    def pipt_digstate(self, digcode, buffer, length):
        self.calls += 1
        assert digcode.value == -62914560
        value = b"Bad Input"
        buffer.value = value[: length.value - 1]
        return 0


def test_piapi_resolves_digital_state_with_pipt_digstate_and_caches_it():
    fake = FakePIAPI()
    reader = PIAPIReader(PIConfig(provider="piapi", server="PI-TEST", site="test"))
    reader.piapi = fake

    first = reader._resolve_digital_state(-62914560, set_id=960, state_id=0)
    second = reader._resolve_digital_state(-62914560, set_id=960, state_id=0)

    assert first is not None
    assert first.digital_code == -62914560
    assert first.digital_state_name == "Bad Input"
    assert first.source == "piapi.pipt_digstate"
    assert second is first
    assert fake.calls == 1
