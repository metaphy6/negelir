"""Topic schema registry tests."""
from __future__ import annotations

import pytest

from swarm.sdk.schemas import known_topics, load


def test_known_topics_lists_echo() -> None:
    topics = known_topics()
    assert "echo.in" in topics
    assert "echo.out" in topics


def test_load_returns_valid_schema_object() -> None:
    schema = load("echo.in")
    assert schema["title"] == "echo.in"
    assert schema["type"] == "object"


def test_load_unknown_raises() -> None:
    with pytest.raises(FileNotFoundError):
        load("nonexistent.topic")
