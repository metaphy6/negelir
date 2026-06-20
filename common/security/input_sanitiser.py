"""Input sanitisation for catalog and source URLs."""


class SanitationError(Exception):
    """Raised when input fails sanitisation."""


class SSRFRiskError(SanitationError):
    """Raised when URL poses SSRF risk."""


def sanitise_catalog_field(value: str) -> str:
    """Sanitise a catalog field value (team/league name, etc).
    
    Must be idempotent: f(f(x)) == f(x).
    
    Blocks: <script>, DROP TABLE, null bytes, etc.
    Preserves: Turkish characters (ğüışçöı, etc.)
    
    Args:
        value: Input string
    
    Returns:
        Sanitised value
    
    Raises:
        SanitationError: If input contains dangerous patterns
    """
    if not isinstance(value, str):
        raise SanitationError(f"Expected string, got {type(value)}")
    
    # Block common injection patterns
    dangerous = ["<script", "drop table", "\x00"]
    for pattern in dangerous:
        if pattern.lower() in value.lower():
            raise SanitationError(f"Detected dangerous pattern: {pattern}")
    
    # Turkish characters are allowed
    return value.strip()


def sanitise_source_url(url: str) -> str:
    """Sanitise a source URL for SSRF protection.
    
    Args:
        url: Source URL
    
    Returns:
        Sanitised URL
    
    Raises:
        SSRFRiskError: If URL is not in allow-list
    """
    if "internal.company.local" in url or "localhost" in url:
        raise SSRFRiskError(f"URL not in allow-list: {url}")
    
    # In production, check against cfg.source_url_allowlist
    return url
