"""Per-record CRC32C trailer for torn-write detection (Phase 16.2 bullet 5).

Adds a CRC32C checksum trailer to each NDJSON line to detect torn writes:
  - Last 8 hex chars after closing `}`, separated by single space
  - Optional via cfg.emitter_record_crc = on|off (default on)
  - Reader skips corrupted lines and emits feed_reader_corrupt_line_total counter

Properties (binding per Phase 16.2):
  - CRC32C: faster than SHA256, adequate for detecting corruption
  - Format: `{json_obj} deadbeef` (space-separated)
  - Optional: can be disabled for performance (cfg-controlled)
  - Per-line verification: detects torn writes without invalidating whole file
"""

import struct
from typing import Tuple, Optional

try:
    import crcmod
    # CRC-32C (Castagnoli) polynomial as used by iSCSI, ext4, etc.
    # x^32 + x^28 + x^27 + x^26 + x^23 + x^22 + x^20 + x^19 + x^18 + x^14 + x^13 + x^11 + x^10 + x^9 + x^8 + x^6 + 1
    _crc32c_fn = crcmod.mkCrcFun(0x11EDC6F41, rev=True, initCrc=0, xorOut=0xffffffff)
    HAS_CRCMOD = True
except ImportError:
    HAS_CRCMOD = False
    _crc32c_fn = None


def crc32c(data: bytes) -> int:
    """Compute CRC32C checksum of data.
    
    Args:
        data: Bytes to checksum
        
    Returns:
        32-bit CRC value
    """
    if not HAS_CRCMOD:
        # Fallback: use zlib crc32 (not ideal but better than nothing)
        import zlib
        return zlib.crc32(data) & 0xffffffff
    
    return _crc32c_fn(data) & 0xffffffff


def append_crc_trailer(line: str, enabled: bool = True) -> str:
    """Append CRC32C trailer to NDJSON line.
    
    Format: `{json_obj} deadbeef`
    
    Args:
        line: NDJSON line (with newline removed)
        enabled: Whether to add CRC (if False, return line unchanged)
        
    Returns:
        Line with CRC trailer appended
    """
    if not enabled or not line:
        return line
    
    # Compute CRC of the JSON part (before the trailer if re-checking)
    crc_val = crc32c(line.encode("utf-8"))
    crc_hex = f"{crc_val:08x}"
    
    return f"{line} {crc_hex}"


def verify_crc_trailer(line: str, enabled: bool = True) -> Tuple[bool, str]:
    """Verify CRC32C trailer on NDJSON line.
    
    Args:
        line: NDJSON line (possibly with CRC trailer)
        enabled: Whether CRC checking is enabled
        
    Returns:
        Tuple of (is_valid, clean_line)
        - is_valid: True if CRC matches (or disabled)
        - clean_line: Line with CRC trailer removed (if present)
    """
    if not enabled:
        return True, line
    
    # Try to extract CRC trailer (last 8 hex chars after space)
    parts = line.rsplit(" ", 1)
    if len(parts) != 2:
        # No trailer found; assume valid if CRC not expected
        return True, line
    
    json_part, trailer_hex = parts
    
    # Validate trailer format (8 hex chars)
    if len(trailer_hex) != 8 or not all(c in "0123456789abcdefABCDEF" for c in trailer_hex):
        return False, json_part
    
    # Compute CRC of JSON part
    expected_crc = crc32c(json_part.encode("utf-8"))
    trailer_crc = int(trailer_hex, 16)
    
    is_valid = expected_crc == trailer_crc
    return is_valid, json_part


class CRCTrailerConfig:
    """Configuration for per-record CRC32C trailers."""
    
    def __init__(self, enabled: bool = True):
        """Initialize CRC config.
        
        Args:
            enabled: Whether to add/verify CRC trailers (default True)
        """
        self.enabled = enabled
        self.total_records = 0
        self.total_corrupted = 0
    
    def append_trailer(self, line: str) -> str:
        """Append CRC trailer to line."""
        self.total_records += 1
        return append_crc_trailer(line, self.enabled)
    
    def verify_trailer(self, line: str) -> Tuple[bool, str]:
        """Verify CRC trailer on line."""
        is_valid, clean_line = verify_crc_trailer(line, self.enabled)
        if not is_valid:
            self.total_corrupted += 1
        return is_valid, clean_line
    
    def get_stats(self) -> dict:
        """Get corruption statistics."""
        return {
            "enabled": self.enabled,
            "total_records": self.total_records,
            "total_corrupted": self.total_corrupted,
            "corruption_rate": (
                self.total_corrupted / self.total_records
                if self.total_records > 0
                else 0.0
            ),
        }
