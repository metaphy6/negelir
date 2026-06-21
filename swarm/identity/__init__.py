"""
Identity resolution for cross-competition club identity normalization.

Phase 13.4 binding: anchor_resolver maintains per-club anchor sets (union of
observed name forms across sources & competitions) and merges based on cosine
similarity thresholds.
"""

from .anchor_resolver import AnchorResolver

__all__ = ["AnchorResolver"]
