"""Phase 18.6 §18.6 ledger #12 — Bus topic ownership is enforced."""
from __future__ import annotations

import os
import pytest


class TestBusTopicOwnerEnforced:
    """Proof test: bus topics have declared owners and enforce them."""

    def test_topics_yaml_exists(self) -> None:
        """topics.yaml file exists in common/bus/."""
        topics_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "common",
            "bus",
            "topics.yaml",
        )
        assert os.path.exists(topics_path), "common/bus/topics.yaml must exist"

    def test_topics_yaml_has_topics_key(self) -> None:
        """topics.yaml has a 'topics' top-level key."""
        import yaml

        topics_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "common",
            "bus",
            "topics.yaml",
        )
        with open(topics_path, "r") as fh:
            config = yaml.safe_load(fh)

        assert "topics" in config, "topics.yaml must have 'topics' key"
        assert isinstance(config["topics"], dict), "'topics' must be a dict"

    def test_each_topic_declares_owner(self) -> None:
        """Each topic in topics.yaml has an owner_component."""
        import yaml

        topics_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "common",
            "bus",
            "topics.yaml",
        )
        with open(topics_path, "r") as fh:
            config = yaml.safe_load(fh)

        topics = config.get("topics", {})
        for topic_name, topic_config in topics.items():
            assert (
                "owner_component" in topic_config
            ), f"Topic {topic_name} must declare 'owner_component'"

    def test_publisher_authenticator_exists(self) -> None:
        """publisher.py has PublisherAuthenticator and related classes."""
        from ai.common.bus.publisher import (
            BusUnauthorizedPublishError,
            PublisherAuthenticator,
            SimplePublisherAuthenticator,
            TopicPolicy,
        )

        assert PublisherAuthenticator is not None
        assert SimplePublisherAuthenticator is not None
        assert BusUnauthorizedPublishError is not None
        assert TopicPolicy is not None

    def test_publisher_can_check_ownership(self) -> None:
        """SimplePublisherAuthenticator can check topic ownership."""
        from ai.common.bus.publisher import SimplePublisherAuthenticator, TopicPolicy

        policy = TopicPolicy(
            topic_name="scrape.matched.v1",
            owner_component="datasource",
            consumers=frozenset(["datasource", "swarm"]),
        )
        auth = SimplePublisherAuthenticator(policies={"scrape.matched.v1": policy})

        # Should allow datasource to publish
        auth.check_publish_allowed("scrape.matched.v1", "datasource")

        # Should reject swarm
        from ai.common.bus.publisher import BusUnauthorizedPublishError

        with pytest.raises(BusUnauthorizedPublishError):
            auth.check_publish_allowed("scrape.matched.v1", "swarm")

    def test_unauthorized_publish_emits_alert_record(self) -> None:
        """Unauthorized publish attempts are recorded for alerting."""
        from ai.common.bus.publisher import (
            BusUnauthorizedPublishError,
            SimplePublisherAuthenticator,
            TopicPolicy,
        )

        policy = TopicPolicy(
            topic_name="predict.approved.v1",
            owner_component="swarm",
            consumers=frozenset(["server", "datasource"]),
        )
        auth = SimplePublisherAuthenticator(policies={"predict.approved.v1": policy})

        # Attempt unauthorized publish
        try:
            auth.check_publish_allowed("predict.approved.v1", "datasource")
        except BusUnauthorizedPublishError:
            pass

        # Alert should be recorded
        assert len(auth.unauthorized_attempts) >= 1
        alert = auth.unauthorized_attempts[0]
        assert alert["kind"] == "bus_unauthorized_publish"
        assert alert["topic"] == "predict.approved.v1"
        assert alert["attempted_by"] == "datasource"
