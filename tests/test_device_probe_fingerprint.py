import re

from model.device import _probe_main


def test_probe_has_host_compute_fingerprint() -> None:
    res = _probe_main()
    assert "host_compute_fingerprint" in res
    f = res["host_compute_fingerprint"]
    assert isinstance(f, str)
    # SHA-256 hex is 64 lowercase hex chars
    assert re.fullmatch(r"[0-9a-f]{64}", f)
