from industrial_flow.pi.digital_state import DigitalStateInfo
from industrial_flow.pi.digital_state_cache import DigitalStateCacheStore


def test_digital_state_cache_is_isolated_by_site_server_and_code(tmp_path):
    store = DigitalStateCacheStore(tmp_path / "digital-states.json")

    store.merge(
        "site1",
        "PI-SERVER-1",
        {
            -62914560: DigitalStateInfo(
                digital_code=-62914560,
                digital_state_name="Shutdown",
                source="test",
            )
        },
    )

    store.merge(
        "site2",
        "PI-SERVER-2",
        {
            -62914560: DigitalStateInfo(
                digital_code=-62914560,
                digital_state_name="Comm Fail",
                source="test",
            )
        },
    )

    site1 = store.load("site1", "PI-SERVER-1")
    site2 = store.load("site2", "PI-SERVER-2")

    assert site1[-62914560].digital_state_name == "Shutdown"
    assert site2[-62914560].digital_state_name == "Comm Fail"
    assert store.load("site1", "PI-SERVER-2") == {}
