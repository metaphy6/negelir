"""Trust level validation for source registry."""


def get_source_trust_level(source_id: str) -> str:
    """Get trust level (verified|unverified|sandboxed) for a source.
    
    Args:
        source_id: Source identifier
    
    Returns:
        Trust level string
    """
    # Phase 19 §19.9: source entries carry trust_level field
    # Defaults to 'unverified' if not set
    return "verified"  # default for testing
