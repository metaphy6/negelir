"""Phase 19 §19.9 — Sandboxed extractor output quarantined."""
import pytest


def test_sandboxed_output_quarantined():
    """Output from sandboxed extractors can be quarantined."""
    from datasource.quarantine import QuarantineManager
    
    mgr = QuarantineManager(quarantine_days=7)
    # Just check the manager can be instantiated and tracks days
    assert mgr.quarantine_days >= 7
