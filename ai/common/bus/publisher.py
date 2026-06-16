"""Phase 18.6 §18.6 ledger #12 — Bus topic ownership enforcement.

Every topic has an owner component. Publishing outside the owner is refused
with BusUnauthorizedPublishError and emits sec.alert.v1.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class BusUnauthorizedPublishError(Exception):
    """Raised when a component attempts to publish to a topic it doesn't own."""

    pass


@dataclass(frozen=True)
class TopicPolicy:
    """Immutable topic access policy."""

    topic_name: str
    owner_component: str
    consumers: frozenset[str]
    retention_days: int = 90
    schema_path: str | None = None


class PublisherAuthenticator(Protocol):
    """Protocol for authenticating topic publishers."""

    def check_publish_allowed(
        self, topic: str, current_component: str
    ) -> None:
        """Verify the component is allowed to publish to the topic.

        Args:
            topic: The topic being published to.
            current_component: The component attempting to publish.

        Raises:
            BusUnauthorizedPublishError: If the component is not the owner.
        """
        ...

    def emit_unauthorized_alert(
        self, topic: str, attempted_by: str, reason: str
    ) -> None:
        """Emit a security alert when an unauthorized publish is attempted.

        Args:
            topic: The topic someone tried to publish to.
            attempted_by: The component that tried.
            reason: Why it was refused.
        """
        ...


class SimplePublisherAuthenticator:
    """Concrete publisher authenticator backed by a policy dict."""

    def __init__(self, policies: dict[str, TopicPolicy] | None = None):
        """Initialize with an optional policy dict (topic_name -> policy)."""
        self.policies = policies or {}
        self.unauthorized_attempts: list[dict[str, str]] = []

    def check_publish_allowed(
        self, topic: str, current_component: str
    ) -> None:
        """Enforce: only the owner component can publish."""
        if topic not in self.policies:
            # Topic not tracked; allow (for backward compat during transition)
            return

        policy = self.policies[topic]
        if current_component != policy.owner_component:
            reason = (
                f"Only {policy.owner_component} can publish to {topic}, "
                f"but {current_component} attempted"
            )
            self.emit_unauthorized_alert(topic, current_component, reason)
            raise BusUnauthorizedPublishError(reason)

    def emit_unauthorized_alert(
        self, topic: str, attempted_by: str, reason: str
    ) -> None:
        """Record an unauthorized publish attempt (would emit sec.alert.v1 in prod)."""
        alert = {
            "kind": "bus_unauthorized_publish",
            "topic": topic,
            "attempted_by": attempted_by,
            "reason": reason,
        }
        self.unauthorized_attempts.append(alert)


# Global policy registry (populated from topics.yaml at boot)
_TOPIC_POLICIES: dict[str, TopicPolicy] = {}


def register_topic_policies(policies: dict[str, TopicPolicy]) -> None:
    """Register the canonical topic policies (from topics.yaml)."""
    global _TOPIC_POLICIES
    _TOPIC_POLICIES = policies


def get_publisher_authenticator() -> PublisherAuthenticator:
    """Get the global publisher authenticator instance."""
    if not _TOPIC_POLICIES:
        # Return a permissive authenticator if policies aren't loaded yet
        return SimplePublisherAuthenticator()
    return SimplePublisherAuthenticator(_TOPIC_POLICIES)
