"""Phase 8 §8.6 — Detectors B (PG column drift) + C (dataclass↔schema)."""
from __future__ import annotations

from pathlib import Path

import pytest

from swarm.agents.maint import _schema_drift as _drift
from swarm.agents.maint.schema import MaintSchemaSentinel, SchemaSentinelStartupError


# ── Detector B: parser unit tests ──────────────────────────────────


def test_parse_create_table(tmp_path: Path) -> None:
    (tmp_path / "001_init.sql").write_text(
        """
        CREATE TABLE IF NOT EXISTS teams (
            uuid TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """,
        encoding="utf-8",
    )
    digest = _drift.parse_migrations_dir(tmp_path)
    assert "teams" in digest.tables
    assert digest.tables["teams"] == {"uuid", "display_name", "created_at"}
    assert "teams" not in digest.unknown_constructs


def test_parse_alter_add_column(tmp_path: Path) -> None:
    (tmp_path / "001.sql").write_text(
        "CREATE TABLE foo (id INT PRIMARY KEY);", encoding="utf-8"
    )
    (tmp_path / "002.sql").write_text(
        "ALTER TABLE foo ADD COLUMN created_at TIMESTAMPTZ;", encoding="utf-8"
    )
    digest = _drift.parse_migrations_dir(tmp_path)
    assert digest.tables["foo"] == {"id", "created_at"}


def test_parse_skips_table_constraints(tmp_path: Path) -> None:
    (tmp_path / "001.sql").write_text(
        """
        CREATE TABLE bar (
            a INT,
            b TEXT,
            CONSTRAINT bar_uniq UNIQUE (a, b),
            PRIMARY KEY (a)
        );
        """,
        encoding="utf-8",
    )
    digest = _drift.parse_migrations_dir(tmp_path)
    assert digest.tables["bar"] == {"a", "b"}


def test_parse_strips_comments(tmp_path: Path) -> None:
    (tmp_path / "001.sql").write_text(
        """
        -- a leading comment
        CREATE TABLE q (
            x INT, -- inline ignored
            /* block
               comment */
            y TEXT
        );
        """,
        encoding="utf-8",
    )
    digest = _drift.parse_migrations_dir(tmp_path)
    assert digest.tables["q"] == {"x", "y"}


def test_parse_real_migrations_dir() -> None:
    repo = Path(__file__).resolve().parents[5]
    digest = _drift.parse_migrations_dir(repo / "migrations")
    # Spot check: teams table from 001_initial.sql.
    assert "teams" in digest.tables
    assert "uuid" in digest.tables["teams"]


def test_parse_missing_dir_safe(tmp_path: Path) -> None:
    digest = _drift.parse_migrations_dir(tmp_path / "nope")
    assert digest.tables == {}


# ── Detector B: diff_columns ───────────────────────────────────────


def test_diff_columns_missing_table() -> None:
    diffs = _drift.diff_columns({"a": {"x"}}, {})
    assert ("a", "missing_table", []) in diffs


def test_diff_columns_extra_table() -> None:
    diffs = _drift.diff_columns({}, {"b": {"y"}})
    assert ("b", "extra_table", []) in diffs


def test_diff_columns_missing_and_extra_columns() -> None:
    diffs = _drift.diff_columns({"t": {"a", "b"}}, {"t": {"a", "c"}})
    assert ("t", "missing_columns", ["b"]) in diffs
    assert ("t", "extra_columns", ["c"]) in diffs


def test_diff_columns_no_drift() -> None:
    assert _drift.diff_columns({"t": {"x"}}, {"t": {"x"}}) == []


# ── Detector B: agent integration ──────────────────────────────────


def _make_sentinel():
    clock = {"t": 0.0}

    def mono():
        return clock["t"]

    s = MaintSchemaSentinel(clock_mono=mono)
    return s, clock


def test_detect_b_emits_drift(tmp_path: Path) -> None:
    (tmp_path / "001.sql").write_text(
        "CREATE TABLE foo (a INT, b TEXT);", encoding="utf-8"
    )
    s, clock = _make_sentinel()
    msgs = s.detect_b(
        fetch_columns=lambda: {"foo": {"a"}, "bar": {"x"}},
        migrations_dir=tmp_path,
    )
    targets = sorted((m.payload["target"], m.payload["drift_kind"]) for m in msgs)
    assert ("bar", "extra_table") in targets
    assert ("foo", "missing_columns") in targets
    for m in msgs:
        assert m.payload["detector"] == "B"
        assert m.payload["severity"] == "warn"
        assert m.payload["parser_uncertain"] is False


def test_detect_b_throttle(tmp_path: Path) -> None:
    (tmp_path / "001.sql").write_text(
        "CREATE TABLE foo (a INT);", encoding="utf-8"
    )
    s, clock = _make_sentinel()
    a = s.detect_b(fetch_columns=lambda: {}, migrations_dir=tmp_path)
    assert len(a) == 1
    clock["t"] += 10  # well below default 3600
    b = s.detect_b(fetch_columns=lambda: {}, migrations_dir=tmp_path)
    assert b == []
    c = s.detect_b(fetch_columns=lambda: {}, migrations_dir=tmp_path,
                   force=True)
    assert len(c) == 1


