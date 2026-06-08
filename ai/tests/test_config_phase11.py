from common.config import Config


def test_npu_max_acc_drop_pct_default() -> None:
    cfg = Config()
    assert hasattr(cfg, "npu_max_acc_drop_pct")
    assert isinstance(cfg.npu_max_acc_drop_pct, float)
    assert cfg.npu_max_acc_drop_pct == 1.0


def test_gpu_reserve_and_psu_defaults() -> None:
    cfg = Config()
    assert hasattr(cfg, "gpu_system_reserve_mb")
    assert isinstance(cfg.gpu_system_reserve_mb, int)
    assert cfg.gpu_system_reserve_mb >= 0

    assert hasattr(cfg, "host_psu_capacity_w")
    assert isinstance(cfg.host_psu_capacity_w, int)
    # Default 0 meaning unknown
    assert cfg.host_psu_capacity_w == 0

    assert hasattr(cfg, "host_psu_safety_factor")
    assert isinstance(cfg.host_psu_safety_factor, float)
    assert 0.0 < cfg.host_psu_safety_factor <= 1.0


def test_tf32_and_allocator_knobs_exist() -> None:
    cfg = Config()
    assert hasattr(cfg, "allow_tf32")
    assert isinstance(cfg.allow_tf32, bool)

    assert hasattr(cfg, "compute_deterministic_kernels")
    assert isinstance(cfg.compute_deterministic_kernels, bool)

    assert hasattr(cfg, "cuda_alloc_conf")
    assert isinstance(cfg.cuda_alloc_conf, str)
