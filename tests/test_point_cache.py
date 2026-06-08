from industrial_flow.pi.point_cache import PointIdCacheStore


def test_point_cache_is_isolated_by_site_and_server(tmp_path):
    store = PointIdCacheStore(tmp_path / "pointids.json")

    store.merge("site1", "PI-SERVER-1", {"TAG_A": 10, "TAG_B": 20})
    store.merge("site2", "PI-SERVER-2", {"TAG_A": 99})

    assert store.load("site1", "PI-SERVER-1") == {"TAG_A": 10, "TAG_B": 20}
    assert store.load("site2", "PI-SERVER-2") == {"TAG_A": 99}
    assert store.load("site1", "PI-SERVER-2") == {}


def test_point_cache_does_not_persist_missing_points(tmp_path):
    store = PointIdCacheStore(tmp_path / "pointids.json")

    store.merge("site1", "PI-SERVER-1", {"OK_TAG": 123, "MISSING_TAG": -1})

    assert store.load("site1", "PI-SERVER-1") == {"OK_TAG": 123}
