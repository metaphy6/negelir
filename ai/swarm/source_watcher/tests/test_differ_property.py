"""Property + adversarial tests for the differ.

We use stdlib ``random`` (deterministic seed) to fuzz a few hundred
random JSON-shaped trees against three structural invariants:

1. **Identity**: ``diff_json(x, x) == []`` for all x.
2. **Symmetry of detection**: every diff in ``diff_json(a, b)`` has a
   counterpart in ``diff_json(b, a)`` (kind flips for added↔removed).
3. **Path uniqueness**: no two diffs share the same path.

Plus a pile of adversarial fixed cases: deeply nested mutations, type
flips, mass deletions, unicode keys, large integer/string deltas.
"""

from __future__ import annotations

import random
import string
from typing import Any, List, Set

import pytest

from ai.swarm.source_watcher.differ import FieldDiff, diff_json, summarize


# ── Random JSON tree generator ────────────────────────────────


def _rand_scalar(rng: random.Random) -> Any:
    return rng.choice(
        [
            rng.randint(-1000, 1000),
            rng.random(),
            "".join(rng.choices(string.ascii_lowercase, k=rng.randint(1, 6))),
            rng.choice([True, False, None]),
        ]
    )


def _rand_tree(rng: random.Random, depth: int = 0, max_depth: int = 4) -> Any:
    if depth >= max_depth:
        return _rand_scalar(rng)
    choice = rng.random()
    if choice < 0.5:
        return _rand_scalar(rng)
    if choice < 0.75:
        return [
            _rand_tree(rng, depth + 1, max_depth) for _ in range(rng.randint(0, 4))
        ]
    return {
        "".join(rng.choices(string.ascii_lowercase, k=rng.randint(1, 5))): _rand_tree(
            rng, depth + 1, max_depth
        )
        for _ in range(rng.randint(0, 4))
    }


def _mutate(rng: random.Random, value: Any, depth: int = 0) -> Any:
    if depth > 4 or rng.random() < 0.3:
        return _rand_scalar(rng)
    if isinstance(value, dict) and value:
        out = dict(value)
        key = rng.choice(list(out))
        out[key] = _mutate(rng, out[key], depth + 1)
        return out
    if isinstance(value, list) and value:
        out = list(value)
        idx = rng.randint(0, len(out) - 1)
        out[idx] = _mutate(rng, out[idx], depth + 1)
        return out
    return _rand_scalar(rng)


# ── Property tests ────────────────────────────────────────────


@pytest.mark.parametrize("seed", list(range(10)))
def test_identity_property(seed: int) -> None:
    rng = random.Random(seed)
    for _ in range(20):
        tree = _rand_tree(rng)
        assert diff_json(tree, tree) == []


@pytest.mark.parametrize("seed", list(range(10)))
def test_path_uniqueness(seed: int) -> None:
    rng = random.Random(seed)
    for _ in range(20):
        a = _rand_tree(rng)
        b = _mutate(rng, a)
        diffs = diff_json(a, b)
        paths = [d.path for d in diffs]
        assert len(paths) == len(set(paths)), f"duplicate paths: {paths}"


def _flip_kind(kind: str) -> str:
    return {"added": "removed", "removed": "added"}.get(kind, kind)


@pytest.mark.parametrize("seed", list(range(10)))
def test_symmetry_added_removed(seed: int) -> None:
    rng = random.Random(seed)
    for _ in range(20):
        a = _rand_tree(rng)
        b = _mutate(rng, a)
        forward = diff_json(a, b)
        backward = diff_json(b, a)
        assert len(forward) == len(backward)
        # Same set of paths in both directions.
        assert {d.path for d in forward} == {d.path for d in backward}
        # And every forward kind has a flipped counterpart in backward.
        f_map = {d.path: d.kind for d in forward}
        b_map = {d.path: d.kind for d in backward}
        for path, fk in f_map.items():
            assert b_map[path] == _flip_kind(fk), (
                f"asymmetry at {path}: forward={fk} backward={b_map[path]}"
            )


# ── Adversarial fixed cases ───────────────────────────────────


def test_deep_nested_change_finds_single_path() -> None:
    a = {"a": {"b": {"c": {"d": [1, 2, {"e": "old"}]}}}}
    b = {"a": {"b": {"c": {"d": [1, 2, {"e": "new"}]}}}}
    diffs = diff_json(a, b)
    assert len(diffs) == 1
    assert diffs[0].path == "$.a.b.c.d[2].e"
    assert diffs[0].kind == "changed"


def test_type_flip_int_to_string() -> None:
    diffs = diff_json({"x": 1}, {"x": "1"})
    assert len(diffs) == 1
    assert diffs[0].kind == "type_changed"


def test_dict_to_list_at_root_is_type_change() -> None:
    diffs = diff_json({"x": 1}, [1, 2, 3])
    assert diffs == [FieldDiff(path="$", kind="type_changed", old={"x": 1}, new=[1, 2, 3])]


def test_mass_addition_counts() -> None:
    a = {}
    b = {f"k{i}": i for i in range(50)}
    diffs = diff_json(a, b)
    assert len(diffs) == 50
    assert all(d.kind == "added" for d in diffs)


def test_mass_removal_counts() -> None:
    a = {f"k{i}": i for i in range(50)}
    b = {}
    diffs = diff_json(a, b)
    assert len(diffs) == 50
    assert all(d.kind == "removed" for d in diffs)


def test_list_length_change_emits_added() -> None:
    diffs = diff_json([1, 2], [1, 2, 3, 4])
    assert summarize(diffs) == {"added": 2, "removed": 0, "changed": 0, "type_changed": 0}


def test_list_shrink_emits_removed() -> None:
    diffs = diff_json([1, 2, 3], [1])
    assert summarize(diffs) == {"added": 0, "removed": 2, "changed": 0, "type_changed": 0}


def test_unicode_keys_and_values() -> None:
    a = {"takım": "Beşiktaş"}
    b = {"takım": "Galatasaray"}
    diffs = diff_json(a, b)
    assert len(diffs) == 1
    assert diffs[0].old == "Beşiktaş"
    assert diffs[0].new == "Galatasaray"


def test_null_vs_missing_distinguished() -> None:
    a = {"x": None}
    b = {}
    diffs = diff_json(a, b)
    assert len(diffs) == 1
    assert diffs[0].kind == "removed"


def test_summarize_counts_each_kind() -> None:
    diffs = [
        FieldDiff("$.a", "added", new=1),
        FieldDiff("$.b", "removed", old=2),
        FieldDiff("$.c", "changed", old=1, new=2),
        FieldDiff("$.d", "type_changed", old=1, new="x"),
        FieldDiff("$.e", "added", new=3),
    ]
    assert summarize(diffs) == {"added": 2, "removed": 1, "changed": 1, "type_changed": 1}
