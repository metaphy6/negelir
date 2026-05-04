"""Local pytest fixtures for swarm-agent tests.

Phase 7 binding: Several Phase 7 tests intentionally mutate
``common.config.cfg`` knobs (``sec_input_max_len``, ``sec_burst_threshold``,
``sec_quarantine_*``, ``sec_scrape_warmup_samples``) to drive the
defense agents into edge-case behaviour without instantiating an
8 KiB payload or 100 burst events.

Without isolation, those mutations leak across tests in the same
process and a later test reading ``cfg.sec_input_max_len`` would
see whatever the previous test set, not the documented default.
This is a real foot-gun — Phase 7 is security-critical and a
silently-relaxed length cap in CI would mask a regression.

The autouse fixture below snapshots the values of every Phase 7
knob before each test and restores them after, regardless of
whether the test passed or raised. It runs ONLY for tests under
``ai/swarm/agents/tests/`` so the rest of the suite is unaffected.
"""
from __future__ import annotations

import pytest

# Phase 7 knob inventory (the §7.7 DoD list). The fixture restores
# whatever values the dataclass carried at process-start, which is
# the documented default unless the operator overrode via env var
# (in which case the env-var value is the contract for that run).
_PHASE7_KNOBS: tuple[str, ...] = (
    "sec_input_max_len",
    "sec_input_gateway_max_latency_ms",
    "sec_input_classifier_max_latency_ms",
    "sec_input_classifier_device",
    "sec_input_classifier_path",
    "sec_input_classifier_batch_enabled",
    "sec_input_classifier_batch_size",
    "sec_input_classifier_batch_window_ms",
    "sec_input_classifier_max_pending",
    "sec_input_breaker_open_s",
    "sec_input_pattern_reload_s",
    "sec_quarantine_ttl_days",
    "sec_quarantine_payload_max_bytes",
    "sec_quarantine_producer_queue_max",
    "sec_quarantine_storage_lag_alert_ms",
    "sec_scrape_size_delta_pct",
    "sec_scrape_inflate_ratio_max",
    "sec_scrape_warmup_samples",
    "sec_scrape_baseline_flush_s",
    "sec_scrape_max_pending",
    "sec_scrape_simhash_max_distance",
    "sec_scrape_dom_fingerprint_max_nodes",
    "sec_rate_pre_auth_capacity",
    "sec_rate_pre_auth_refill_per_s",
    "sec_rate_post_auth_capacity",
    "sec_rate_post_auth_refill_per_s",
    "sec_rate_bucket_idle_ttl_s",
    "sec_rate_max_subjects",
    "sec_rate_ipv4_prefix",
    "sec_rate_ipv6_prefix",
    "sec_rate_trusted_proxies",
    "sec_rate_redis_timeout_ms",
    "sec_rate_secondary_capacity",
    "sec_rate_secondary_refill_per_s",
    "sec_rate_default_cost",
    "sec_rate_eviction_rate_alert_per_s",
    "sec_rate_eviction_rate_window_s",
    "sec_burst_threshold",
    "sec_burst_window_ms",
    "sec_burst_dedup_window",
    "sec_denylist_ttl_s",
    "sec_denylist_escalation_factor",
    "sec_denylist_max_entries",
    "sec_alert_debounce_ttl_s",
    "sec_alert_critical_debounce_enabled",
    "qa_request_v1_dedup_window_s",
)


@pytest.fixture(autouse=True)
def _restore_phase7_cfg_knobs():
    """Snapshot + restore Phase 7 cfg knobs around every test in
    this directory. Runs even on failure (yield + finally semantics
    via try/finally inside the fixture's teardown).
    """
    from common import config as _cfg_mod

    snapshot = {k: getattr(_cfg_mod.cfg, k) for k in _PHASE7_KNOBS}
    try:
        yield
    finally:
        for k, v in snapshot.items():
            setattr(_cfg_mod.cfg, k, v)
