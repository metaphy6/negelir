"""Phase 10 §10.21.8 — citation key rotation command tests."""
from __future__ import annotations

import stat
from pathlib import Path

from ai.common.config import cfg as _cfg
from xops.makefile.nlp import cmd_nlp_rotate_citation_key


def test_rotate_citation_key_moves_previous_and_writes_new(monkeypatch, tmp_path: Path) -> None:
    key_path = tmp_path / "predict_citation_hmac.key"
    old_key = b"old-citation-key-material"
    key_path.write_bytes(old_key)
    key_path.chmod(0o400)

    monkeypatch.setattr(_cfg, "predict_citation_hmac_key_path", str(key_path), raising=False)
    monkeypatch.setattr(_cfg, "predict_citation_hmac_key_grace_s", 86400, raising=False)

    rc = cmd_nlp_rotate_citation_key([])
    assert rc == 0

    prev_path = tmp_path / "predict_citation_hmac.key.prev"
    assert prev_path.read_bytes() == old_key
    assert key_path.read_bytes() != old_key
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o400
    assert stat.S_IMODE(prev_path.stat().st_mode) == 0o400


def test_rotate_citation_key_bootstraps_when_missing(monkeypatch, tmp_path: Path) -> None:
    key_path = tmp_path / "predict_citation_hmac.key"
    monkeypatch.setattr(_cfg, "predict_citation_hmac_key_path", str(key_path), raising=False)
    monkeypatch.setattr(_cfg, "predict_citation_hmac_key_grace_s", 10, raising=False)

    rc = cmd_nlp_rotate_citation_key([])
    assert rc == 0
    assert key_path.exists()
    assert not (tmp_path / "predict_citation_hmac.key.prev").exists()
