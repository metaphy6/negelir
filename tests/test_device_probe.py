import time

from model.device import _probe_main


def test_probe_includes_monotonic_and_wall_timestamps() -> None:
    res = _probe_main()
    assert "probe_ts" in res
    assert "t_mono_ns" in res
    assert isinstance(res["t_mono_ns"], int)
    assert res["t_mono_ns"] > 0
    assert "t_wall_utc" in res
    # Basic parse check for RFC-like UTC timestamp
    try:
        time.strptime(res["t_wall_utc"], "%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        raise AssertionError("t_wall_utc is not in expected UTC format")
