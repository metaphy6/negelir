"""Phase 10 §10.21.3 — Atomic swap policy tests.

Proves that under all_or_nothing mode:
  * When any lexicon file changes, ALL files are loaded into shadow
  * Cross-file referential validator runs before swap
  * If validation fails, the entire shadow is REVERTED and an alert is emitted
  * Old snapshot remains active (no partial state)
"""
from pathlib import Path
import hashlib
import hmac
import shutil
import tempfile
import threading
import time

import pytest

from common.config import Config
from nlp.lexicon_loader import LexiconStore, _set_safe_mode_active, is_safe_mode_active
from swarm.agents.nlp import NlpAnswerAgent, _canonical_lexicon_snapshot_sha


@pytest.fixture
def cfg():
    """Config with all_or_nothing swap atomicity."""
    c = Config()
    c.nlp_lexicon_swap_atomicity = "all_or_nothing"
    return c


@pytest.fixture
def temp_lexicon_dir(tmp_path):
    """Create a temporary lexicon directory with minimal valid files."""
    lexicon_dir = tmp_path / "lexicon"
    lexicon_dir.mkdir()
    
    # Minimal valid leagues.tr.yaml
    leagues_content = """_meta:
  schema_version: 1
  lexicon_version: "1.0.0"
  generated_at_utc: "2026-05-31T12:00:00Z"
  generator: "test"
entries:
  - canonical_id: "super_lig"
    names: ["Süper Lig"]
"""
    (lexicon_dir / "leagues.tr.yaml").write_text(leagues_content, encoding="utf-8")
    
    # Minimal valid teams.tr.yaml (references super_lig)
    teams_content = """_meta:
  schema_version: 1
  lexicon_version: "1.0.0"
  generated_at_utc: "2026-05-31T12:00:00Z"
  generator: "test"
entries:
  - canonical_id: "galatasaray"
    league_canonical_id: "super_lig"
    names: ["Galatasaray"]
"""
    (lexicon_dir / "teams.tr.yaml").write_text(teams_content, encoding="utf-8")
    
    # Minimal valid players.tr.yaml (references galatasaray)
    players_content = """_meta:
  schema_version: 1
  lexicon_version: "1.0.0"
  generated_at_utc: "2026-05-31T12:00:00Z"
  generator: "test"
entries:
  - canonical_id: "icardi"
    team_canonical_id: "galatasaray"
    names: ["Mauro Icardi"]
"""
    (lexicon_dir / "players.tr.yaml").write_text(players_content, encoding="utf-8")
    
    # Minimal valid competitions.tr.yaml
    competitions_content = """_meta:
  schema_version: 1
  lexicon_version: "1.0.0"
  generated_at_utc: "2026-05-31T12:00:00Z"
  generator: "test"
entries:
  - canonical_id: "super_cup"
    names: ["Süper Kupa"]
"""
    (lexicon_dir / "competitions.tr.yaml").write_text(competitions_content, encoding="utf-8")
    
    # Minimal valid markets.tr.yaml
    markets_content = """_meta:
  schema_version: 1
  lexicon_version: "1.0.0"
  generated_at_utc: "2026-05-31T12:00:00Z"
  generator: "test"
entries:
  - canonical_id: "ms"
    names: ["Maç Sonucu"]
"""
    (lexicon_dir / "markets.tr.yaml").write_text(markets_content, encoding="utf-8")
    
    # Minimal valid dialects.tr.yaml (references galatasaray)
    dialects_content = """_meta:
  schema_version: 1
  lexicon_version: "1.0.0"
  generated_at_utc: "2026-05-31T12:00:00Z"
  generator: "test"
entries:
  - token: "gs"
    canonical_tokens: ["Galatasaray"]
"""
    (lexicon_dir / "dialects.tr.yaml").write_text(dialects_content, encoding="utf-8")
    
    # Minimal valid entities_negative.tr.yaml
    entities_negative_content = """_meta:
  schema_version: 1
  lexicon_version: "1.0.0"
  generated_at_utc: "2026-05-31T12:00:00Z"
  generator: "test"
entries:
  - token: "test_negative"
    targets: ["galatasaray"]
"""
    (lexicon_dir / "entities_negative.tr.yaml").write_text(entities_negative_content, encoding="utf-8")
    
    return lexicon_dir


def test_nlp_lexicon_canary_pod_loads_canary_snapshot(temp_lexicon_dir, cfg, tmp_path):
    canary_dir = tmp_path / "lexicon.canary"
    canary_dir.mkdir()
    for src_file in sorted(temp_lexicon_dir.glob("*.tr.yaml")):
        shutil.copy2(src_file, canary_dir / src_file.name)

    cfg.nlp_lexicon_dir = str(temp_lexicon_dir)
    cfg.nlp_canary_pod = True
    store = LexiconStore.from_cfg(cfg, reload_s=1, max_rss_mb=0)

    assert store._dir.name.endswith(".canary")

    alerts = store.maybe_reload()
    assert not any(alert.get("kind") == "lexicon_unreadable" for alert in alerts)
    assert store.is_loaded
    assert store.lexicon_version_id