def test_detect_b_no_drift_emits_nothing(tmp_path: Path) -> None:
    (tmp_path / "001.sql").write_text(
        "CREATE TABLE foo (a INT);", encoding="utf-8"
    )
    s, _ = _make_sentinel()
    out = s.detect_b(fetch_columns=lambda: {"foo": {"a"}},
                     migrations_dir=tmp_path)
    assert out == []


def test_detect_b_fetch_failure_swallowed(tmp_path: Path) -> None:
    (tmp_path / "001.sql").write_text(
        "CREATE TABLE foo (a INT);", encoding="utf-8"
    )
    s, _ = _make_sentinel()

    def boom():
        raise RuntimeError("pg down")

    out = s.detect_b(fetch_columns=boom, migrations_dir=tmp_path)
    assert out == []  # never crashes the producer


def test_detect_b_uncertain_parser_downgrades_severity(tmp_path: Path) -> None:
    # Garbled CREATE TABLE: missing close paren so the table lands
    # in unknown_constructs.
    (tmp_path / "001.sql").write_text(
        "CREATE TABLE oops ( a INT, b TEXT;", encoding="utf-8"
    )
    s, _ = _make_sentinel()
    out = s.detect_b(
        fetch_columns=lambda: {"oops": {"a"}},
        migrations_dir=tmp_path,
    )
    # Either drift is detected with severity=info, or no drift at
    # all; the binding requirement is severity is never `warn` for
    # an uncertain parser result.
    for m in out:
        assert m.payload["severity"] == "info"
        assert m.payload["parser_uncertain"] is True


# ── Detector C: dataclass parser ───────────────────────────────────


def test_parse_payloads_dataclasses_finds_defs(tmp_path: Path) -> None:
    src = tmp_path / "p.py"
    src.write_text(
        """
from dataclasses import dataclass

@dataclass
class A:
    x: int
    y: str

@dataclass(frozen=True)
class B:
    only: int

class NotADC:
    z: int
""",
        encoding="utf-8",
    )
    digest = _drift.parse_payloads_dataclasses(src)
    assert digest.classes == {"A": {"x", "y"}, "B": {"only"}}


def test_parse_payloads_dataclasses_skips_underscore(tmp_path: Path) -> None:
    src = tmp_path / "p.py"
    src.write_text(
        "from dataclasses import dataclass\n\n"
        "@dataclass\nclass C:\n    public: int\n    _private: int\n",
        encoding="utf-8",
    )
    digest = _drift.parse_payloads_dataclasses(src)
    assert digest.classes == {"C": {"public"}}


def test_parse_real_payloads_module() -> None:
    """Sanity: the production payloads.py parses cleanly and
    contains the well-known MaintAck dataclass."""
    repo = Path(__file__).resolve().parents[5]
    src = repo / "ai" / "swarm" / "agents" / "payloads.py"
    digest = _drift.parse_payloads_dataclasses(src)
    assert "MaintAck" in digest.classes


# ── Detector C: diff_dataclass_vs_schema ──────────────────────────


def test_diff_dataclass_vs_schema_clean() -> None:
    msgs = _drift.diff_dataclass_vs_schema(
        dataclass_fields={"a", "b"},
        schema_properties={"a", "b"},
        schema_required={"a"},
    )
    assert msgs == []


def test_diff_dataclass_vs_schema_missing_required() -> None:
    msgs = _drift.diff_dataclass_vs_schema(
        dataclass_fields={"a"},
        schema_properties={"a", "b"},
        schema_required={"a", "b"},
    )
    assert any("missing from dataclass" in m for m in msgs)


def test_diff_dataclass_vs_schema_extra_field() -> None:
    msgs = _drift.diff_dataclass_vs_schema(
        dataclass_fields={"a", "b", "c"},
        schema_properties={"a", "b"},
        schema_required={"a"},
    )
    assert any("not declared in schema" in m for m in msgs)


# ── Detector C: agent integration ──────────────────────────────────


def test_detect_c_no_map_is_noop() -> None:
    s, _ = _make_sentinel()
    assert s.detect_c() == []
    assert s.detect_c(dataclass_schema_map={}) == []


def test_detect_c_emits_drift_for_missing_class(tmp_path: Path) -> None:
    src = tmp_path / "p.py"
    src.write_text("# empty module\n", encoding="utf-8")
    s, _ = _make_sentinel()
    out = s.detect_c(
        payloads_path=src,
        dataclass_schema_map={
            "MissingClass": ({"x"}, {"x"}),
        },
    )
    assert len(out) == 1
    p = out[0].payload
    assert p["detector"] == "C"
    assert p["severity"] == "critical"
    assert p["target"] == "MissingClass"
    assert any("not found" in e for e in p["errors"])


