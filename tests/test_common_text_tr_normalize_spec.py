from __future__ import annotations

from pathlib import Path

from ai.common.text.normalize import TR_NORMALIZE_SPEC_SHA, _load_tr_normalize_spec, _load_tr_normalize_spec_sha


def test_tr_normalize_spec_loads_and_validates() -> None:
    spec = _load_tr_normalize_spec()

    assert spec["spec_version"] == 1
    assert isinstance(spec["steps"], list)
    assert {"nfc", "strip_control", "lowercase_tr"}.issubset(set(spec["steps"]))
    assert isinstance(spec["mappings"], dict)
    assert spec["mappings"]["I"]
    assert spec["mappings"]["İ"]


def test_tr_normalize_spec_sha_matches_file_contents() -> None:
    path = Path("ai/common/text/tr_normalize_spec.json")
    assert TR_NORMALIZE_SPEC_SHA == _load_tr_normalize_spec_sha(path)
