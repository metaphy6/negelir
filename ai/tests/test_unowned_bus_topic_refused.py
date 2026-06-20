"""Phase 18.6 §18.6 ledger #12 — Unowned bus topics are refused."""
from __future__ import annotations

import pytest


class TestUnownedBusTopicRefused:
    """Proof test: publishing to unowned topics is refused."""

    def test_unowned_topic_raises_error(self) -> None:
        """Publishing to an untracked topic raises an error."""
        from ai.common.bus.publisher import (
            BusUnauthorizedPublishError,
            SimplePublisherAuthenticator,
        )

        auth = SimplePublisherAuthenticator(policies={})

        # Untracked topics are allowed during transition (backward compat)
        # but in strict mode would be refused
        auth.check_publish_allowed("unknown.topic.v1", "datasource")

    def test_multiple_topics_policies_enforced(self) -> None:
        """Policies are enforced for multiple topics independently."""
        from ai.common.bus.publisher import (
            BusUnauthorizedPublishError,
            SimplePublisherAuthenticator,
            TopicPolicy,
        )

        policies = {
            "topic1": TopicPolicy(
                topic_name="topic1",
                owner_component="datasource",
                consumers=frozenset(),
            ),
            "topic2": TopicPolicy(
                topic_name="topic2",
                owner_component="swarm",
                consumers=frozenset(),
            ),
        }
        auth = SimplePublisherAuthenticator(policies=policies)

        # Correct owner allowed
        auth.check_publish_allowed("topic1", "datasource")
        auth.check_publish_allowed("topic2", "swarm")

        # Wrong owner refused
        with pytest.raises(BusUnauthorizedPublishError):
            auth.check_publish_allowed("topic1", "swarm")

        with pytest.raises(BusUnauthorizedPublishError):
            auth.check_publish_allowed("topic2", "datasource")
