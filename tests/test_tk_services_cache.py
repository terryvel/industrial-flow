from __future__ import annotations

from pathlib import Path
from tk.models import ServiceType
from tk.process_manager import ServiceSpec
from tk.services_cache import SavedService, ServicesCacheStore


def test_services_cache_store_save_load(tmp_path: Path):
    cache_file = tmp_path / "test_services.json"
    store = ServicesCacheStore(cache_file=cache_file)

    spec1 = ServiceSpec(
        service_type=ServiceType.REALTIME,
        config_path="config/config.yaml",
        site="site1",
        output_type="bigquery",
    )
    spec2 = ServiceSpec(
        service_type=ServiceType.HISTORICAL,
        config_path="config/config.yaml",
        start="2026-09-01T00:00:00Z",
        end="2026-09-02T00:00:00Z",
        site="site2",
        output_type="parquet",
    )

    services = [
        SavedService(id_str="01", spec=spec1),
        SavedService(id_str="02", spec=spec2),
    ]

    store.save(services)
    assert cache_file.exists()

    loaded = store.load()
    assert len(loaded) == 2
    assert loaded[0].id == "01"
    assert loaded[0].spec.service_type == ServiceType.REALTIME
    assert loaded[0].spec.site == "site1"
    assert loaded[1].id == "02"
    assert loaded[1].spec.service_type == ServiceType.HISTORICAL
    assert loaded[1].spec.site == "site2"


def test_services_cache_store_edit_spec(tmp_path: Path):
    cache_file = tmp_path / "test_services.json"
    store = ServicesCacheStore(cache_file=cache_file)

    spec_orig = ServiceSpec(
        service_type=ServiceType.REALTIME,
        config_path="config/config.yaml",
        site="siteA",
        output_type="console",
    )
    saved = SavedService(id_str="01", spec=spec_orig)
    store.save([saved])

    # Edit spec
    spec_edited = ServiceSpec(
        service_type=ServiceType.REALTIME,
        config_path="config/config.yaml",
        site="siteB_edited",
        output_type="bigquery",
    )
    saved.spec = spec_edited
    store.save([saved])

    loaded = store.load()
    assert len(loaded) == 1
    assert loaded[0].spec.site == "siteB_edited"
    assert loaded[0].spec.output_type == "bigquery"