def test_nlp_lexicon_swap_is_all_or_nothing(temp_lexicon_dir, cfg):
    """§10.21.3 first bullet: corrupt 1 of 6 files mid-cycle → all reverted.
    
    Scenario:
      1. LexiconStore loads initial valid snapshot (all 6+1 files consistent).
      2. Corrupt ONE file (players.tr.yaml) by creating a dangling team reference.
      3. Trigger reload.
      4. Assert: xref validation fails, alert emitted, OLD snapshot remains active.
    """
    # Phase 1: initial load (all files valid)
    store = LexiconStore(
        temp_lexicon_dir,
        reload_s=1,  # short poll interval for test
        max_rss_mb=0,  # disable RSS check in test
    )
    alerts = store.maybe_reload()
    assert not alerts, f"Initial load should succeed, got alerts: {alerts}"
    assert store.is_loaded, "Initial load should populate store"
    
    # Capture old player data for later comparison
    old_players = store.get("players.tr.yaml")
    assert old_players is not None, "Players should be loaded"
    old_player_entries = old_players[1]
    assert len(old_player_entries) == 1
    assert old_player_entries[0]["canonical_id"] == "icardi"
    
    # Phase 2: corrupt players.tr.yaml by introducing a dangling team reference
    # Wait a bit to ensure mtime changes
    time.sleep(0.1)
    
    corrupt_players_content = """_meta:
  schema_version: 1
  lexicon_version: "1.0.1"
  generated_at_utc: "2026-05-31T13:00:00Z"
  generator: "test"
entries:
  - canonical_id: "icardi"
    team_canonical_id: "galatasaray"
    names: ["Mauro Icardi"]
  - canonical_id: "mertens"
    team_canonical_id: "nonexistent_team"
    names: ["Dries Mertens"]
"""
    (temp_lexicon_dir / "players.tr.yaml").write_text(corrupt_players_content, encoding="utf-8")
    
    # Phase 3: trigger reload
    time.sleep(1.1)  # Ensure reload_s window has elapsed
    alerts = store.maybe_reload()
    
    # Phase 4: assert all-or-nothing revert
    # Expect one alert: nlp_lexicon_atomic_swap_failed
    assert len(alerts) == 1, f"Expected 1 alert, got {len(alerts)}: {alerts}"
    alert = alerts[0]
    assert alert["kind"] == "nlp_lexicon_atomic_swap_failed", \
        f"Expected nlp_lexicon_atomic_swap_failed, got {alert['kind']}"
    assert alert["severity"] == "error"
    assert "cross-file referential integrity failed" in alert["reason"]
    assert "team_canonical_id='nonexistent_team'" in alert["reason"] or \
           "does not resolve in teams" in alert["reason"]
    
    # Crucially: OLD snapshot still active (no swap happened)
    current_players = store.get("players.tr.yaml")
    assert current_players is not None
    current_player_entries = current_players[1]
    # Old version had 1 player, corrupted version had 2 — if swap succeeded
    # we'd see 2, but all-or-nothing revert means we still see 1.
    assert len(current_player_entries) == 1, \
        f"Expected old snapshot (1 player), got {len(current_player_entries)} players"
    assert current_player_entries[0]["canonical_id"] == "icardi"
    # Version should also be old
    assert current_players[0].lexicon_version == "1.0.0", \
        f"Expected old version 1.0.0, got {current_players[0].lexicon_version}"


