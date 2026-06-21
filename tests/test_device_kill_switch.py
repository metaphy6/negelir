import os

from model.device import apply_disable_rules, _attach_device_uuids


def make_probe_with_cuda() -> dict:
    return {
        "probe_id": "test",
        "probe_ts": 0,
        "inventory": [
            {"device_kind": "cpu", "available": True, "name": "cpu"},
            {"device_kind": "cuda", "available": True, "index": 0, "name": "cuda0"},
        ],
    }


def test_disable_gpu_env_disables_cuda(monkeypatch):
    monkeypatch.setenv("NEGELIR_DISABLE_GPU", "1")
    res = make_probe_with_cuda()
    _attach_device_uuids(res)
    apply_disable_rules(res)

    # CPU remains available, CUDA should be disabled
    cpu = next(d for d in res["inventory"] if d["device_kind"] == "cpu")
    cuda = next(d for d in res["inventory"] if d["device_kind"] == "cuda")

    assert cpu["available"] is True
    assert cuda["available"] is False
    assert cuda.get("disabled_by") == "NEGELIR_DISABLE_GPU"
    assert any(a["kind"] == "panic_cpu" for a in res.get("alerts", []))


def test_disable_device_uuid_disables_single(monkeypatch):
    res = make_probe_with_cuda()
    _attach_device_uuids(res)
    cuda = next(d for d in res["inventory"] if d["device_kind"] == "cuda")
    uid = cuda["uuid"]

    monkeypatch.setenv("NEGELIR_DISABLE_DEVICE", uid)
    apply_disable_rules(res)

    assert cuda["available"] is False
    assert cuda.get("disabled_by") == f"NEGELIR_DISABLE_DEVICE={uid}"
    assert any(a["kind"] == "panic_cpu" for a in res.get("alerts", []))
