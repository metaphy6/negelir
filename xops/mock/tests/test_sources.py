"""Tests for the source registry — pure data, smoke checks."""

from __future__ import annotations

import re

import pytest

from xops.mock import sources


def test_all_sources_have_unique_keys() -> None:
    keys = [s.key for s in sources.SOURCES]
    assert len(keys) == len(set(keys))


def test_all_sources_have_distinct_mock_hosts() -> None:
    hosts = [s.mock_host for s in sources.SOURCES]
    assert len(hosts) == len(set(hosts))


def test_all_mock_hosts_use_local_tld() -> None:
    for s in sources.SOURCES:
        assert s.mock_host.endswith(".local"), s.mock_host


def test_real_hosts_look_like_dns() -> None:
    pattern = re.compile(r"^[a-z0-9.-]+$")
    for s in sources.SOURCES:
        assert pattern.match(s.real_host), s.real_host


def test_targets_have_absolute_paths() -> None:
    for s in sources.SOURCES:
        for t in s.targets:
            assert t.path.startswith("/"), f"{s.key}/{t.name}: {t.path!r}"


def test_real_url_and_mock_url_share_path() -> None:
    for s in sources.SOURCES:
        for t in s.targets:
            assert s.real_url(t).endswith(t.path)
            assert s.mock_url(t).endswith(t.path)


def test_by_key_lookup() -> None:
    s = sources.by_key("mackolik")
    assert s.mock_host == "mackolik.local"
    with pytest.raises(KeyError):
        sources.by_key("does-not-exist")


def test_all_keys_matches_registry() -> None:
    assert sources.all_keys() == [s.key for s in sources.SOURCES]
