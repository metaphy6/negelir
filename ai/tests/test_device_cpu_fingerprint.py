from ai.model.device import _probe_main


def test_probe_includes_cpu_fingerprint_keys() -> None:
    res = _probe_main()
    cpu = next(d for d in res.get("inventory", []) if d.get("device_kind") == "cpu")
    assert "arch" in cpu
    assert "vendor" in cpu
    assert "model_name" in cpu
    assert "cores_logical" in cpu
    assert isinstance(cpu["cores_logical"], int)
    assert "cores_physical" in cpu
    assert isinstance(cpu["cores_physical"], int)
    assert "numa_nodes" in cpu
    assert isinstance(cpu["numa_nodes"], int)
    assert "simd" in cpu
    assert isinstance(cpu["simd"], list)