def test_detect_c_emits_drift_for_field_mismatch(tmp_path: Path) -> None:
    src = tmp_path / "p.py"
    src.write_text(
        "from dataclasses import dataclass\n\n"
        "@dataclass\nclass D:\n    a: int\n    b: str\n",
        encoding="utf-8",
    )
    s, _ = _make_sentinel()
    out = s.detect_c(
        payloads_path=src,
        dataclass_schema_map={
            "D": ({"a", "c"}, {"a", "c"}),  # b extra in DC, c missing
        },
    )
    assert len(out) == 1
    msgs = out[0].payload["errors"]
    assert any("missing from dataclass" in m for m in msgs)
    assert any("not declared in schema" in m for m in msgs)


def test_detect_c_clean_emits_nothing(tmp_path: Path) -> None:
    src = tmp_path / "p.py"
    src.write_text(
        "from dataclasses import dataclass\n\n"
        "@dataclass\nclass E:\n    x: int\n",
        encoding="utf-8",
    )
    s, _ = _make_sentinel()
    out = s.detect_c(
        payloads_path=src,
        dataclass_schema_map={"E": ({"x"}, {"x"})},
    )
    assert out == []


# ── Config validator ──────────────────────────────────────────────


def test_pg_check_interval_validator() -> None:
    from common.config import Config
    bad = Config(maint_schema_pg_check_interval_s=10).validate()
    assert any("maint_schema_pg_check_interval_s" in s for s in bad)
    good = Config(maint_schema_pg_check_interval_s=3600).validate()
    assert not any("maint_schema_pg_check_interval_s" in s for s in good)


# ── Detector C boot gate — startup isolation ──────────────────────


def test_detect_c_boot_gate_raises_on_mismatch(tmp_path: Path) -> None:
    """Detector C boot gate: a dataclass-vs-schema mismatch raises
    SchemaSentinelStartupError from __init__, failing ONLY this
    agent's instantiation."""
    src = tmp_path / "payloads.py"
    src.write_text(
        "from dataclasses import dataclass\n\n"
        "@dataclass\nclass Foo:\n    x: int\n    y: str\n",
        encoding="utf-8",
    )
    # Schema says Foo must have field 'z' (required) — but dataclass has x, y.
    bad_map = {"Foo": ({"z"}, {"z"})}
    with pytest.raises(SchemaSentinelStartupError) as exc_info:
        MaintSchemaSentinel(
            boot_c_map=bad_map,
            boot_c_payloads_path=src,
        )
    assert "Foo" in str(exc_info.value)


def test_detect_c_boot_gate_clean_map_does_not_raise(tmp_path: Path) -> None:
    """No drift → boot gate does NOT raise; sentinel starts normally."""
    src = tmp_path / "payloads.py"
    src.write_text(
        "from dataclasses import dataclass\n\n"
        "@dataclass\nclass Bar:\n    a: int\n",
        encoding="utf-8",
    )
    clean_map = {"Bar": ({"a"}, {"a"})}
    # Must not raise.
    s = MaintSchemaSentinel(boot_c_map=clean_map, boot_c_payloads_path=src)
    assert s.name == "maint.schema.v1"


def test_detect_c_startup_failure_isolated(tmp_path: Path) -> None:
    """Negative test: Detector C drift fails *only* the schema-sentinel
    agent's startup, not the registry boot.

    Steps:
    1. Sentinel init raises SchemaSentinelStartupError → sentinel is
       never registered.
    2. MaintScaler (a sibling agent) is instantiated and registered
       successfully in the same registry — proving isolation.
    """
    from swarm.agents.maint.scaler import MaintScaler
    from swarm.sdk.agent import AgentSpec
    from swarm.sdk.registry import AgentRegistry

    # Synthetic payloads file with a class whose schema doesn't match.
    src = tmp_path / "payloads.py"
    src.write_text(
        "from dataclasses import dataclass\n\n"
        "@dataclass\nclass MyPayload:\n    field_a: int\n",
        encoding="utf-8",
    )
    # Schema claims 'missing_field' is required — mismatch.
    bad_map = {"MyPayload": ({"missing_field"}, {"missing_field"})}

    registry = AgentRegistry()

    # Sentinel startup fails — isolated exception, NOT a global crash.
    sentinel_started = False
    try:
        MaintSchemaSentinel(boot_c_map=bad_map, boot_c_payloads_path=src)
        sentinel_started = True
    except SchemaSentinelStartupError:
        pass  # Expected — sentinel's own startup failed.

    assert not sentinel_started, "Sentinel should have raised at boot"

    # Other agents in the same 'registry boot' are unaffected.
    scaler = MaintScaler()
    spec = AgentSpec(
        name=scaler.name,
        instance_id=f"{scaler.name}.test",
        subscribes=tuple(scaler.subscribes),
        publishes=tuple(scaler.publishes),
    )
    registry.register(spec)

    all_specs = registry.all_specs()
    assert f"{scaler.name}.test" in all_specs, "Scaler must be registered"
    # Sentinel was never registered because its init raised.
    sentinel_ids = [iid for iid in all_specs if "schema" in iid]
    assert sentinel_ids == [], "Sentinel must NOT appear in the registry"
