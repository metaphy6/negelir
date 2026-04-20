"""Live parity tests: real upstream vs locally-served mock.

These tests are SKIPPED by default. They only run when the developer
sets ``RUN_LIVE_TESTS=1`` in their environment, and they assume the
mock stack (mocksrv + nginx + /etc/hosts entries) is up locally.

Workflow for a human operator:

    1. ``make hosts.install``                  # one-time, needs sudo
    2. ``make mock.ca-init && make mock.ca-trust``
    3. ``make mock.capture``                   # HUMAN-ONLY: hits real internet
    4. ``make up-mock``                        # boots mocksrv + nginx
    5. ``RUN_LIVE_TESTS=1 pytest -m live``     # runs THIS file

What we assert (per source, per target):
    * Both endpoints respond with HTTP 200.
    * Same content-type (modulo charset).
    * Same byte length within ±10% (real sites change constantly).
    * For JSON sources: both bodies parse, top-level keys match.

These thresholds are intentionally loose — strict parity is the
**captured snapshot's** job, not the live diff's.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Tuple

import pytest

from xops.mock.sources import SOURCES, CaptureTarget, Source

LIVE_ENABLED = os.environ.get("RUN_LIVE_TESTS") == "1"

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not LIVE_ENABLED,
        reason="set RUN_LIVE_TESTS=1 (and bring up the mock stack) to enable",
    ),
]


def _fetch(url: str, *, timeout: float = 20.0) -> Tuple[int, str, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "Negelir-Parity/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        body = resp.read()
        ct = resp.headers.get("content-type", "")
        return resp.status, ct, body


def _flatten() -> list:
    out = []
    for s in SOURCES:
        for t in s.targets:
            out.append((s, t))
    return out


@pytest.mark.parametrize("source,target", _flatten(), ids=lambda v: getattr(v, "key", getattr(v, "name", "?")))
def test_real_vs_mock_parity(source: Source, target: CaptureTarget) -> None:
    real_status, real_ct, real_body = _fetch(source.real_url(target))
    mock_status, mock_ct, mock_body = _fetch(source.mock_url(target))

    assert real_status == 200, f"real {source.real_url(target)} → {real_status}"
    assert mock_status == 200, f"mock {source.mock_url(target)} → {mock_status}"

    real_root = real_ct.split(";", 1)[0].strip().lower()
    mock_root = mock_ct.split(";", 1)[0].strip().lower()
    assert real_root == mock_root, f"content-type drift: real={real_ct!r} mock={mock_ct!r}"

    rl, ml = len(real_body), len(mock_body)
    if rl > 0:
        delta = abs(rl - ml) / rl
        assert delta < 0.10, (
            f"size drift {delta:.0%} for {source.key}/{target.name}: "
            f"real={rl} mock={ml} — re-run `make mock.capture`?"
        )

    if real_root == "application/json":
        real_obj = json.loads(real_body)
        mock_obj = json.loads(mock_body)
        if isinstance(real_obj, dict) and isinstance(mock_obj, dict):
            real_keys = set(real_obj.keys())
            mock_keys = set(mock_obj.keys())
            missing = real_keys - mock_keys
            assert not missing, (
                f"mock missing top-level keys {missing} for {source.key}/{target.name}"
            )
