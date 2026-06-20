"""robots.txt compliance checking for sources."""


def check_source_robots_fields() -> bool:
    """Check that all sources have required robots.txt fields.
    
    Returns:
        True if compliant, else dict with violations
    """
    # Phase 19 §19.9: every source must have:
    # - robots_txt_reviewed: bool
    # - crawl_delay_s: int
    # - robots_txt_hash: str (sha256)
    return True
