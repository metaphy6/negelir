"""Tests for per-record CRC32C trailer (Phase 16.2 bullet 5).

Covers:
  - CRC32C computation and verification
  - Trailer format (space-separated, 8 hex chars)
  - Torn-write detection
  - Optional CRC control
  - Corruption statistics
"""

import pytest
from common.feeds.crc import (
    crc32c,
    append_crc_trailer,
    verify_crc_trailer,
    CRCTrailerConfig,
)


class TestCRC32C:
    """Tests for CRC32C computation."""

    def test_crc32c_basic(self):
        """CRC32C computes deterministic checksum."""
        data = b"test data"
        crc1 = crc32c(data)
        crc2 = crc32c(data)
        
        assert crc1 == crc2
        assert isinstance(crc1, int)
        assert 0 <= crc1 <= 0xffffffff

    def test_crc32c_different_data(self):
        """Different data produces different CRC."""
        crc1 = crc32c(b"data1")
        crc2 = crc32c(b"data2")
        
        assert crc1 != crc2

    def test_crc32c_empty(self):
        """CRC32C of empty data is deterministic."""
        crc1 = crc32c(b"")
        crc2 = crc32c(b"")
        
        assert crc1 == crc2
        assert isinstance(crc1, int)


class TestCRCTrailer:
    """Tests for CRC trailer append and verify."""

    def test_append_crc_enabled(self):
        """append_crc_trailer adds CRC when enabled."""
        line = '{"field":"value"}'
        result = append_crc_trailer(line, enabled=True)
        
        assert " " in result  # Has space separator
        parts = result.rsplit(" ", 1)
        assert len(parts) == 2
        assert parts[0] == line  # Original line unchanged
        assert len(parts[1]) == 8  # 8 hex chars
        assert all(c in "0123456789abcdef" for c in parts[1])

    def test_append_crc_disabled(self):
        """append_crc_trailer skips CRC when disabled."""
        line = '{"field":"value"}'
        result = append_crc_trailer(line, enabled=False)
        
        assert result == line
        assert " " not in result

    def test_append_crc_empty_line(self):
        """append_crc_trailer handles empty lines."""
        result = append_crc_trailer("", enabled=True)
        assert result == ""

    def test_verify_crc_valid(self):
        """verify_crc_trailer accepts valid CRC."""
        line = '{"field":"value"}'
        with_crc = append_crc_trailer(line, enabled=True)
        
        is_valid, clean = verify_crc_trailer(with_crc, enabled=True)
        
        assert is_valid is True
        assert clean == line

    def test_verify_crc_invalid(self):
        """verify_crc_trailer rejects corrupt CRC."""
        line = '{"field":"value"}'
        with_crc = append_crc_trailer(line, enabled=True)
        
        # Flip a bit in the CRC
        parts = with_crc.rsplit(" ", 1)
        crc_hex = parts[1]
        bad_crc = hex(int(crc_hex, 16) ^ 0x00000001)[2:].zfill(8)
        bad_line = f"{parts[0]} {bad_crc}"
        
        is_valid, clean = verify_crc_trailer(bad_line, enabled=True)
        
        assert is_valid is False
        assert clean == line  # Returns clean line anyway

    def test_verify_crc_disabled(self):
        """verify_crc_trailer skips verification when disabled."""
        line_with_bad_crc = '{"field":"value"} deadbeef'
        
        is_valid, clean = verify_crc_trailer(line_with_bad_crc, enabled=False)
        
        assert is_valid is True
        assert clean == line_with_bad_crc

    def test_verify_crc_no_trailer(self):
        """verify_crc_trailer handles lines without CRC."""
        line = '{"field":"value"}'
        
        is_valid, clean = verify_crc_trailer(line, enabled=True)
        
        # Returns valid but indicates no CRC found
        assert is_valid is True
        assert clean == line

    def test_verify_crc_malformed_trailer(self):
        """verify_crc_trailer rejects malformed CRC."""
        # Not enough hex chars
        line = '{"field":"value"} deadbeef1'  # 9 chars instead of 8
        
        is_valid, clean = verify_crc_trailer(line, enabled=True)
        
        assert is_valid is False

    def test_verify_crc_non_hex_trailer(self):
        """verify_crc_trailer rejects non-hex CRC."""
        line = '{"field":"value"} deadbeefg'  # g is not hex
        
        is_valid, clean = verify_crc_trailer(line, enabled=True)
        
        assert is_valid is False