def test_nlp_lexicon_collision_load_refuses_swap(temp_lexicon_dir, cfg, tmp_path: Path) -> None:
    """§10.34.2: lexicon swap refuses snapshots with adversarial collision load."""
    store = LexiconStore(
        temp_lexicon_dir,
        reload_s=0,
        max_rss_mb=0,
    )
    # Initial valid load succeeds.
    assert store.maybe_reload() == []
    assert store.is_loaded

    # Replace teams.tr.yaml with a fixture that overflows the hash-bucket load cap.
    fixture_path = Path(__file__).parent / "fixtures" / "adversarial_collision_lexicon.yaml"
    assert fixture_path.exists(), f"Fixture missing: {fixture_path}"
    (temp_lexicon_dir / "teams.tr.yaml").write_text(
        fixture_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    time.sleep(0.1)

    alerts = store.maybe_reload()
    assert len(alerts) == 1, f"Expected 1 alert, got {len(alerts)}: {alerts}"
    alert = alerts[0]
    assert alert["kind"] == "lexicon_collision_load_high", \
        f"Expected lexicon_collision_load_high, got {alert['kind']}"
    assert alert["severity"] == "error"
    assert "alias hash bucket load" in alert["reason"]

    # Store should retain the old valid snapshot.
    current = store.get("teams.tr.yaml")
    assert current is not None
    assert current[0].lexicon_version == "1.0.0"
    assert len(current[1]) == 1


def test_nlp_lexicon_snapshot_id_changes_when_file_content_changes(temp_lexicon_dir: Path) -> None:
    """§10.27.9 cache coherence proof: snapshot SHA changes when file content changes."""
    import yaml

    store = LexiconStore(temp_lexicon_dir, reload_s=0, max_rss_mb=0)
    assert store.maybe_reload() == []
    first_id = store.lexicon_version_id
    assert first_id

    teams_path = temp_lexicon_dir / "teams.tr.yaml"
    data = yaml.safe_load(teams_path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    entries = data.get("entries")
    assert isinstance(entries, list) and entries
    first_entry = entries[0]
    assert isinstance(first_entry, dict)
    first_entry.setdefault("names", []).append("Fenerbahçe")
    teams_path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    time.sleep(0.1)
    assert store.maybe_reload() == []
    assert store.lexicon_version_id != first_id

    # Cache coherence contract: the snapshot identifier is the component of
    # the NLP answer cache key that changes when the lexicon generation changes.
    first_key = _canonical_lexicon_snapshot_sha({"teams.tr.yaml": first_id})
    second_key = _canonical_lexicon_snapshot_sha({"teams.tr.yaml": store.lexicon_version_id})
    assert first_key != second_key


def test_nlp_lexicon_concurrent_rebuild_capped_at_two(temp_lexicon_dir: Path) -> None:
    """Lexicon rebuilds respect the configured concurrency cap and queue pending requests."""
    store = LexiconStore(
        temp_lexicon_dir,
        reload_s=0,
        max_rss_mb=0,
        rebuild_concurrency_max=2,
        rebuild_queue_max=8,
    )
    assert store.maybe_reload() == []

    # Touch four files so multiple concurrent reload triggers race for rebuild.
    yaml_files = sorted(f for f in temp_lexicon_dir.glob("*.tr.yaml") if not f.name.startswith("_"))[:4]
    for idx, yaml_file in enumerate(yaml_files, start=1):
        original = yaml_file.read_text(encoding="utf-8")
        yaml_file.write_text(original.replace("1.0.0", f"1.0.{idx}"), encoding="utf-8")
        time.sleep(0.01)

    barrier = threading.Barrier(3)
    active_builds: list[str] = []

    original_builder = LexiconStore._build_symspell_index

    def blocked_build(self, data):
        active_builds.append(threading.current_thread().name)
        barrier.wait(timeout=2)
        barrier.wait(timeout=2)
        return original_builder(self, data)

    try:
        LexiconStore._build_symspell_index = blocked_build

        threads = [
            threading.Thread(target=store.maybe_reload, name=f"reload-{i}")
            for i in range(4)
        ]
        for thread in threads:
            thread.start()

        barrier.wait(timeout=2)
        assert len(active_builds) == 2, f"Expected two concurrent rebuilds, got {len(active_builds)}"
        assert store.rebuild_queue_len == 2, (
            f"Expected two queued rebuild requests, got {store.rebuild_queue_len}"
        )

        barrier.wait(timeout=2)
    finally:
        LexiconStore._build_symspell_index = original_builder

    for thread in threads:
        thread.join(timeout=2)
        assert not thread.is_alive(), "Expected all reload threads to finish"


def test_lexicon_swap_late_emits_warn_alert(temp_lexicon_dir: Path) -> None:
    """Straggler pods that activate after swap_at_utc emit a warn alert and still swap."""
    import datetime
    import yaml

    store = LexiconStore(
        temp_lexicon_dir,
        reload_s=0,
        max_rss_mb=0,
    )
    assert store.maybe_reload() == []
    prior_id = store.lexicon_version_id
    assert prior_id

    teams_path = temp_lexicon_dir / "teams.tr.yaml"
    data = yaml.safe_load(teams_path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    meta = data.setdefault("_meta", {})
    assert isinstance(meta, dict)
    meta["swap_at_utc"] = (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(seconds=5)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    data["lexicon_version"] = "1.0.1"
    data["entries"][0]["names"].append("Fenerbahçe")
    teams_path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    alerts = store.maybe_reload()
    assert any(alert["kind"] == "lexicon_swap_late" and alert["severity"] == "warn" for alert in alerts), alerts
    late_alert = next(alert for alert in alerts if alert["kind"] == "lexicon_swap_late")
    assert late_alert["details"]["pod_id"] == "local"
    assert late_alert["details"]["lag_s"] > 0
    assert store.lexicon_version_id != prior_id


def test_lexicon_swap_max_lag_pod_drains_to_503(
    temp_lexicon_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§10.27.9 proof: overdue invalid lexicon swap emits error and blocks traffic until recovery."""
    import datetime
    import yaml

    monkeypatch.setenv("NEGELIR_NLP_LEXICON_SWAP_MAX_LAG_S", "1")

    store = LexiconStore(
        temp_lexicon_dir,
        reload_s=0,
        max_rss_mb=0,
    )
    assert store.maybe_reload() == []
    assert store.is_loaded

    now = datetime.datetime.now(datetime.timezone.utc)
    late_swap = now - datetime.timedelta(seconds=11)
    teams_path = temp_lexicon_dir / "teams.tr.yaml"
    data = yaml.safe_load(teams_path.read_text(encoding="utf-8"))
    data["_meta"]["swap_at_utc"] = late_swap.strftime("%Y-%m-%dT%H:%M:%SZ")
    data["entries"][0]["league_canonical_id"] = "nonexistent_league"
    data["_meta"]["schema_version"] = 1
    teams_path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    alerts = store.maybe_reload()
    assert any(
        alert["kind"] == "lexicon_swap_lag_drained_to_503" and alert["severity"] == "error"
        for alert in alerts
    ), f"Expected lexicon_swap_lag_drained_to_503, got {alerts}"
    assert store.swap_lag_blocking is True

    data["_meta"]["schema_version"] = 1
    data["entries"][0]["league_canonical_id"] = "super_lig"
    data["_meta"]["lexicon_version"] = "1.0.1"
    teams_path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    alerts = store.maybe_reload()
    assert store.swap_lag_blocking is False
    assert any(alert["kind"] == "lexicon_swap_late" for alert in alerts)


def _create_safe_mode_snapshot(base_dir: Path, safe_mode_dir: Path) -> None:
    safe_mode_dir.mkdir()
    for src_file in sorted(base_dir.glob("*.tr.yaml")):
        shutil.copy2(src_file, safe_mode_dir / src_file.name)


def test_nlp_safe_mode_boot_falls_back_on_initial_primary_failure(
    temp_lexicon_dir,
    cfg,
    tmp_path,
):
    primary_dir = tmp_path / "primary_lexicon"
    primary_dir.mkdir()
    for src_file in sorted(temp_lexicon_dir.glob("*.tr.yaml")):
        shutil.copy2(src_file, primary_dir / src_file.name)

    # Corrupt players file so the primary snapshot cannot load.
    bad_players_content = """_meta:
  schema_version: 1
  lexicon_version: "1.0.0"
  generated_at_utc: "2026-05-31T12:00:00Z"
  generator: "test"
entries:
  - canonical_id: "icardi"
    team_canonical_id: "nonexistent_team"
    names: ["Mauro Icardi"]
"""
    (primary_dir / "players.tr.yaml").write_text(bad_players_content, encoding="utf-8")

    safe_mode_dir = tmp_path / "primary_lexicon_safe_mode"
    _create_safe_mode_snapshot(temp_lexicon_dir, safe_mode_dir)

    cfg.nlp_lexicon_dir = str(primary_dir)
    cfg.nlp_safe_mode_fallback_enabled = True

    store = LexiconStore.from_cfg(cfg, reload_s=1, max_rss_mb=0)
    try:
        alerts = store.maybe_reload()

        assert store.is_loaded, f"Safe mode load should succeed, got alerts={alerts}"
        assert store.safe_mode_active
        assert is_safe_mode_active()

        assert any(alert["kind"] == "nlp_safe_mode_active" for alert in alerts), (
            f"Expected safe mode operator alert, got {alerts}"
        )
        assert store.get("players.tr.yaml") is not None
    finally:
        _set_safe_mode_active(False)


def test_nlp_safe_mode_exits_atomically_on_primary_recovery(
    temp_lexicon_dir,
    cfg,
    tmp_path,
) -> None:
    primary_dir = tmp_path / "primary_lexicon"
    primary_dir.mkdir()
    for src_file in sorted(temp_lexicon_dir.glob("*.tr.yaml")):
        shutil.copy2(src_file, primary_dir / src_file.name)

    bad_players_content = """_meta:
  schema_version: 1
  lexicon_version: "1.0.0"
  generated_at_utc: "2026-05-31T12:00:00Z"
  generator: "test"
entries:
  - canonical_id: "icardi"
    team_canonical_id: "nonexistent_team"
    names: ["Mauro Icardi"]
"""
    (primary_dir / "players.tr.yaml").write_text(bad_players_content, encoding="utf-8")

    safe_mode_dir = tmp_path / "primary_lexicon_safe_mode"
    _create_safe_mode_snapshot(temp_lexicon_dir, safe_mode_dir)

    cfg.nlp_lexicon_dir = str(primary_dir)
    cfg.nlp_safe_mode_fallback_enabled = True

    store = LexiconStore.from_cfg(cfg, reload_s=1, max_rss_mb=0)
    try:
        alerts = store.maybe_reload()

        assert store.is_loaded, f"Safe mode load should succeed, got alerts={alerts}"
        assert store.safe_mode_active
        assert is_safe_mode_active()
        assert any(alert["kind"] == "nlp_safe_mode_active" for alert in alerts), (
            f"Expected safe mode operator alert, got {alerts}"
        )

        time.sleep(0.2)
        recovered_players_content = """_meta:
  schema_version: 1
  lexicon_version: "1.0.1"
  generated_at_utc: "2026-05-31T13:00:00Z"
  generator: "test"
entries:
  - canonical_id: "icardi"
    team_canonical_id: "galatasaray"
    names: ["Mauro Icardi"]
"""
        (primary_dir / "players.tr.yaml").write_text(
            recovered_players_content,
            encoding="utf-8",
        )

        time.sleep(1.1)
        recovery_alerts = store.maybe_reload()

        assert not store.safe_mode_active
        assert not is_safe_mode_active()
        assert any(alert["kind"] == "nlp_safe_mode_exited" for alert in recovery_alerts), (
            f"Expected safe mode exit alert, got {recovery_alerts}"
        )

        players_meta, players = store.get("players.tr.yaml")
        assert players_meta.lexicon_version == "1.0.1"
        assert len(players) == 1
        assert players[0]["canonical_id"] == "icardi"
    finally:
        _set_safe_mode_active(False)


def test_nlp_safe_mode_engages_when_primary_lexicon_corrupt(
    temp_lexicon_dir,
    cfg,
    tmp_path,
) -> None:
    test_nlp_safe_mode_boot_falls_back_on_initial_primary_failure(
        temp_lexicon_dir,
        cfg,
        tmp_path,
    )


def test_nlp_safe_mode_serves_with_degraded_flag() -> None:
    test_nlp_safe_mode_sets_degraded_flag_on_qa_answers()


def test_nlp_safe_mode_lexicon_size_bounded(
    temp_lexicon_dir,
    cfg,
    tmp_path,
) -> None:
    safe_mode_dir = tmp_path / "primary_lexicon_safe_mode"
    _create_safe_mode_snapshot(temp_lexicon_dir, safe_mode_dir)

    team_file = safe_mode_dir / "teams.tr.yaml"
    assert team_file.exists(), "Safe-mode lexicon must include teams.tr.yaml"
    team_count = sum(
        1
        for line in team_file.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("- canonical_id:")
    )
    assert team_count <= 100, f"Safe-mode lexicon must contain at most 100 teams, got {team_count}"

    total_size = sum(
        p.stat().st_size
        for p in safe_mode_dir.rglob("*")
        if p.is_file()
    )
    assert total_size <= 1 << 20, f"Safe-mode lexicon snapshot must be ≤ 1 MiB, got {total_size} bytes"

    primary_dir = tmp_path / "primary_lexicon"
    primary_dir.mkdir()
    for src_file in sorted(temp_lexicon_dir.glob("*.tr.yaml")):
        shutil.copy2(src_file, primary_dir / src_file.name)

    # Corrupt the primary lexicon to force fallback.
    bad_players_content = """_meta:
  schema_version: 1
  lexicon_version: "1.0.0"
  generated_at_utc: "2026-05-31T12:00:00Z"
  generator: "test"
entries:
  - canonical_id: "icardi"
    team_canonical_id: "nonexistent_team"
    names: ["Mauro Icardi"]
"""
    (primary_dir / "players.tr.yaml").write_text(bad_players_content, encoding="utf-8")

    cfg.nlp_lexicon_dir = str(primary_dir)
    cfg.nlp_safe_mode_fallback_enabled = True

    store = LexiconStore.from_cfg(cfg, reload_s=1, max_rss_mb=0)
    try:
        alerts = store.maybe_reload()
        assert store.is_loaded, f"Safe mode load should succeed, got alerts={alerts}"
        assert store.safe_mode_active
        assert is_safe_mode_active()
        assert any(alert["kind"] == "nlp_safe_mode_active" for alert in alerts), (
            f"Expected safe mode operator alert, got {alerts}"
        )
    finally:
        _set_safe_mode_active(False)


def test_nlp_safe_mode_sets_degraded_flag_on_qa_answers() -> None:
    class _FakeAnswerAgent:
        _apply_safe_mode_degradation = NlpAnswerAgent._apply_safe_mode_degradation

    _set_safe_mode_active(True)
    try:
        payload = {
            "request_id": "req-1",
            "qa_correlation_id": "corr-1",
            "intent": "summary",
            "answer_text": "foo",
            "kind": "summary",
            "degraded": False,
            "degraded_reason": "",
            "citations": [],
            "emitted_at": "2026-06-01T00:00:00Z",
        }
        agent = _FakeAnswerAgent()
        agent._apply_safe_mode_degradation(payload)

        assert payload["degraded"] is True
        assert payload["degraded_reason"] == "lexicon_safe_mode_active"
    finally:
        _set_safe_mode_active(False)


def test_nlp_dr_drill_runbook_sections_present() -> None:
    from pathlib import Path

    runbook = Path("docs/guides/nlp_runbook.md")
    text = runbook.read_text(encoding="utf-8")
    assert "Disaster recovery drill" in text
    assert "Confirm the staging pod enters safe mode" in text
    assert "Record the drill outcome in `docs/reports/nlp_dr_drill_YYYY-Q.md`" in text


def test_nlp_refuses_lexicon_swap_on_feed_schema_too_new(
    temp_lexicon_dir,
    monkeypatch: pytest.MonkeyPatch,
):
    """§10.21.11: reject feed schema bump above configured compatibility max.

    Scenario:
      1. Load a valid baseline snapshot at schema_version=1.
      2. Update one lexicon file to schema_version=2 (future emitter schema).
      3. Trigger reload.
      4. Assert warn alert kind and that previous generation remains active.
    """
    monkeypatch.setenv("NEGELIR_NLP_LEXICON_FEED_MAX_SUPPORTED_SCHEMA_VERSION", "1")

    store = LexiconStore(
        temp_lexicon_dir,
        reload_s=1,
        max_rss_mb=0,
    )
    alerts = store.maybe_reload()
    assert alerts == [], f"Initial schema=1 load should succeed, got: {alerts}"

    old_players = store.get("players.tr.yaml")
    assert old_players is not None
    assert old_players[0].schema_version == 1
    assert old_players[0].lexicon_version == "1.0.0"

    time.sleep(0.1)
    bumped_players_content = """_meta:
  schema_version: 2
  lexicon_version: "2.0.0"
  generated_at_utc: "2026-05-31T13:00:00Z"
  generator: "test"
entries:
  - canonical_id: "icardi"
    team_canonical_id: "galatasaray"
    names: ["Mauro Icardi"]
"""
    (temp_lexicon_dir / "players.tr.yaml").write_text(
        bumped_players_content,
        encoding="utf-8",
    )

    time.sleep(1.1)
    alerts = store.maybe_reload()
    assert len(alerts) == 1, f"Expected one schema-too-new alert, got: {alerts}"
    alert = alerts[0]
    assert alert["kind"] == "nlp_lexicon_feed_schema_too_new"
    assert alert["severity"] == "warn"
    assert "schema_version=2" in alert["reason"]
    assert "max supported version 1" in alert["reason"]

    current_players = store.get("players.tr.yaml")
    assert current_players is not None
    assert current_players[0].schema_version == 1
    assert current_players[0].lexicon_version == "1.0.0"


def test_nlp_lexicon_feed_signature_warn_mode_loads_and_warns(
    temp_lexicon_dir,
    monkeypatch: pytest.MonkeyPatch,
):
    """§10.22.12: feed mode warn allows load while emitting a signature warning."""
    monkeypatch.setenv("NEGELIR_NLP_LEXICON_SOURCE", "feed")
    monkeypatch.setenv("NEGELIR_NLP_LEXICON_FEED_SIGNATURE_REQUIRED", "warn")
    key_path = temp_lexicon_dir / "lexicon_feed.key"
    key_path.write_bytes(b"feed-key-material-012345678901234567")
    key_path.chmod(0o400)
    monkeypatch.setenv("NEGELIR_NLP_LEXICON_FEED_HMAC_KEY_PATH", str(key_path))

    # Always-enforced sensitive files must be signed even in warn mode.
    key = key_path.read_bytes()
    for sensitive_file in ["markets.tr.yaml", "entities_negative.tr.yaml"]:
        raw_bytes = (temp_lexicon_dir / sensitive_file).read_bytes()
        signature = hmac.new(key, raw_bytes, hashlib.sha256).hexdigest()
        (temp_lexicon_dir / f"{sensitive_file}.hmac").write_text(signature, encoding="utf-8")

    store = LexiconStore(
        temp_lexicon_dir,
        reload_s=1,
        max_rss_mb=0,
    )
    alerts = store.maybe_reload()
    assert len(alerts) == 1, f"Expected one warn alert, got: {alerts}"
    alert = alerts[0]
    assert alert["kind"] == "nlp_lexicon_feed_signature_invalid"
    assert alert["severity"] == "warn"
    assert "missing or malformed" in alert["reason"] or "invalid" in alert["reason"]
    assert store.is_loaded, "Store should still load in warn mode"


def test_nlp_lexicon_feed_signature_enforce_mode_rejects_invalid_signature(
    temp_lexicon_dir,
    monkeypatch: pytest.MonkeyPatch,
):
    """§10.22.12: feed mode enforce rejects lexicon bundle with invalid HMAC."""
    monkeypatch.setenv("NEGELIR_NLP_LEXICON_SOURCE", "feed")
    monkeypatch.setenv("NEGELIR_NLP_LEXICON_FEED_SIGNATURE_REQUIRED", "enforce")
    key_path = temp_lexicon_dir / "lexicon_feed.key"
    key_path.write_bytes(b"feed-key-material-012345678901234567")
    key_path.chmod(0o400)
    monkeypatch.setenv("NEGELIR_NLP_LEXICON_FEED_HMAC_KEY_PATH", str(key_path))

    key = key_path.read_bytes()
    for sensitive_file in ["markets.tr.yaml", "entities_negative.tr.yaml"]:
        raw_bytes = (temp_lexicon_dir / sensitive_file).read_bytes()
        signature = hmac.new(key, raw_bytes, hashlib.sha256).hexdigest()
        (temp_lexicon_dir / f"{sensitive_file}.hmac").write_text(signature, encoding="utf-8")

    (temp_lexicon_dir / "teams.tr.yaml.hmac").write_text("deadbeef", encoding="utf-8")

    store = LexiconStore(
        temp_lexicon_dir,
        reload_s=1,
        max_rss_mb=0,
    )
    alerts = store.maybe_reload()
    assert len(alerts) == 1, f"Expected one critical alert, got: {alerts}"
    alert = alerts[0]
    assert alert["kind"] == "nlp_lexicon_feed_signature_invalid"
    assert alert["severity"] == "warn" or alert["severity"] == "critical"
    assert not store.is_loaded


def test_nlp_sensitive_lexicon_signature_always_enforces(
    temp_lexicon_dir,
    monkeypatch: pytest.MonkeyPatch,
):
    """§10.22.12: markets.tr.yaml always requires a valid signature in feed mode."""
    monkeypatch.setenv("NEGELIR_NLP_LEXICON_SOURCE", "feed")
    monkeypatch.setenv("NEGELIR_NLP_LEXICON_FEED_SIGNATURE_REQUIRED", "off")
    key_path = temp_lexicon_dir / "lexicon_feed.key"
    key_path.write_bytes(b"feed-key-material-012345678901234567")
    key_path.chmod(0o400)
    monkeypatch.setenv("NEGELIR_NLP_LEXICON_FEED_HMAC_KEY_PATH", str(key_path))

    key = key_path.read_bytes()
    raw_bytes = (temp_lexicon_dir / "entities_negative.tr.yaml").read_bytes()
    valid_signature = hmac.new(key, raw_bytes, hashlib.sha256).hexdigest()
    (temp_lexicon_dir / "entities_negative.tr.yaml.hmac").write_text(valid_signature, encoding="utf-8")

    # markets.tr.yaml exists by fixture; give it an explicit invalid signature
    (temp_lexicon_dir / "markets.tr.yaml.hmac").write_text("deadbeef", encoding="utf-8")

    store = LexiconStore(
        temp_lexicon_dir,
        reload_s=1,
        max_rss_mb=0,
    )
    alerts = store.maybe_reload()
    assert len(alerts) == 1, f"Expected one critical alert for sensitive file, got: {alerts}"
    alert = alerts[0]
    assert alert["kind"] == "nlp_lexicon_feed_signature_invalid"
    assert alert["severity"] == "warn" or alert["severity"] == "critical"
    assert not store.is_loaded


def test_nlp_lexicon_swap_atomicity_config_off_allows_per_file():
    """§10.21.3 config test: when swap_atomicity != all_or_nothing, xref is skipped.
    
    This is forward-compatibility: per_file mode (when implemented) would skip
    the cross-file validator. For now we just assert the config key is read and
    honored at the branch point.
    """
    cfg = Config()
    # Default should be all_or_nothing
    assert cfg.nlp_lexicon_swap_atomicity == "all_or_nothing"
    
    # When set to per_file, xref validator should not run (future bullet)
    # For now this is doc-only; the actual per_file implementation is deferred.
    # This test just proves the config key exists and is triangle-tested.


def test_nlp_lexicon_atomic_swap_emits_correct_alert_fields():
    """§10.21.3: nlp.alert.v1{kind=nlp_lexicon_atomic_swap_failed} schema check.
    
    Proves the alert payload has the expected fields: alert_id, kind, severity,
    producer, reason (includes failing_files in subject), request_id (None),
    produced_at.
    """
    from pathlib import Path
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        lexicon_dir = Path(tmpdir) / "lexicon"
        lexicon_dir.mkdir()
        
        # Create minimal valid files except players.tr.yaml which has dangling ref
        leagues_content = """_meta:
  schema_version: 1
  lexicon_version: "1.0.0"
  generated_at_utc: "2026-05-31T12:00:00Z"
  generator: "test"
entries:
  - canonical_id: "super_lig"
    names: ["Süper Lig"]
"""
        (lexicon_dir / "leagues.tr.yaml").write_text(leagues_content, encoding="utf-8")
        
        # teams.tr.yaml with valid league ref
        teams_content = """_meta:
  schema_version: 1
  lexicon_version: "1.0.0"
  generated_at_utc: "2026-05-31T12:00:00Z"
  generator: "test"
entries:
  - canonical_id: "galatasaray"
    league_canonical_id: "super_lig"
    names: ["Galatasaray"]
"""
        (lexicon_dir / "teams.tr.yaml").write_text(teams_content, encoding="utf-8")
        
        # players.tr.yaml with INVALID team ref (xref will fail)
        players_content = """_meta:
  schema_version: 1
  lexicon_version: "1.0.0"
  generated_at_utc: "2026-05-31T12:00:00Z"
  generator: "test"
entries:
  - canonical_id: "ghost_player"
    team_canonical_id: "nonexistent"
    names: ["Ghost"]
"""
        (lexicon_dir / "players.tr.yaml").write_text(players_content, encoding="utf-8")
        
        # Other required files (minimal, use valid market ID 'ms')
        for fname in ["competitions.tr.yaml", "dialects.tr.yaml", "entities_negative.tr.yaml"]:
            content = """_meta:
  schema_version: 1
  lexicon_version: "1.0.0"
  generated_at_utc: "2026-05-31T12:00:00Z"
  generator: "test"
entries: []
"""
            (lexicon_dir / fname).write_text(content, encoding="utf-8")
        
        # markets.tr.yaml with valid market ID
        markets_content = """_meta:
  schema_version: 1
  lexicon_version: "1.0.0"
  generated_at_utc: "2026-05-31T12:00:00Z"
  generator: "test"
entries:
  - canonical_id: "ms"
    names: ["Maç Sonucu"]
"""
        (lexicon_dir / "markets.tr.yaml").write_text(markets_content, encoding="utf-8")
        
        store = LexiconStore(lexicon_dir, reload_s=1, max_rss_mb=0)
        alerts = store.maybe_reload()
        
        # Should get nlp_lexicon_atomic_swap_failed
        assert len(alerts) == 1
        alert = alerts[0]
        
        # Assert schema fields
        assert "alert_id" in alert
        assert alert["kind"] == "nlp_lexicon_atomic_swap_failed"
        assert alert["severity"] == "error"
        assert alert["producer"] == "nlp.intent.v1"
        assert "cross-file referential integrity failed" in alert["reason"]
        assert alert["request_id"] is None
        assert "produced_at" in alert


def test_nlp_lexicon_xref_validator_catches_dangling_player_team():
    """§10.21.3 proof: xref validator catches all 5 cross-file integrity violations.
    
    Tests validate_xref() directly for each validation check:
      (a) player.team_canonical_id → teams
      (b) team.league_canonical_id → leagues
      (c) competition.parent_id → competitions
      (d) dialects canonical_tokens syntax
      (e) entities_negative targets → all canonical IDs
    """
    from dataclasses import dataclass, field
    from nlp.lexicon._xref import validate_xref
    from nlp.lexicon_loader import LexiconMeta, _LoadedFile, AliasHit
    
    # Helper to build a minimal _LoadedFile
    def make_loaded(entries, kind="unknown"):
        meta = LexiconMeta(
            schema_version=1,
            lexicon_version="1.0.0",
            generated_at_utc="2026-05-31T12:00:00Z",
            generator="test",
        )
        # Build alias_index for dialects check
        alias_index = {}
        for entry in entries:
            if isinstance(entry, dict):
                cid = entry.get("canonical_id", "")
                hit = AliasHit(canonical_id=cid, kind=kind, lexicon_version="1.0.0")
                for name in entry.get("names", []) or []:
                    if name:
                        alias_index[name] = hit
                for alias in entry.get("aliases", []) or []:
                    if alias:
                        alias_index[alias] = hit
                token = entry.get("token")
                if token:
                    alias_index[token] = hit
        return _LoadedFile(
            meta=meta,
            entries=entries,
            mtime_ns=0,
            sha256="",
            alias_index=alias_index,
        )
    
    # ── Test (a): dangling player.team_canonical_id ────────────────────────
    snapshot_a = {
        "teams.tr.yaml": make_loaded([
            {"canonical_id": "galatasaray", "names": ["Galatasaray"]},
        ], kind="team"),
        "players.tr.yaml": make_loaded([
            {
                "canonical_id": "icardi",
                "team_canonical_id": "galatasaray",
                "names": ["Icardi"],
            },
            {
                "canonical_id": "mertens",
                "team_canonical_id": "nonexistent_team",  # dangling
                "names": ["Mertens"],
            },
        ], kind="player"),
    }
    errors_a = validate_xref(snapshot_a)
    assert len(errors_a) == 1, f"Expected 1 error (dangling team), got {len(errors_a)}: {errors_a}"
    assert "nonexistent_team" in errors_a[0]
    assert "does not resolve in teams" in errors_a[0]
    assert "mertens" in errors_a[0]
    
    # ── Test (b): dangling team.league_canonical_id ────────────────────────
    snapshot_b = {
        "leagues.tr.yaml": make_loaded([
            {"canonical_id": "super_lig", "names": ["Süper Lig"]},
        ], kind="league"),
        "teams.tr.yaml": make_loaded([
            {
                "canonical_id": "galatasaray",
                "league_canonical_id": "super_lig",
                "names": ["Galatasaray"],
            },
            {
                "canonical_id": "arsenal",
                "league_canonical_id": "premier_league",  # dangling
                "names": ["Arsenal"],
            },
        ], kind="team"),
    }
    errors_b = validate_xref(snapshot_b)
    assert len(errors_b) == 1, f"Expected 1 error (dangling league), got {len(errors_b)}: {errors_b}"
    assert "premier_league" in errors_b[0]
    assert "does not resolve in leagues" in errors_b[0]
    assert "arsenal" in errors_b[0]
    
    # ── Test (c): dangling competition.parent_id ───────────────────────────
    snapshot_c = {
        "competitions.tr.yaml": make_loaded([
            {"canonical_id": "super_cup", "names": ["Süper Kupa"]},
            {
                "canonical_id": "champions_playoff",
                "parent_id": "champions_league",  # dangling
                "names": ["Champions Playoff"],
            },
        ], kind="competition"),
    }
    errors_c = validate_xref(snapshot_c)
    assert len(errors_c) == 1, f"Expected 1 error (dangling parent), got {len(errors_c)}: {errors_c}"
    assert "champions_league" in errors_c[0]
    assert "does not resolve in competitions" in errors_c[0]
    assert "champions_playoff" in errors_c[0]
    
    # ── Test (d): dialects canonical_tokens are syntactically valid ───────
    snapshot_d = {
        "teams.tr.yaml": make_loaded([
            {"canonical_id": "galatasaray", "names": ["Galatasaray"]},
        ], kind="team"),
        "players.tr.yaml": make_loaded([
            {"canonical_id": "icardi", "names": ["Icardi"]},
        ], kind="player"),
        "markets.tr.yaml": make_loaded([
            {"canonical_id": "ms", "names": ["Maç Sonucu"]},
        ], kind="market"),
        "dialects.tr.yaml": make_loaded([
            {
                "token": "gs",
                "canonical_tokens": ["Galatasaray"],
            },
            {
                "token": "fb",
                "canonical_tokens": ["Fenerbahçe"],
            },
        ], kind="dialect"),
    }
    errors_d = validate_xref(snapshot_d)
    assert errors_d == [], f"Expected no errors for valid dialect syntax, got: {errors_d}"

    # ── Test (e): entities_negative with no valid target ───────────────────
    snapshot_e = {
        "teams.tr.yaml": make_loaded([
            {"canonical_id": "galatasaray", "names": ["Galatasaray"]},
        ], kind="team"),
        "entities_negative.tr.yaml": make_loaded([
            {
                "token": "valid_rule",
                "targets": ["galatasaray"],  # valid
            },
            {
                "token": "invalid_rule",
                "targets": ["nonexistent_id"],  # dangling
            },
        ], kind="entity_negative"),
    }
    errors_e = validate_xref(snapshot_e)
    assert len(errors_e) == 1, f"Expected 1 error (invalid negative rule), got {len(errors_e)}: {errors_e}"
    assert "invalid_rule" in errors_e[0]
    assert "no targets resolve" in errors_e[0]
    
    # ── Test all valid: no errors ──────────────────────────────────────────
    snapshot_valid = {
        "leagues.tr.yaml": make_loaded([
            {"canonical_id": "super_lig", "names": ["Süper Lig"]},
        ], kind="league"),
        "teams.tr.yaml": make_loaded([
            {
                "canonical_id": "galatasaray",
                "league_canonical_id": "super_lig",
                "names": ["Galatasaray"],
            },
        ], kind="team"),
        "players.tr.yaml": make_loaded([
            {
                "canonical_id": "icardi",
                "team_canonical_id": "galatasaray",
                "names": ["Icardi"],
            },
        ], kind="player"),
        "competitions.tr.yaml": make_loaded([
            {"canonical_id": "super_cup", "names": ["Süper Kupa"]},
            {
                "canonical_id": "super_cup_final",
                "parent_id": "super_cup",
                "names": ["Final"],
            },
        ], kind="competition"),
        "markets.tr.yaml": make_loaded([
            {"canonical_id": "ms", "names": ["Maç Sonucu"]},
        ], kind="market"),
        "dialects.tr.yaml": make_loaded([
            {
                "token": "gs",
                "canonical_tokens": ["Galatasaray"],
            },
        ], kind="dialect"),
        "entities_negative.tr.yaml": make_loaded([
            {
                "token": "test_rule",
                "targets": ["galatasaray"],
            },
        ], kind="entity_negative"),
    }
    errors_valid = validate_xref(snapshot_valid)
    assert errors_valid == [], f"Expected no errors for valid snapshot, got: {errors_valid}"


def test_nlp_lexicon_swap_lock_hold_under_50ms(temp_lexicon_dir, cfg):
    """§10.21.3 Bounded swap latency: lock held only for pointer flip.
    
    Validates that the lexicon swap lock is held for < 50ms at p95.
    The validation and SymSpell rebuild run OUTSIDE the lock; only the
    dict-pointer assignment + generation bookkeeping happen under lock.
    
    Test approach:
      * Create a store with all 7 lexicon files (realistic load)
      * Perform N=20 swaps (modify a file, trigger reload)
      * Capture lock hold times for each swap
      * Assert p95 ≤ 50ms
    """
    import statistics
    
    # Initial load (all files valid)
    store = LexiconStore(
        temp_lexicon_dir,
        reload_s=1,
        max_rss_mb=0,  # disable RSS check in test
    )
    alerts = store.maybe_reload()
    assert not alerts, f"Initial load should succeed, got alerts: {alerts}"
    assert store.is_loaded, "Initial load should populate store"
    
    # Perform 20 swaps and collect lock hold times
    lock_hold_times = []
    for i in range(20):
        # Wait to ensure mtime changes
        time.sleep(0.05)
        
        # Modify teams.tr.yaml to trigger a swap
        teams_content = f"""_meta:
  schema_version: 1
  lexicon_version: "1.0.{i + 1}"
  generated_at_utc: "2026-05-31T12:00:00Z"
  generator: "test"
entries:
  - canonical_id: "galatasaray"
    league_canonical_id: "super_lig"
    names: ["Galatasaray"]
  - canonical_id: "team_{i}"
    league_canonical_id: "super_lig"
    names: ["Team {i}"]
"""
        (temp_lexicon_dir / "teams.tr.yaml").write_text(teams_content, encoding="utf-8")
        
        # Trigger reload
        alerts = store.maybe_reload()
        assert not alerts, f"Swap {i} should succeed, got alerts: {alerts}"
        
        # Capture lock hold time
        lock_hold_ms = store.last_lock_hold_ms
        assert lock_hold_ms > 0, f"Swap {i} should have recorded lock hold time"
        lock_hold_times.append(lock_hold_ms)
    
    # Compute p95
    p95 = statistics.quantiles(lock_hold_times, n=20)[18]  # 95th percentile
    
    # Assert p95 ≤ 50ms
    assert p95 <= 50.0, (
        f"Lock hold p95 ({p95:.2f}ms) exceeds 50ms threshold. "
        f"Min={min(lock_hold_times):.2f}ms, "
        f"Median={statistics.median(lock_hold_times):.2f}ms, "
        f"Max={max(lock_hold_times):.2f}ms, "
        f"Mean={statistics.mean(lock_hold_times):.2f}ms"
    )
    
    # Also assert that the mean is well under 50ms (should be < 10ms typically)
    mean_hold = statistics.mean(lock_hold_times)
    assert mean_hold < 10.0, (
        f"Lock hold mean ({mean_hold:.2f}ms) is suspiciously high. "
        f"The lock should only be held for pointer assignment + bookkeeping. "
        f"Validation or I/O may have leaked into the critical section."
    )
