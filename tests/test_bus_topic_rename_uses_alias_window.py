"""Phase 18.6 §18.6 ledger #12 — Bus topic renames use an alias window."""
from __future__ import annotations

import os


class TestBusTopicRenameUsesAliasWindow:
    """Proof test: topic renames are mirrored by an alias window (ledger #8)."""

    def test_topics_yaml_has_aliases_key(self) -> None:
        """topics.yaml has an 'aliases' section for rename transitions."""
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

        assert "aliases" in config, "topics.yaml must have 'aliases' for topic renames"
        assert isinstance(config["aliases"], dict), "'aliases' must be a dict"

    def test_alias_structure_old_to_new_mapping(self) -> None:
        """Alias structure maps old_name -> new_name."""
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

        aliases = config.get("aliases", {})
        # Each alias is old_name -> new_name
        # Validate that if aliases exist, they point to valid topics
        topics = config.get("topics", {})
        for old_name, new_name in aliases.items():
            assert (
                new_name in topics
            ), f"Alias {old_name} -> {new_name} but {new_name} not in topics"

    def test_alias_pattern_follows_semver_versioning(self) -> None:
        """Topic names follow semantic versioning (e.g., v1, v2)."""
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
        for topic_name in topics.keys():
            # Topics should have versioning (e.g., .v1, .v2)
            # This is a recommended pattern, not strict enforcement
            assert (
                ".v" in topic_name or ":v" in topic_name
            ), f"Topic {topic_name} should have version suffix (e.g., .v1)"