class TestCRCTrailerConfig:
    """Tests for CRCTrailerConfig statistics."""

    def test_config_init_default(self):
        """CRCTrailerConfig initializes with defaults."""
        cfg = CRCTrailerConfig()
        assert cfg.enabled is True
        assert cfg.total_records == 0
        assert cfg.total_corrupted == 0

    def test_config_init_disabled(self):
        """CRCTrailerConfig can be disabled."""
        cfg = CRCTrailerConfig(enabled=False)
        assert cfg.enabled is False

    def test_config_append_trailer_tracking(self):
        """append_trailer tracks record count."""
        cfg = CRCTrailerConfig()
        
        cfg.append_trailer('{"a":"1"}')
        assert cfg.total_records == 1
        
        cfg.append_trailer('{"b":"2"}')
        assert cfg.total_records == 2

    def test_config_verify_trailer_tracking(self):
        """verify_trailer tracks corruption count."""
        cfg = CRCTrailerConfig()
        
        # Valid
        line1 = cfg.append_trailer('{"a":"1"}')
        cfg.verify_trailer(line1)
        assert cfg.total_corrupted == 0
        
        # Invalid
        bad_line = '{"b":"2"} 00000000'
        cfg.verify_trailer(bad_line)
        assert cfg.total_corrupted == 1

    def test_config_get_stats(self):
        """get_stats returns corruption metrics."""
        cfg = CRCTrailerConfig()
        
        line1 = cfg.append_trailer('{"a":"1"}')
        cfg.verify_trailer(line1)  # valid
        
        line2 = cfg.append_trailer('{"b":"2"}')
        cfg.verify_trailer(line2)  # valid
        
        stats = cfg.get_stats()
        
        assert stats["enabled"] is True
        assert stats["total_records"] == 2
        assert stats["total_corrupted"] == 0
        assert stats["corruption_rate"] == 0.0

    def test_config_get_stats_with_corruption(self):
        """get_stats reports corruption rate."""
        cfg = CRCTrailerConfig()
        
        # 2 valid
        for i in range(2):
            line = cfg.append_trailer(f'{{"n":{i}}}')
            cfg.verify_trailer(line)
        
        # 1 invalid (also tracked as a record)
        cfg.total_records += 1
        cfg.verify_trailer('{"x":"y"} badcrc')
        
        stats = cfg.get_stats()
        
        assert stats["total_records"] == 3
        assert stats["total_corrupted"] == 1
        assert abs(stats["corruption_rate"] - 1/3) < 0.01

    def test_config_get_stats_zero_records(self):
        """get_stats handles zero records gracefully."""
        cfg = CRCTrailerConfig()
        stats = cfg.get_stats()
        
        assert stats["corruption_rate"] == 0.0


class TestCRCInvariants:
    """Property-based tests for CRC invariants."""

    def test_invariant_crc_always_deterministic(self):
        """CRC of same data is always identical."""
        data = b"deterministic test data"
        crcs = [crc32c(data) for _ in range(10)]
        
        assert all(c == crcs[0] for c in crcs)

    def test_invariant_roundtrip_consistency(self):
        """Append-verify roundtrip is consistent."""
        line = '{"complex":["json","with",123,"fields"]}'
        
        # Multiple roundtrips
        for _ in range(5):
            with_crc = append_crc_trailer(line, enabled=True)
            is_valid, clean = verify_crc_trailer(with_crc, enabled=True)
            
            assert is_valid is True
            assert clean == line

    def test_invariant_disabled_crc_is_noop(self):
        """Disabled CRC is no-op."""
        line = '{"a":"b"}'
        
        # Disabled append returns original
        result1 = append_crc_trailer(line, enabled=False)
        assert result1 == line
        
        # Disabled verify returns original
        _, result2 = verify_crc_trailer(line, enabled=False)
        assert result2 == line


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
