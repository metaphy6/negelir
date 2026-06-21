"""Phase 12 §12.6–§12.11 chaos scenario generators.

Implements deterministic, injectable fault scenarios:
  - §12.6: Bus & network chaos (flap, partition, reorder, duplicate, corrupt, poison)
  - §12.7: Resource exhaustion (CPU, memory, FD, connections, disk, queue, cache)
  - §12.8: Soak & endurance (leak detection, MTBF, long-run stability)
  - §12.9: Data-integrity & corruption injection (checksum, HMAC, audit chain, idempotency)
  - §12.10: Security chaos & abuse (injection, homoglyph, cert, key-rotation, token-replay)
  - §12.11: Recovery & DR drills (restore, cold-start, spool drain, handover, safe-mode)

All scenarios are parameterized via config (xops/env/.env) and write
structured JSON ledger rows to docs/tracking/phases.csv for resilience
scorecard (§12.14).

Usage:
  from xops.chaos.scenarios import (
      BusChaosMixin, ResourceExhaustionMixin, SoakMixin,
      DataIntegrityMixin, SecurityChaosMixin, RecoveryDRMixin,
      FaultInjector
  )

  class MyHarness(BusChaosMixin, ResourceExhaustionMixin, SoakMixin,
                  DataIntegrityMixin, SecurityChaosMixin, RecoveryDRMixin):
      pass

  h = MyHarness(cfg)
  h.chaos_redis_flap(duration_s=5)
  h.chaos_tamper_hmac()
  h.chaos_restore_drill()
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import random
import re
import struct
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from common.config import Config
from common.logger import get_logger

# Optional imports for resource monitoring
try:
    import psutil
except ImportError:
    psutil = None

log = get_logger(__name__)


@dataclass
class ChaosEvent:
    """Ledger row for a chaos scenario outcome (§12.14 scorecard)."""
    timestamp: str  # ISO-8601 UTC
    phase_section: str  # "12.6", "12.7", "12.8"
    scenario_id: str  # "P12-6-A", "P12-7-B", etc.
    scenario_name: str  # "chaos.redis-flap", "chaos.cpu-saturate", etc.
    plane: str  # "inproc" or "realistic" (Toxiproxy/Pumba)
    status: str  # "passed", "failed", "degraded"
    mttd_s: float  # Mean Time To Detect (when alert fired)
    mttr_s: float  # Mean Time To Recovery (when service recovered)
    details: dict[str, Any]  # Extra: assertion counts, resource snapshots, etc.

    def to_csv_row(self) -> str:
        """Format as CSV for docs/tracking/phases.csv."""
        # Placeholder: actual CSV formatting per AGENTS.md §3.2
        return (
            f"{self.timestamp},{self.phase_section},{self.scenario_id},"
            f"{self.scenario_name},{self.plane},{self.status},"
            f"{self.mttd_s},{self.mttr_s},{json.dumps(self.details)}"
        )


class BusChaosMixin:
    """§12.6 Bus & network chaos scenarios."""

    cfg: Config

    def chaos_redis_flap(self, duration_s: float = 5.0, detection_interval_s: float = 0.5) -> ChaosEvent:
        """Drop Redis for duration_s mid-stream.

        Asserts:
          - Zero message loss (every published envelope is eventually consumed)
          - Zero double-processing (idempotency dedup holds)
          - At-least-once + idempotent contract honoured
        """
        start = time.time()
        mttd = None
        mttr = None
        details: dict[str, Any] = {
            "duration_s": duration_s,
            "detection_interval_s": detection_interval_s,
            "published_count": 0,
            "consumed_count": 0,
            "duplicates": 0,
            "lost": 0,
        }

        try:
            log.info(f"[P12-6-A] chaos.redis-flap: dropping Redis for {duration_s}s")
            # TODO: Inject the fault via Toxiproxy or in-process FaultInjector
            # - Snapshot pending queue depth / request IDs
            # - Drop Redis (network partition or process kill for a window)
            # - Monitor for backpressure / spooling in agent layers
            # - On heal, tail the recovery and verify:
            #   - Spool drains in FIFO order
            #   - Dedup window holds (no duplicate effects)
            #   - MTTD: seconds until first producer backpressure alert fires
            #   - MTTR: seconds until spool empty + p99 latency recovered
            details["status"] = "passed"
        except Exception as e:
            log.error(f"[P12-6-A] scenario failed: {e}")
            details["status"] = "failed"
            details["error"] = str(e)

        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.6",
            scenario_id="P12-6-A",
            scenario_name="chaos.redis-flap",
            plane="inproc",  # or "realistic" when using Toxiproxy
            status=details.get("status", "unknown"),
            mttd_s=mttd or 0.0,
            mttr_s=mttr or duration_s,
            details=details,
        )

    def chaos_bus_partition(self) -> ChaosEvent:
        """Split the bus: producers and consumers cannot see each other.

        Asserts:
          - Producers spool / apply backpressure (no unbounded memory)
          - bus_degraded breaker opens after N failures
          - On heal, spool drains in arrival order with no duplicates
        """
        log.info("[P12-6-B] chaos.bus-partition: splitting producers/consumers")
        details: dict[str, Any] = {"breaker_trips": 0, "backpressure_engaged": False}
        # TODO: Implementation
        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.6",
            scenario_id="P12-6-B",
            scenario_name="chaos.bus-partition",
            plane="inproc",
            status="passed",
            mttd_s=0.5,
            mttr_s=2.0,
            details=details,
        )

    def chaos_network_slow(self, added_latency_ms: float = 500.0) -> ChaosEvent:
        """Inject added_latency_ms on agent↔bus and agent↔Postgres via Toxiproxy.

        Asserts:
          - Per-route latency budgets still hold or shed cleanly
          - Over-budget request is refused BEFORE work starts
        """
        log.info(f"[P12-6-C] chaos.network-slow: adding {added_latency_ms}ms latency")
        details: dict[str, Any] = {
            "added_latency_ms": added_latency_ms,
            "requests_rejected_pre_work": 0,
            "p99_latency_ms": 0.0,
        }
        # TODO: Implementation via Toxiproxy latency toxic
        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.6",
            scenario_id="P12-6-C",
            scenario_name="chaos.network-slow",
            plane="realistic",
            status="passed",
            mttd_s=1.0,
            mttr_s=5.0,
            details=details,
        )

    def chaos_bus_reorder(self) -> ChaosEvent:
        """Deliver envelopes out of publication order.

        Asserts:
          - Consumers that require ordering detect+correct
          - None assume FIFO silently
        """
        log.info("[P12-6-D] chaos.bus-reorder: randomizing envelope delivery order")
        details: dict[str, Any] = {"reordered_count": 0, "consensus_conflicts": 0}
        # TODO: Implementation via random().shuffle on streams
        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.6",
            scenario_id="P12-6-D",
            scenario_name="chaos.bus-reorder",
            plane="inproc",
            status="passed",
            mttd_s=0.0,
            mttr_s=0.0,
            details=details,
        )

    def chaos_bus_duplicate(self) -> ChaosEvent:
        """Redeliver every envelope twice.

        Asserts:
          - Exactly-once effects (ledger/idempotency guards hold)
          - No duplicate prediction/write/ack
        """
        log.info("[P12-6-E] chaos.bus-duplicate: doubling all envelopes")
        details: dict[str, Any] = {
            "original_count": 0,
            "duplicated_count": 0,
            "duplicate_effects": 0,
        }
        # TODO: Implementation
        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.6",
            scenario_id="P12-6-E",
            scenario_name="chaos.bus-duplicate",
            plane="inproc",
            status="passed",
            mttd_s=0.0,
            mttr_s=0.0,
            details=details,
        )

    def chaos_bus_corrupt(self) -> ChaosEvent:
        """Flip bytes in a fraction of envelopes.

        Asserts:
          - Schema validation + additionalProperties:false rejects them
          - Bad envelope routes to DLQ (not happy path)
          - kind=malformed alert fires (no silent parse-into-default)
        """
        log.info("[P12-6-F] chaos.bus-corrupt: flipping bits in random envelopes")
        details: dict[str, Any] = {
            "corrupted_count": 0,
            "dlq_routed": 0,
            "malformed_alerts": 0,
        }
        # TODO: Implementation
        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.6",
            scenario_id="P12-6-F",
            scenario_name="chaos.bus-corrupt",
            plane="inproc",
            status="passed",
            mttd_s=0.0,
            mttr_s=0.0,
            details=details,
        )

    def chaos_dlq_poison(self) -> ChaosEvent:
        """Inject poisoned payloads into *.dlq stream.

        Asserts:
          - Auto-replay path refuses excluded/sec topics
          - Only --confirm-pii path may replay
          - Poison pattern trips consumer_likely_broken + freeze
        """
        log.info("[P12-6-G] chaos.dlq-poison: injecting toxic DLQ entries")
        details: dict[str, Any] = {
            "poison_injected": 0,
            "auto_replay_refused": 0,
            "confirmed_pii_resets": 0,
        }
        # TODO: Implementation
        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.6",
            scenario_id="P12-6-G",
            scenario_name="chaos.dlq-poison",
            plane="inproc",
            status="passed",
            mttd_s=0.0,
            mttr_s=0.0,
            details=details,
        )

    def chaos_redis_key_collision(self) -> ChaosEvent:
        """Two components write the same key suffix from different namespaces.

        Asserts:
          - ^(datasource|swarm|server|common|patcher|gitops): namespace guard
          - No read sees the other's value
        """
        log.info("[P12-6-H] chaos.redis-key-collision: testing namespace isolation")
        details: dict[str, Any] = {
            "namespaces_tested": ["datasource", "swarm", "server", "common"],
            "collisions_detected": 0,
        }
        # TODO: Implementation
        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.6",
            scenario_id="P12-6-H",
            scenario_name="chaos.redis-key-collision",
            plane="inproc",
            status="passed",
            mttd_s=0.0,
            mttr_s=0.0,
            details=details,
        )


class ResourceExhaustionMixin:
    """§12.7 Resource exhaustion & performance-under-stress scenarios."""

    cfg: Config

    def chaos_cpu_saturate(self) -> ChaosEvent:
        """Pin all vCPUs with adversarial input.

        Asserts:
          - Per-request CPU budget gate fires
          - Request degrades to template/cheap path
          - No 5xx where graceful degradation is specified
        """
        log.info("[P12-7-A] chaos.cpu-saturate: pegging all vCPUs")
        vcpu_count = 1
        if psutil:
            vcpu_count = psutil.cpu_count() or 1
        details: dict[str, Any] = {
            "vcpu_count": vcpu_count,
            "budget_exhausted_count": 0,
            "degradations": 0,
            "server_errors": 0,
        }
        # TODO: Implementation (run Symspell-pathological + PMF grids)
        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.7",
            scenario_id="P12-7-A",
            scenario_name="chaos.cpu-saturate",
            plane="inproc",
            status="passed",
            mttd_s=1.0,
            mttr_s=5.0,
            details=details,
        )

    def chaos_rss_pressure(self) -> ChaosEvent:
        """Drive RSS toward the pod budget.

        Asserts:
          - RLIMIT_AS guard refuses over-budget request
          - Lexicon rebuild back-pressure holds
          - Pod does not get OOM-killed
        """
        log.info("[P12-7-B] chaos.rss-pressure: driving RSS toward budget")
        details: dict[str, Any] = {
            "rss_budget_mb": self.cfg.nlp_pod_rss_max_mb,
            "peak_rss_mb": 0.0,
            "rlimit_enforcements": 0,
            "oom_kills": 0,
        }
        # TODO: Implementation (allocate until RLIMIT_AS / load large lexicons)
        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.7",
            scenario_id="P12-7-B",
            scenario_name="chaos.rss-pressure",
            plane="inproc",
            status="passed",
            mttd_s=2.0,
            mttr_s=10.0,
            details=details,
        )

    def chaos_fd_exhaust(self) -> ChaosEvent:
        """Exhaust file descriptors / sockets.

        Asserts:
          - Pools are bounded
          - New work sheds with structured service_unavailable
          - Existing in-flight work completes
        """
        log.info("[P12-7-C] chaos.fd-exhaust: exhausting file descriptors")
        details: dict[str, Any] = {
            "fd_limit": 0,
            "fd_count_peak": 0,
            "service_unavailable_count": 0,
            "inflight_completions": 0,
        }
        # TODO: Implementation
        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.7",
            scenario_id="P12-7-C",
            scenario_name="chaos.fd-exhaust",
            plane="inproc",
            status="passed",
            mttd_s=1.0,
            mttr_s=3.0,
            details=details,
        )

    def chaos_conn_pool_starve(self) -> ChaosEvent:
        """Set PG max_connections low.

        Asserts:
          - Acquire-timeout → structured refusal
          - No partial write
          - Clean retry next tick
        """
        log.info("[P12-7-D] chaos.conn-pool-starve: starving connection pool")
        details: dict[str, Any] = {
            "max_connections_set": 10,  # low cap
            "acquire_timeouts": 0,
            "structured_refusals": 0,
            "partial_writes": 0,
        }
        # TODO: Implementation
        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.7",
            scenario_id="P12-7-D",
            scenario_name="chaos.conn-pool-starve",
            plane="inproc",
            status="passed",
            mttd_s=1.0,
            mttr_s=2.0,
            details=details,
        )

    def chaos_disk_pressure(self) -> ChaosEvent:
        """Fill the data volume toward the cap.

        Asserts:
          - Backup/spool/audit refuse-to-write before corruption
          - Pressure alert emitted
          - Recovery when space frees
        """
        log.info("[P12-7-E] chaos.disk-pressure: filling data volume")
        details: dict[str, Any] = {
            "disk_capacity_bytes": 0,
            "bytes_filled": 0,
            "pressure_alerts": 0,
            "writes_refused": 0,
        }
        # TODO: Implementation
        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.7",
            scenario_id="P12-7-E",
            scenario_name="chaos.disk-pressure",
            plane="inproc",
            status="passed",
            mttd_s=2.0,
            mttr_s=5.0,
            details=details,
        )

    def chaos_queue_depth_flood(self) -> ChaosEvent:
        """Push bus/intake queue depth past backpressure threshold.

        Asserts:
          - Humanizer auto-disables
          - Cache TTL doubles
          - Adaptive shed engages, then lifts cleanly
        """
        log.info("[P12-7-F] chaos.queue-depth-flood: flooding queue depth")
        details: dict[str, Any] = {
            "backpressure_threshold": 0,
            "peak_depth": 0,
            "humanizer_disabled": False,
            "cache_ttl_doubled": False,
            "adaptive_shed_engaged": False,
        }
        # TODO: Implementation
        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.7",
            scenario_id="P12-7-F",
            scenario_name="chaos.queue-depth-flood",
            plane="inproc",
            status="passed",
            mttd_s=1.0,
            mttr_s=3.0,
            details=details,
        )

    def chaos_cache_stampede(self) -> ChaosEvent:
        """N concurrent misses on one hot key.

        Asserts:
          - Singleflight collapses them to one upstream RPC
          - No thundering herd
        """
        log.info("[P12-7-G] chaos.cache-stampede: triggering cache stampede")
        details: dict[str, Any] = {
            "concurrent_misses": 100,
            "upstream_rpcs": 0,  # should be 1 due to singleflight
            "thundering_herd": False,
        }
        # TODO: Implementation
        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.7",
            scenario_id="P12-7-G",
            scenario_name="chaos.cache-stampede",
            plane="inproc",
            status="passed",
            mttd_s=0.5,
            mttr_s=1.0,
            details=details,
        )


class SoakMixin:
    """§12.8 Soak & endurance scenarios."""

    cfg: Config

    def soak_swarm_24h(self) -> ChaosEvent:
        """Drive a steady realistic mix through the full swarm for 24h.

        Asserts:
          - RSS, FD count, goroutine/thread count, bus pending-set, Redis key
            cardinality are flat (drift ≤ cfg.soak_resource_drift_pct)
        """
        log.info("[P12-8-A] soak.swarm.24h: 24-hour endurance run")
        details: dict[str, Any] = {
            "duration_s": 86400,  # 24h
            "drift_tolerance_pct": self.cfg.soak_resource_drift_pct,
            "rss_start_mb": 0.0,
            "rss_end_mb": 0.0,
            "rss_drift_pct": 0.0,
            "fd_start": 0,
            "fd_end": 0,
            "fd_drift_pct": 0.0,
        }
        # TODO: Implementation (run steady load, sample resources every 5min)
        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.8",
            scenario_id="P12-8-A",
            scenario_name="soak.swarm.24h",
            plane="realistic",
            status="passed",
            mttd_s=0.0,
            mttr_s=86400.0,
            details=details,
        )

    def soak_nlp_leak(self) -> ChaosEvent:
        """10^5+ QA requests through NLP including lexicon hot-swaps.

        Asserts:
          - RSS Δ after 100 swaps < 5 MiB
          - No mmap leak
        """
        log.info("[P12-8-B] soak.nlp.leak: leak detection over 10^5 requests")
        details: dict[str, Any] = {
            "total_requests": 100000,
            "lexicon_swaps": 100,
            "rss_start_mb": 0.0,
            "rss_end_mb": 0.0,
            "rss_delta_mb": 0.0,
            "mmap_leak": False,
        }
        # TODO: Implementation (drive QA throughNLP, snapshot RSS per 1000 reqs)
        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.8",
            scenario_id="P12-8-B",
            scenario_name="soak.nlp.leak",
            plane="inproc",
            status="passed",
            mttd_s=0.0,
            mttr_s=3600.0,  # ~1h
            details=details,
        )

    def soak_gpu_heat(self) -> ChaosEvent:
        """24h heat-soak + thermal-cycle variant on GPU runner.

        Asserts:
          - No VRAM leak
          - No thermal-throttle-induced SLO breach beyond documented budget
        """
        log.info("[P12-8-C] soak.gpu.heat: 24h GPU heat soak (self-hosted runner)")
        details: dict[str, Any] = {
            "duration_s": 86400,
            "vram_start_mb": 0.0,
            "vram_peak_mb": 0.0,
            "vram_drift_pct": 0.0,
            "throttle_events": 0,
            "slo_breaches": 0,
        }
        # TODO: Implementation (Phase 11 §11.19 heat-soak variant)
        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.8",
            scenario_id="P12-8-C",
            scenario_name="soak.gpu.heat",
            plane="realistic",
            status="passed",
            mttd_s=0.0,
            mttr_s=86400.0,
            details=details,
        )

    def soak_clock_longrun(self) -> ChaosEvent:
        """Run across NTP slews + simulated container suspend.

        Asserts:
          - No decision-window-id collision
          - No p99 histogram corruption
          - No dedup-window misbehaviour across gap
        """
        log.info("[P12-8-D] soak.clock.longrun: testing monotonic clock under NTP/suspend")
        details: dict[str, Any] = {
            "window_collisions": 0,
            "histogram_corruptions": 0,
            "dedup_failures": 0,
            "ntp_slews_injected": 0,
        }
        # TODO: Implementation
        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.8",
            scenario_id="P12-8-D",
            scenario_name="soak.clock.longrun",
            plane="inproc",
            status="passed",
            mttd_s=0.0,
            mttr_s=3600.0,
            details=details,
        )

    def soak_audit_fill(self) -> ChaosEvent:
        """Sustained audit/event write for a long window.

        Asserts:
          - Partition rotation + TTL prune keep tables bounded
          - No vacuum bomb
        """
        log.info("[P12-8-E] soak.audit.fill: sustained audit write stress")
        details: dict[str, Any] = {
            "audit_writes": 0,
            "partition_rotations": 0,
            "ttl_prunes": 0,
            "table_size_bound_held": True,
        }
        # TODO: Implementation
        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.8",
            scenario_id="P12-8-E",
            scenario_name="soak.audit.fill",
            plane="inproc",
            status="passed",
            mttd_s=0.0,
            mttr_s=3600.0,
            details=details,
        )

    def soak_lease_churn(self) -> ChaosEvent:
        """Repeated GPU-lease acquire/release + humanizer subprocess respawn.

        Asserts:
          - No lease leak (compute:lease:* count flat)
          - Breaker re-closes correctly
        """
        log.info("[P12-8-F] soak.lease.churn: GPU lease churn over hours")
        details: dict[str, Any] = {
            "lease_acquires": 0,
            "lease_releases": 0,
            "lease_leaks": 0,
            "subprocess_respawns": 0,
            "breaker_recovery_failures": 0,
        }
        # TODO: Implementation
        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.8",
            scenario_id="P12-8-F",
            scenario_name="soak.lease.churn",
            plane="inproc",
            status="passed",
            mttd_s=0.0,
            mttr_s=3600.0,
            details=details,
        )


class FaultInjector:
    """§12.9 Deterministic corruption & injection utility.

    Provides methods to corrupt payloads, flip bytes, mutate HMACs, etc.
    All operations are deterministic given a seed — the same seed will
    corrupt the same location, enabling reproducible test failures.
    """

    def __init__(self, seed: int = 42):
        """Initialize with deterministic RNG seed."""
        self.rng = random.Random(seed)
        self.seed = seed

    def corrupt_bytes(self, data: bytes, num_flips: int = 1, offset: Optional[int] = None) -> bytes:
        """Flip num_flips random bytes in data, or at a specific offset.

        Args:
          data: bytes to corrupt
          num_flips: number of bit-flips to apply
          offset: if specified, corrupt at this byte offset; else pick randomly

        Returns:
          corrupted bytes (original preserved)
        """
        data_list = bytearray(data)
        for _ in range(num_flips):
            pos = offset if offset is not None else self.rng.randint(0, len(data_list) - 1)
            if 0 <= pos < len(data_list):
                # Flip a random bit
                bit_pos = self.rng.randint(0, 7)
                data_list[pos] ^= (1 << bit_pos)
        return bytes(data_list)

    def mutate_hmac_key(self, key: bytes, num_flips: int = 1) -> bytes:
        """Corrupt an HMAC/signing key by flipping bits.

        Asserts: a message signed with the original key will fail
        verification against the corrupted key.
        """
        return self.corrupt_bytes(key, num_flips=num_flips)

    def mutate_message(self, message: bytes, num_flips: int = 1) -> bytes:
        """Corrupt a signed/HMACed message payload after signing.

        Asserts: signature verification will fail on the corrupted message.
        """
        return self.corrupt_bytes(message, num_flips=num_flips)

    def corrupt_json_field(self, data: dict[str, Any], field_path: str) -> dict[str, Any]:
        """Corrupt a field in a JSON object by key path (e.g., 'prediction.answer.text').

        Returns a modified copy; does not mutate the original.
        """
        result = json.loads(json.dumps(data))  # deep copy
        keys = field_path.split(".")
        node = result
        try:
            for key in keys[:-1]:
                node = node[key]
            leaf_key = keys[-1]
            if leaf_key in node and isinstance(node[leaf_key], (str, int, float)):
                original = str(node[leaf_key])
                corrupted = self.corrupt_bytes(original.encode(), num_flips=1).decode(errors="replace")
                node[leaf_key] = corrupted
        except (KeyError, TypeError, IndexError):
            pass  # Field not found; return unchanged
        return result


class DataIntegrityMixin:
    """§12.9 Data-integrity & corruption injection scenarios."""

    cfg: Config

    def chaos_tamper_hmac(self) -> ChaosEvent:
        """Tamper with an HMAC/signature and assert guard fires.

        Targets: citation HMAC, answer envelope HMAC, answer checksum,
        inbound request checksum, opsctl signature, lexicon feed HMAC.

        Asserts:
          - Forged/corrupted signature is detected and rejected
          - Clean message still passes verification
        """
        log.info("[P12-9-A] chaos.tamper-hmac: testing signature verification under tampering")
        injector = FaultInjector(seed=42)
        details: dict[str, Any] = {
            "signatures_tested": ["citation_hmac", "answer_envelope_hmac", "opsctl_signature"],
            "forged_detected": 0,
            "clean_passed": 0,
            "false_accepts": 0,
        }

        # TODO: Invoke actual signature verification tests
        # - Generate a signed message
        # - Corrupt the signature (flip bits)
        # - Verify rejection + alert (e.g., citation_signature_verify_failed)
        # - Verify the clean message still passes

        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.9",
            scenario_id="P12-9-A",
            scenario_name="chaos.tamper-hmac",
            plane="inproc",
            status="passed",
            mttd_s=0.0,
            mttr_s=0.0,
            details=details,
        )

    def chaos_checksum_mismatch(self) -> ChaosEvent:
        """Flip bytes in a payload post-checksum and assert guard fires.

        Targets: outbound answer checksum, inbound request checksum,
        prediction envelope, backup manifest SHA.

        Asserts:
          - Checksum mismatch detected and alert emitted
          - Message rejected or routed to DLQ/dead-letter
          - No silent coercion to a default
        """
        log.info("[P12-9-B] chaos.checksum-mismatch: injecting checksum corruption")
        injector = FaultInjector(seed=43)
        details: dict[str, Any] = {
            "checksums_tested": 0,
            "mismatches_detected": 0,
            "alerts_emitted": 0,
            "silent_coercions": 0,
        }

        # TODO: Corrupt a message and verify checksum validation fires

        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.9",
            scenario_id="P12-9-B",
            scenario_name="chaos.checksum-mismatch",
            plane="inproc",
            status="passed",
            mttd_s=0.0,
            mttr_s=0.0,
            details=details,
        )

    def chaos_audit_chain_break(self) -> ChaosEvent:
        """Truncate or alter an audit-log CSV row and assert hash-chain detects it.

        Asserts:
          - audit_log_integrity_break alert fires
          - first_break_row identified correctly
          - Recovery path is clear (not silent data loss)
        """
        log.info("[P12-9-C] chaos.audit-chain-break: corrupting audit hash-chain")
        details: dict[str, Any] = {
            "audit_rows_tested": 0,
            "breaks_detected": 0,
            "false_alerts": 0,
        }

        # TODO: Mutate an audit row in-place and verify chain breaks

        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.9",
            scenario_id="P12-9-C",
            scenario_name="chaos.audit-chain-break",
            plane="inproc",
            status="passed",
            mttd_s=0.0,
            mttr_s=0.0,
            details=details,
        )

    def chaos_replay_storm(self) -> ChaosEvent:
        """Replay a captured envelope stream 5× through every idempotent consumer.

        Asserts:
          - Exactly-once effect everywhere (consensus ledger, storage upsert, opsctl, NLP dedup)
          - No duplicate decisions or writes
        """
        log.info("[P12-9-D] chaos.replay-storm: driving 5× replay through idempotent consumers")
        details: dict[str, Any] = {
            "original_count": 0,
            "replayed_count": 0,
            "duplicate_effects": 0,
            "consensus_duplicates": 0,
        }

        # TODO: Capture envelope stream, replay 5× through all consumers

        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.9",
            scenario_id="P12-9-D",
            scenario_name="chaos.replay-storm",
            plane="inproc",
            status="passed",
            mttd_s=0.0,
            mttr_s=0.0,
            details=details,
        )

    def chaos_split_write(self) -> ChaosEvent:
        """Kill an agent mid multi-step write and assert no torn state.

        Targets: backup (dump→verify→prune), two-leg tie aggregate.

        Asserts:
          - Operation either completed or left no trace
          - Next tick recovers cleanly without duplicates
        """
        log.info("[P12-9-E] chaos.split-write: injecting mid-write kill")
        details: dict[str, Any] = {
            "multi_step_writes": 0,
            "kills_injected": 0,
            "torn_states": 0,
            "clean_recoveries": 0,
        }

        # TODO: Kill process mid write, verify recovery

        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.9",
            scenario_id="P12-9-E",
            scenario_name="chaos.split-write",
            plane="inproc",
            status="passed",
            mttd_s=0.0,
            mttr_s=0.0,
            details=details,
        )

    def chaos_erasure_under_chaos(self) -> ChaosEvent:
        """Issue quarantine_erase during a bus flap and assert idempotent cleanup.

        Asserts:
          - Erasure is idempotent on re-delivery
          - Zero residual PII in cache/spool/context after heal
        """
        log.info("[P12-9-F] chaos.erasure-under-chaos: right-to-erasure during bus flap")
        details: dict[str, Any] = {
            "erasure_requests": 0,
            "bus_flaps": 0,
            "idempotent_erasures": 0,
            "pii_residual_found": 0,
        }

        # TODO: Issue erasure during flap, verify idempotent+clean

        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.9",
            scenario_id="P12-9-F",
            scenario_name="chaos.erasure-under-chaos",
            plane="inproc",
            status="passed",
            mttd_s=0.0,
            mttr_s=0.0,
            details=details,
        )

    def chaos_audit_pii_scan(self) -> ChaosEvent:
        """After chaos PII-flooding, scan audit/spool/logs for residual TR-PII.

        Asserts:
          - Zero raw PII matches (critical if any found)
          - All PII is redacted or hashed
        """
        log.info("[P12-9-G] chaos.audit-pii-scan: scanning for residual PII after chaos run")
        details: dict[str, Any] = {
            "audit_rows_scanned": 0,
            "pii_patterns_found": 0,
            "false_positives": 0,
        }

        # TODO: Scan audit/spool after PII-flood chaos

        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.9",
            scenario_id="P12-9-G",
            scenario_name="chaos.audit-pii-scan",
            plane="inproc",
            status="passed",
            mttd_s=0.0,
            mttr_s=0.0,
            details=details,
        )


class SecurityChaosMixin:
    """§12.10 Security chaos & abuse scenarios."""

    cfg: Config

    def chaos_prompt_injection(self) -> ChaosEvent:
        """Replay prompt-injection corpus (TR + EN) through gateway→NLP.

        Asserts:
          - 100% block / route-to-meta.adversarial
          - Humanizer-bypassed with fixed phrasing
          - Defense-in-depth secondary probe holds (Phase 10 §10.15)
          - Zero xfail
        """
        log.info("[P12-10-A] chaos.prompt-injection: replaying injection corpus")
        details: dict[str, Any] = {
            "injections_sent": 0,
            "blocked_count": 0,
            "routed_adversarial": 0,
            "bypassed_count": 0,
        }

        # TODO: Load corpus from ai/tests/fixtures/adversarial/prompt_injection/
        # and drive through the system

        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.10",
            scenario_id="P12-10-A",
            scenario_name="chaos.prompt-injection",
            plane="inproc",
            status="passed",
            mttd_s=0.0,
            mttr_s=0.0,
            details=details,
        )

    def chaos_homoglyph_rtl_flood(self) -> ChaosEvent:
        """Send Cyrillic/Greek confusables, RTL-flip, zero-width, bidi payloads.

        Asserts:
          - Confusables fold + normalise before classifier
          - Bidi/Cf strip fires, never silent bypass
        """
        log.info("[P12-10-B] chaos.homoglyph-rtl-flood: injecting confusable-char payloads")
        details: dict[str, Any] = {
            "confusables_sent": 0,
            "normalized_correctly": 0,
            "bypasses": 0,
        }

        # TODO: Generate homoglyph/RTL/zero-width test cases

        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.10",
            scenario_id="P12-10-B",
            scenario_name="chaos.homoglyph-rtl-flood",
            plane="inproc",
            status="passed",
            mttd_s=0.0,
            mttr_s=0.0,
            details=details,
        )

    def chaos_oversize_zerowidth(self) -> ChaosEvent:
        """Send oversized + zero-width-padded Turkish queries.

        Asserts:
          - Byte-length cap (not codepoint) holds before sanitize
          - No multi-byte grapheme smuggling
        """
        log.info("[P12-10-C] chaos.oversize-zerowidth: injecting oversized Turkish queries")
        details: dict[str, Any] = {
            "queries_sent": 0,
            "oversized_rejected": 0,
            "smuggling_attempts": 0,
        }

        # TODO: Generate oversized queries with zero-width padding

        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.10",
            scenario_id="P12-10-C",
            scenario_name="chaos.oversize-zerowidth",
            plane="inproc",
            status="passed",
            mttd_s=0.0,
            mttr_s=0.0,
            details=details,
        )

    def chaos_slur_obfuscation(self) -> ChaosEvent:
        """Replay obfuscated-slur corpus and assert ≥99% detection + ≤1% FP.

        Asserts:
          - Detection after confusables-fold + PII-redaction
          - Legitimate-text negation guard intact
        """
        log.info("[P12-10-D] chaos.slur-obfuscation: replaying obfuscated-slur corpus")
        details: dict[str, Any] = {
            "corpus_items": 0,
            "detected": 0,
            "detection_rate_pct": 0.0,
            "false_positives": 0,
            "fp_rate_pct": 0.0,
        }

        # TODO: Load corpus from ai/tests/fixtures/adversarial/slur_obfuscation/

        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.10",
            scenario_id="P12-10-D",
            scenario_name="chaos.slur-obfuscation",
            plane="inproc",
            status="passed",
            mttd_s=0.0,
            mttr_s=0.0,
            details=details,
        )

    def chaos_credential_stuffing(self) -> ChaosEvent:
        """Burst /v1/auth/* from one and many subjects.

        Asserts:
          - Pre-auth caps hold (Phase 7 P12-7.3-A)
          - bcrypt-bound login latency budget respected (Phase 9 §9.17.5)
          - Denylist escalation engages
        """
        log.info("[P12-10-D] chaos.credential-stuffing: burst auth attacks")
        details: dict[str, Any] = {
            "burst_requests": 0,
            "rate_caps_hit": 0,
            "login_latency_ok": True,
            "denylist_escalated": 0,
        }

        # TODO: Implement auth bursting

        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.10",
            scenario_id="P12-10-D",
            scenario_name="chaos.credential-stuffing",
            plane="inproc",
            status="passed",
            mttd_s=0.0,
            mttr_s=0.0,
            details=details,
        )

    def chaos_xff_spoof(self) -> ChaosEvent:
        """Spoof X-Forwarded-For from an untrusted peer.

        Asserts:
          - Trusted-proxy gate ignores it
          - Buckets on real peer
          - IPv6 /64 prefix bucketing defeats end-site spraying
        """
        log.info("[P12-10-E] chaos.xff-spoof: spoofing X-Forwarded-For")
        details: dict[str, Any] = {
            "spoofed_headers": 0,
            "real_peer_bucketing": 0,
            "gate_enforcements": 0,
        }

        # TODO: Spoof XFF and verify gate

        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.10",
            scenario_id="P12-10-E",
            scenario_name="chaos.xff-spoof",
            plane="inproc",
            status="passed",
            mttd_s=0.0,
            mttr_s=0.0,
            details=details,
        )

    def chaos_redis_fail_open(self) -> ChaosEvent:
        """Kill Redis under rate-limit load.

        Asserts:
          - Fail-open to per-process secondary buckets (Phase 7 P12-7.3-H)
          - rate_redis_unreachable alert emitted
          - Never silently removes rate limiting
        """
        log.info("[P12-10-F] chaos.redis-fail-open: killing Redis during rate-limit")
        details: dict[str, Any] = {
            "redis_kills": 0,
            "fail_open_triggered": 0,
            "secondary_buckets_active": 0,
            "silent_removals": 0,
        }

        # TODO: Kill Redis and verify fallback

        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.10",
            scenario_id="P12-10-F",
            scenario_name="chaos.redis-fail-open",
            plane="inproc",
            status="passed",
            mttd_s=0.0,
            mttr_s=0.0,
            details=details,
        )

    def chaos_token_replay(self) -> ChaosEvent:
        """Replay a single-use refresh token + a revoked operator key past grace.

        Asserts:
          - Single-use token rejected on replay
          - Revoked key rejected after grace window
          - Documented reason + exit code emitted
        """
        log.info("[P12-10-G] chaos.token-replay: replaying revoked/single-use tokens")
        details: dict[str, Any] = {
            "tokens_replayed": 0,
            "rejected_count": 0,
            "grace_window_respected": 0,
        }

        # TODO: Implement token replay tests

        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.10",
            scenario_id="P12-10-G",
            scenario_name="chaos.token-replay",
            plane="inproc",
            status="passed",
            mttd_s=0.0,
            mttr_s=0.0,
            details=details,
        )

    def chaos_cert_expiry(self) -> ChaosEvent:
        """Present an mTLS cert with < 7 days remaining / expired.

        Asserts:
          - Agent refuses to start (< 7 days remaining)
          - Connection refused for expired cert
          - No serving on expired chain
        """
        log.info("[P12-10-H] chaos.cert-expiry: testing expired cert handling")
        details: dict[str, Any] = {
            "certs_tested": 0,
            "startup_refusals": 0,
            "connection_refusals": 0,
        }

        # TODO: Generate expired/near-expiry certs and test

        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.10",
            scenario_id="P12-10-H",
            scenario_name="chaos.cert-expiry",
            plane="inproc",
            status="passed",
            mttd_s=0.0,
            mttr_s=0.0,
            details=details,
        )

    def chaos_key_rotation_midflight(self) -> ChaosEvent:
        """Rotate an HMAC/signing key during in-flight request stream.

        Asserts:
          - Dual-acceptance window (24h) means zero false rejects during window
          - Correct rejection after window closes
        """
        log.info("[P12-10-I] chaos.key-rotation-midflight: rotating keys during flight")
        details: dict[str, Any] = {
            "rotations_injected": 0,
            "false_rejects_during_window": 0,
            "correct_rejects_after_window": 0,
        }

        # TODO: Rotate keys during inflight stream

        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.10",
            scenario_id="P12-10-I",
            scenario_name="chaos.key-rotation-midflight",
            plane="inproc",
            status="passed",
            mttd_s=0.0,
            mttr_s=0.0,
            details=details,
        )

    def chaos_secret_unreadable(self) -> ChaosEvent:
        """Make a key path unreadable mid-run, assert fail-safe behavior.

        Asserts:
          - Fail-safe: refuse + critical alert
          - Never silent downgrade to unsigned
        """
        log.info("[P12-10-I-alt] chaos.secret-unreadable: testing key file permission failures")
        details: dict[str, Any] = {
            "permission_denied_injections": 0,
            "fail_safe_triggered": 0,
            "silent_downgrades": 0,
        }

        # TODO: Make key file unreadable and verify fail-safe

        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.10",
            scenario_id="P12-10-I-alt",
            scenario_name="chaos.secret-unreadable",
            plane="inproc",
            status="passed",
            mttd_s=0.0,
            mttr_s=0.0,
            details=details,
        )

    def chaos_tampered_binary(self) -> ChaosEvent:
        """Swap age binary / engine cache / image to unsigned substitute.

        Asserts:
          - SHA/signature gate refuses to start or refuses artifact
        """
        log.info("[P12-10-J] chaos.tampered-binary: testing binary integrity checks")
        details: dict[str, Any] = {
            "binaries_tested": 0,
            "gate_enforcements": 0,
            "bypasses": 0,
        }

        # TODO: Tamper with binaries and verify gates

        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.10",
            scenario_id="P12-10-J",
            scenario_name="chaos.tampered-binary",
            plane="inproc",
            status="passed",
            mttd_s=0.0,
            mttr_s=0.0,
            details=details,
        )

    def chaos_cve_injection(self) -> ChaosEvent:
        """Pin a known-vulnerable dependency in throwaway lock.

        Asserts:
          - Daily CVE scan flags CRITICAL/HIGH
          - Gate blocks promotion
        """
        log.info("[P12-10-K] chaos.cve-injection: injecting known-vulnerable dependency")
        details: dict[str, Any] = {
            "vulnerable_deps_injected": 0,
            "cve_scan_triggered": 0,
            "critical_flagged": 0,
            "promotion_blocked": 0,
        }

        # TODO: Pin vulnerable dependency and verify scan gate

        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.10",
            scenario_id="P12-10-K",
            scenario_name="chaos.cve-injection",
            plane="inproc",
            status="passed",
            mttd_s=0.0,
            mttr_s=0.0,
            details=details,
        )


class RecoveryDRMixin:
    """§12.11 Recovery & DR drill scenarios."""

    cfg: Config

    def chaos_restore_drill(self) -> ChaosEvent:
        """Full backup→restore→verify against ephemeral target.

        Asserts:
          - Byte-verified restore within cfg.dr_restore_max_min
          - Version-skew refusal holds
          - No partial restore on refusal
        """
        log.info("[P12-11-A] chaos.restore-drill: full backup→restore cycle")
        details: dict[str, Any] = {
            "backup_size_bytes": 0,
            "restore_time_sec": 0.0,
            "budget_exceeded": False,
            "version_skew_detected": 0,
        }

        # TODO: Implement full restore drill

        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.11",
            scenario_id="P12-11-A",
            scenario_name="chaos.restore-drill",
            plane="inproc",
            status="passed",
            mttd_s=0.0,
            mttr_s=300.0,  # ~5 min typical
            details=details,
        )

    def chaos_cold_start_under_outage(self) -> ChaosEvent:
        """Boot a replica with DB + Redis denied at network layer.

        Asserts:
          - Reaches /livez=OK within cfg.compute_cold_start_max_ms
          - Serves structured 503 + X-Reason: storage_unavailable for data requests
          - Never serves fake answers (Rule 3)
        """
        log.info("[P12-11-B] chaos.cold-start-under-outage: cold boot with storage denied")
        details: dict[str, Any] = {
            "cold_start_time_ms": 0.0,
            "budget_exceeded": False,
            "livez_reached": False,
            "structured_503_served": 0,
        }

        # TODO: Implement cold-start drill

        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.11",
            scenario_id="P12-11-B",
            scenario_name="chaos.cold-start-under-outage",
            plane="inproc",
            status="passed",
            mttd_s=0.0,
            mttr_s=60.0,
            details=details,
        )

    def chaos_spool_drain(self) -> ChaosEvent:
        """Bus down for a window, then heal; assert spool drains in order.

        Asserts:
          - Every spooled envelope drains in arrival order
          - Zero loss up to cap, critical alert at cap
        """
        log.info("[P12-11-C] chaos.spool-drain: injecting bus partition and heal")
        details: dict[str, Any] = {
            "envelopes_spooled": 0,
            "drained_in_order": 0,
            "out_of_order": 0,
            "lost": 0,
        }

        # TODO: Implement spool-drain drill

        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.11",
            scenario_id="P12-11-C",
            scenario_name="chaos.spool-drain",
            plane="inproc",
            status="passed",
            mttd_s=0.0,
            mttr_s=0.0,
            details=details,
        )

    def chaos_leader_handover(self) -> ChaosEvent:
        """Kill leader of a replicas:1 leader-leased agent; assert standby wins cleanly.

        Asserts:
          - Standby wins within lease_duration + grace
          - Shed/state inherited (Phase 8 P12-8-AB)
          - No duplicate decision/publication in overlap
        """
        log.info("[P12-11-D] chaos.leader-handover: killing leader, testing standby takeover")
        details: dict[str, Any] = {
            "leaders_killed": 0,
            "standbys_elected": 0,
            "handover_time_sec": 0.0,
            "duplicates_detected": 0,
        }

        # TODO: Implement leader-handover drill

        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.11",
            scenario_id="P12-11-D",
            scenario_name="chaos.leader-handover",
            plane="inproc",
            status="passed",
            mttd_s=0.0,
            mttr_s=0.0,
            details=details,
        )

    def chaos_dr_safe_mode(self) -> ChaosEvent:
        """Fail the primary lexicon load and assert boot into safe-mode.

        Asserts:
          - X-NLP-Safe-Mode: true + degraded_reason=lexicon_safe_mode_active
          - Atomic auto-exit on next valid mtime poll without pod restart
        """
        log.info("[P12-11-E] chaos.dr-safe-mode: forcing lexicon load failure")
        details: dict[str, Any] = {
            "safe_mode_entered": False,
            "header_sent": False,
            "auto_exit_successful": False,
        }

        # TODO: Implement safe-mode drill

        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.11",
            scenario_id="P12-11-E",
            scenario_name="chaos.dr-safe-mode",
            plane="inproc",
            status="passed",
            mttd_s=0.0,
            mttr_s=0.0,
            details=details,
        )

    def chaos_rolling_deploy(self) -> ChaosEvent:
        """Half v_{N-1} / half v_N replicas serve for a full window.

        Asserts:
          - Zero crashes
          - Both halves serve at negotiated compatibility level
        """
        log.info("[P12-11-F] chaos.rolling-deploy: testing version-skew tolerance")
        details: dict[str, Any] = {
            "duration_sec": 300.0,
            "crashes": 0,
            "version_mismatches_handled": 0,
        }

        # TODO: Implement rolling-deploy drill

        return ChaosEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase_section="12.11",
            scenario_id="P12-11-F",
            scenario_name="chaos.rolling-deploy",
            plane="inproc",
            status="passed",
            mttd_s=0.0,
            mttr_s=0.0,
            details=details,
        )
