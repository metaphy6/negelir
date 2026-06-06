"""Phase 10 §10.32.8 productive suffix peeling helpers."""

from .productive_suffixes import (
    ProductivePeelResult,
    load_productive_peel_no_fire_allowlist,
    load_productive_suffix_families,
    peel_productive_suffixes,
)

__all__ = [
    "ProductivePeelResult",
    "load_productive_peel_no_fire_allowlist",
    "load_productive_suffix_families",
    "peel_productive_suffixes",
]
