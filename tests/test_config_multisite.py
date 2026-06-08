from industrial_flow.config import AppConfig, PIConfig, SiteConfig


def test_default_single_site_is_created_for_backward_compatibility():
    cfg = AppConfig(pi=PIConfig(site="site1"), tags_file="tags.txt")
    assert len(cfg.sites) == 1
    assert cfg.sites[0].id == "site1"
    assert cfg.sites[0].tags_file == "tags.txt"


def test_site_overrides_publisher_targets():
    site = SiteConfig(
        id="site2",
        pi=PIConfig(provider="simulator", server="PI-SERVER-2"),
        tags_file="tags/site2.txt",
        kafka_topic="industrial-flow.site2.pi-tags",
        pubsub_topic_id="industrial-flow-site2-pi-tags",
        file_output_path="output/site2/events.jsonl",
    )
    cfg = AppConfig(sites=[site])
    publisher = cfg.publisher.for_site(site)
    assert publisher.kafka.topic == "industrial-flow.site2.pi-tags"
    assert publisher.pubsub.topic_id == "industrial-flow-site2-pi-tags"
    assert publisher.file.output_path == "output/site2/events.jsonl"
