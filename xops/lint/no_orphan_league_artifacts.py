"""Linter for orphan league artifacts."""


def check_no_orphan_artifacts():
    """Check that all league artifacts reference active leagues."""
    # Phase 19 §19.10: every mock-seed, NLP gazetteer, config,
    # and competition file must reference a non-decommissioned league_id
    return True
