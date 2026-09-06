from pathlib import Path

from industrial_flow.pi.point_cache import PointIdCacheStore


def test_point_cache_falls_back_when_atomic_replace_is_blocked(tmp_path, monkeypatch):
    store = PointIdCacheStore(tmp_path / "pointids.json")
    original_replace = Path.replace

    def fake_replace(self, target):
        if self.name.endswith(".tmp"):
            raise PermissionError("Access is denied")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fake_replace)
    store.merge("site1", "PI-SERVER-1", {"TAG_A": 10, "TAG_B": 20})

    assert store.load("site1", "PI-SERVER-1") == {"TAG_A": 10, "TAG_B": 20}


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