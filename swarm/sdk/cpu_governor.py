"""
Phase 11.3 — CPU compute governor: thread-budget owner for all CPU-bound agents on a host.

The governor is the peer of the GPU arbiter (§11.2). It owns all thread-pool environment
variables (OMP_NUM_THREADS, MKL_NUM_THREADS, OPENBLAS_NUM_THREADS, TORCH_NUM_THREADS,
XGBOOST_NUM_THREADS, RAYON_NUM_THREADS, TOKENIZERS_PARALLELISM) for every agent on the
host. This prevents oversubscription, which is the #1 cause of CPU-tier latency regressions.

Key responsibilities (per §11.3):
  - Single thread-budget owner per host (claims before model load)
  - NUMA & affinity pinning (taskset, sched_setaffinity, numactl --membind)
  - CPU frequency scaling awareness (performance vs powersave)
  - SIMD gating (AVX-512 / SVE / AVX2 / NEON wheels)
  - cgroup / container CPU limit awareness (K8s requests/limits)
  - CPU LLM backend (llama.cpp, not raw transformers)
  - Denormal handling (FTZ/DAZ flags)
  - AMX / VNNI gating (Sapphire Rapids+)
  - Hyperthreading policy (SMT siblings counted or not)
  - Fork + CUDA safety (refuse fork after CUDA init)

This stub is Phase 11 design-phase; full implementation deferred to Phase 12+.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ThreadBudgetRequest:
    """Request to claim thread budget for an agent (per §11.3 bullet 1)."""
    agent: str  # Agent name
    priority: str  # "realtime", "interactive", "batch", "training"
    min_threads: int = 1
    max_threads: int = 0  # 0 = unlimited


@dataclass
class ThreadBudgetGrant:
    """Grant of thread budget to an agent (per §11.3 bullet 1)."""
    agent: str
    num_threads: int
    numa_nodes: Optional[list[int]] = None
    cpu_affinity_mask: Optional[str] = None


class CPUGovernor:
    """
    Per-host CPU thread-budget governor.

    Owns OMP_NUM_THREADS and related env vars for all agents on the host.
    Single budget owner prevents thread-pool oversubscription.
    """

    def __init__(self, cfg):
        """
        Initialize the CPU governor.

        Args:
            cfg: Config instance with Phase 11.3 governor knobs.
        """
        self.cfg = cfg
        # TODO: Detect total physical/logical cores
        # TODO: Detect NUMA topology
        # TODO: Detect cgroup CPU limits
        # TODO: Detect CPU frequency scaling mode
        # TODO: Load SIMD fingerprint from §11.1 probe
        raise NotImplementedError("Phase 11 design-phase stub; implementation deferred to Phase 12")

    async def claim_thread_budget(self, request: ThreadBudgetRequest) -> Optional[ThreadBudgetGrant]:
        """
        Claim thread budget for an agent (§11.3 bullet 1).

        Default policy: each agent gets max(1, floor(cores_physical / active_agents)).
        Co-resident agents must claim before loading a model; oversubscription is refused.

        Args:
            request: Thread budget request.

        Returns:
            ThreadBudgetGrant if successful, None if oversubscribed.
        """
        raise NotImplementedError("Phase 11 design-phase stub; implementation deferred to Phase 12")

    async def release_thread_budget(self, agent: str) -> bool:
        """
        Release thread budget when an agent shuts down.

        Args:
            agent: Agent name.

        Returns:
            True if released, False if not claimed.
        """
        raise NotImplementedError("Phase 11 design-phase stub; implementation deferred to Phase 12")

    async def apply_numa_affinity(self, agent: str, numa_nodes: list[int]) -> bool:
        """
        Pin an agent to specific NUMA nodes via taskset / sched_setaffinity (§11.3 bullet 2).

        Binds memory with numactl --membind. Cross-node memory traffic is reported
        in telemetry (negelir_cpu_numa_remote_pct).

        Args:
            agent: Agent name (process or thread group).
            numa_nodes: List of NUMA node IDs to pin to.

        Returns:
            True if pinning succeeded.
        """
        raise NotImplementedError("Phase 11 design-phase stub; implementation deferred to Phase 12")

    async def check_cpufreq_mode(self) -> str:
        """
        Probe CPU frequency scaling mode (§11.3 bullet 3).

        Warns if mode is 'powersave' (common cloud default) — worth ~30% p95 latency.

        Returns:
            Current cpufreq mode: "performance", "powersave", "ondemand", "schedutil", etc.
        """
        raise NotImplementedError("Phase 11 design-phase stub; implementation deferred to Phase 12")

    async def select_simd_wheel(self) -> str:
        """
        Select the correct SIMD wheel for loading (§11.3 bullet 4).

        Compares available wheels (AVX-512, SVE, AVX2, NEON, baseline) against the
        §11.1 CPU fingerprint. Mismatch → device.alert.v1{kind=simd_mismatch}.

        Returns:
            Selected SIMD level: "avx512_f", "sve", "avx2", "neon", "baseline".
        """
        raise NotImplementedError("Phase 11 design-phase stub; implementation deferred to Phase 12")

    async def get_cgroup_cpu_limit(self) -> Optional[float]:
        """
        Read cgroup CPU quota so the governor doesn't claim cores it isn't allowed (§11.3 bullet 5).

        Reads /sys/fs/cgroup/cpu.max for K8s requests/limits. Required for Phase 14.

        Returns:
            CPU limit (e.g., 2.5 cores), or None if no limit set.
        """
        raise NotImplementedError("Phase 11 design-phase stub; implementation deferred to Phase 12")

    async def set_denormal_flags(self) -> bool:
        """
        Set FTZ / DAZ flags at thread-pool init (§11.3 bullet 7).

        Flush-to-zero / denormals-are-zero flags leak from glibc and silently change
        numerics. Must be set explicitly on x86 (_MM_SET_FLUSH_ZERO_MODE) and ARM (FPCR.FZ).
        The chosen mode is recorded for parity audit.

        Returns:
            True if flags were set successfully.
        """
        raise NotImplementedError("Phase 11 design-phase stub; implementation deferred to Phase 12")

    async def enable_amx_vnni_if_available(self) -> bool:
        """
        Enable AMX / VNNI integer and bf16 GEMM kernels on Sapphire Rapids+ (§11.3 bullet 8).

        When the §11.1 fingerprint advertises amx_bf16 / amx_int8 or avx512_vnni,
        enable INT8 / bf16 paths in oneDNN and llama.cpp.

        Returns:
            True if AMX/VNNI was enabled.
        """
        raise NotImplementedError("Phase 11 design-phase stub; implementation deferred to Phase 12")

    async def spawn_safe_worker(self, fn, args, use_spawn=True) -> any:
        """
        Spawn a worker safely after CUDA init (§11.3 bullet 10).

        Refuses fork() after CUDA is initialized (contexts don't survive fork).
        Only spawn / forkserver are allowed. Returns the result once the worker completes.

        Args:
            fn: Function to run in the worker.
            args: Arguments to fn.
            use_spawn: If True, use 'spawn'; if False, use 'forkserver'.

        Returns:
            Result of fn(*args).
        """
        raise NotImplementedError("Phase 11 design-phase stub; implementation deferred to Phase 12")
