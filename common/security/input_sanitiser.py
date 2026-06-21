"""Phase 19.9 — Input sanitiser for catalog fields.

Blocks injection attacks (XSS, SQL injection, null bytes, etc.) while
remaining idempotent on clean input.
"""
from __future__ import annotations

import re


class SanitationError(Exception):
    """Raised when input contains dangerous patterns."""
    pass


class SSRFRiskError(Exception):
    """Raised when a URL poses an SSRF risk."""
    pass


# Patterns that indicate injection attacks
_DANGEROUS_PATTERNS = [
    r'<script|</script',  # Script tags
    r'--\s*;|;\s*DROP',   # SQL injection patterns
    r'[\x00]',            # Null bytes
    r'UNION.*SELECT',     # SQL UNION injection
    r'exec\s*\(|eval\s*\(',  # Code execution
]

# Mock/test hostnames that are safe for scraping
_SAFE_MOCK_HOSTNAMES = {
    'mackolik.local',
    'nesine.local',
    'tff.local',
    'openfootball.local',
    'localhost',
    '127.0.0.1',
}

_COMPILED_PATTERNS = [re.compile(pattern, re.IGNORECASE) for pattern in _DANGEROUS_PATTERNS]


def sanitise_catalog_field(value: str) -> str:
    """Sanitise a catalog field value.
    
    Blocks dangerous patterns (injection attacks) while passing through
    normal strings and special characters like Turkish letters.
    
    Args:
        value: The input string.
        
    Returns:
        The sanitised string (same as input if clean).
        
    Raises:
        SanitationError: If dangerous patterns are detected.
    """
    # Check for dangerous patterns
    for pattern in _COMPILED_PATTERNS:
        if pattern.search(value):
            raise SanitationError(f"Dangerous pattern detected: {value!r}")
    
    # Return unchanged (idempotent on clean input)
    return value


def sanitise_source_url(url: str) -> str:
    """Sanitise a source URL to prevent SSRF attacks.
    
    Only allows mock/test hostnames in non-production environment.
    
    Args:
        url: The source URL.
        
    Returns:
        The URL if safe.
        
    Raises:
        SSRFRiskError: If the URL poses an SSRF risk.
    """
    # Extract hostname from URL
    try:
        import urllib.parse
        parsed = urllib.parse.urlparse(url)
        hostname = parsed.hostname or parsed.netloc
    except Exception:
        raise SSRFRiskError(f"Invalid URL: {url}")
    
    # Check if hostname is in safe list
    if hostname not in _SAFE_MOCK_HOSTNAMES:
        raise SSRFRiskError(f"SSRF risk: hostname '{hostname}' not in safe list")
    
    return url
