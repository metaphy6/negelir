"""Phase 19.9 — DPA (Data Processing Agreement) validation for restricted planes (Phase 22.3b symbol-union merge).

Validates that GDPR/KVKK/LGPD/PIPL jurisdictional requirements have corresponding
DPA entries before restricted data planes (enrichment, identity, etc.) are activated.

Phase 22.3b merge: AI version adopted (more complete); includes register_dpa_entry,
clear_dpa_registry, and _DPA_REGISTRY internal state management.
"""
from __future__ import annotations

from typing import Optional, Dict


# Registry of jurisdictions and their DPA requirements
_DPA_REGISTRY: Dict[str, Optional[str]] = {}


def validate_dpa_for_jurisdiction(league_id: str, jurisdiction: str) -> bool:
    """Validate that a jurisdiction has a valid DPA entry.
    
    Args:
        league_id: The league identifier.
        jurisdiction: Jurisdiction code (gdpr, kvkk, lgpd, pipl, etc.).
        
    Returns:
        True if DPA is documented, False otherwise.
    """
    # Check if DPA entry exists for this league+jurisdiction
    key = f"{league_id}:{jurisdiction}"
    return key in _DPA_REGISTRY


def can_enable_restricted_planes(
    league_id: str,
    jurisdiction: str = None,
    dpa_entered: bool = False,
) -> bool:
    """Check if restricted data planes can be enabled.
    
    Restricted planes require documented DPA coverage before activation.
    
    Args:
        league_id: The league identifier.
        jurisdiction: Jurisdiction (optional, defaults to GDPR if None).
        dpa_entered: Boolean flag indicating DPA presence.
        
    Returns:
        True if DPA requirement is satisfied, False otherwise.
    """
    # Simple case: if dpa_entered is explicitly True, allow it
    if dpa_entered:
        return True
    
    # Otherwise, check registry
    jurisdiction = jurisdiction or "gdpr"
    return validate_dpa_for_jurisdiction(league_id, jurisdiction)


def register_dpa_entry(league_id: str, jurisdiction: str, dpa_reference: str) -> None:
    """Register a DPA entry for a league+jurisdiction combination.
    
    Args:
        league_id: The league identifier.
        jurisdiction: Jurisdiction code.
        dpa_reference: Reference to the DPA document (e.g., doc ID, URL, etc.).
    """
    key = f"{league_id}:{jurisdiction}"
    _DPA_REGISTRY[key] = dpa_reference


def clear_dpa_registry() -> None:
    """Clear the DPA registry (for testing only)."""
    _DPA_REGISTRY.clear()
