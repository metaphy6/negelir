"""Backup scope management."""


def get_backup_scope():
    """Get list of backup scope items."""
    # Phase 19 §19.10: backup includes:
    # - onboarding_bundle.yaml
    # - source_discovery_report.yaml
    # - batch_readiness_report.yaml
    return [
        "league_catalog.yaml",
        "onboarding_bundle.yaml",
        "source_discovery_report.yaml",
        "batch_readiness_report.yaml",
    ]
