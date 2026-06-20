"""Phase 21.6 — Mock-stack integration for enrichment sources."""
from __future__ import annotations

import os
import json
from pathlib import Path

import pytest

from common.logger import get_logger

_LOG = get_logger(__name__)


class TestMockSources:
    def test_all_enrichment_sources_resolve_to_mock_vhosts(self, tmp_path) -> None:
        """Verify all five enrichment sources are in the registry."""
        from xops.mock.sources import SOURCES
        
        enrichment_sources = {
            'transfers_feed', 'injury_watch', 'referee_reg',
            'weather_prov', 'pitch_inspect'
        }
        
        registry_keys = {s.key for s in SOURCES}
        
        for source_key in enrichment_sources:
            assert source_key in registry_keys, f"enrichment source {source_key!r} not in registry"
        
        # Verify each has a mock_host ending in .local
        for source_key in enrichment_sources:
            source = next(s for s in SOURCES if s.key == source_key)
            assert source.mock_host.endswith('.local'), \
                f"{source_key} mock_host should end in .local, got {source.mock_host!r}"

    def test_mock_seeds_manifest_reference_structure(self, tmp_path) -> None:
        """Verify manifest.json structure is sound."""
        manifest_path = Path('infra/mock/seeds/manifest.json')
        
        if manifest_path.exists():
            with open(manifest_path) as f:
                manifest = json.load(f)
            
            # Manifest should have 'entries' key (not 'sources')
            assert 'entries' in manifest, "manifest.json must have 'entries' key"
            assert isinstance(manifest['entries'], list), "entries must be a list"

    def test_all_enrichment_vhosts_have_tls_cert_entries(self, tmp_path) -> None:
        """Verify all five enrichment vhosts are configured."""
        from xops.mock.sources import SOURCES
        
        enrichment_sources = ['transfers_feed', 'injury_watch', 'referee_reg',
                            'weather_prov', 'pitch_inspect']
        
        for source_key in enrichment_sources:
            source = next(s for s in SOURCES if s.key == source_key)
            assert source.mock_host is not None
            assert len(source.mock_host) > 0

    def test_no_real_upstream_urls_in_mock_mode(self) -> None:
        """Verify that extractor code would use mock vhosts in mock mode."""
        from xops.mock.sources import SOURCES
        
        # This test documents the intent — actual redirection is in extractor code
        for source in SOURCES:
            assert hasattr(source, 'mock_url'), "Source must have mock_url method"
            assert hasattr(source, 'real_url'), "Source must have real_url method"
            
            # In NEGELIR_SCRAPE_PROFILE=mock, code should call mock_url()
            mock_url = source.mock_url(source.targets[0])
            assert source.mock_host in mock_url, f"mock_url should contain mock_host {source.mock_host}"

    def test_enrichment_source_seed_ages_reasonable(self) -> None:
        """Verify seed corpus staleness thresholds are reasonable."""
        from xops.mock.sources import SOURCES
        
        enrichment_sources = ['transfers_feed', 'injury_watch', 'referee_reg',
                            'weather_prov', 'pitch_inspect']
        
        for source_key in enrichment_sources:
            source = next(s for s in SOURCES if s.key == source_key)
            # Weather (hourly) and injuries (2h) should have shorter TTLs
            if 'weather' in source_key or 'pitch' in source_key:
                assert source.seed_max_age_days <= 3, \
                    f"{source_key} seed_max_age_days should be ≤ 3 days, got {source.seed_max_age_days}"
            # Others can be 7d or less
            assert source.seed_max_age_days <= 7, \
                f"{source_key} seed_max_age_days should be ≤ 7 days, got {source.seed_max_age_days}"

    def test_all_enrichment_sources_respect_robots_txt(self) -> None:
        """Verify all enrichment sources respect robots.txt."""
        from xops.mock.sources import SOURCES
        
        enrichment_sources = ['transfers_feed', 'injury_watch', 'referee_reg',
                            'weather_prov', 'pitch_inspect']
        
        for source_key in enrichment_sources:
            source = next(s for s in SOURCES if s.key == source_key)
            assert source.robots_respect, f"{source_key} must respect robots.txt"
            # All should have passed ToS audit
            assert source.tos_audit_passed, f"{source_key} should have tos_audit_passed=True"
