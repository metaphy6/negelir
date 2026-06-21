"""Phase 10 §10.25.8 — Lexicon alert coverage and stale support tests."""
from __future__ import annotations

import os
import time
from pathlib import Path

try:
    import redis
except ImportError:
    redis = None
else:
    class _FakeRedis:
        def __init__(self, *args, **kwargs):
            pass

        def ping(self):
            return True

    redis.Redis = _FakeRedis

from common.telemetry import TelemetrySink
from nlp.lexicon_loader import LexiconStore

_VALID_META = (
    "_meta:\n"
    "  schema_version: 1\n"
    "  lexicon_version: 1.0.0\n"
    '  generated_at_utc: "2026-05-27T00:00:00Z"\n'
    "  generator: nlp.lexicon-build\n"
)


def _make_teams_yaml(n_entries: int) -> str:
    lines = [_VALID_META, "entries:"]
    for i in range(n_entries):
        lines.extend([
            f"  - canonical_id: team_{i}",
            "    names:",
            f"      - Team {i}",
            "    aliases:",
            f"      - t{i}",
        ])
    return "\n".join(lines) + "\n"


def _make_markets_yaml() -> str:
    return (
        _VALID_META
        + "entries:\n"
        + "  - canonical_id: ms\n"
        + "    names:\n"
        + "      - Mac Sonucu\n"
        + "    aliases:\n"
        + "      - 1x2\n"
    )


def _make_dialects_yaml() -> str:
    return (
        _VALID_META
        + "entries:\n"
        + "  - token: kl\n"
        + "    canonical_tokens:\n"
        + "      - Team 0\n"
    )


def _make_entities_neg_yaml() -> str:
    return (
        _VALID_META
        + "entries:\n"
        + "  - token: fener\n"
        + "    requires_co_tokens:\n"
        + "      - bahce\n"
    )


def _write_lexicon_dir(tmp_path: Path, *, teams_content: str) -> Path:
    (tmp_path / "teams.tr.yaml").write_text(teams_content, encoding="utf-8")
    small = _make_teams_yaml(2)
    for fname in ("players.tr.yaml", "leagues.tr.yaml", "competitions.tr.yaml"):
        (tmp_path / fname).write_text(small, encoding="utf-8")
    (tmp_path / "markets.tr.yaml").write_text(_make_markets_yaml(), encoding="utf-8")
    (tmp_path / "dialects.tr.yaml").write_text(_make_dialects_yaml(), encoding="utf-8")
    (tmp_path / "entities_negative.tr.yaml").write_text(
        _make_entities_neg_yaml(), encoding="utf-8"
    )
    return tmp_path


class TestLexiconStaleAlert:
    def test_old_lexicon_emits_stale_alert(self, tmp_path: Path) -> None:
        lexdir = _write_lexicon_dir(tmp_path, teams_content=_make_teams_yaml(2))
        now = time.time()
        old_time = now - (15 * 24 * 3600)
        for path in lexdir.glob("*.tr.yaml"):
            os.utime(path, (old_time, old_time))

        store = LexiconStore(
            lexdir,
            reload_s=9999,
            max_rss_mb=0,
            clock_wall=lambda: now,
            clock_mono=lambda: 0.0,
        )

        alerts = store.maybe_reload()
        assert any(alert["kind"] == "lexicon_stale" for alert in alerts), alerts

    def test_recent_lexicon_does_not_emit_stale_alert(self, tmp_path: Path) -> None:
        lexdir = _write_lexicon_dir(tmp_path, teams_content=_make_teams_yaml(2))
        now = time.time()
        store = LexiconStore(
            lexdir,
            reload_s=9999,
            max_rss_mb=0,
            clock_wall=lambda: now,
            clock_mono=lambda: 0.0,
        )

        alerts = store.maybe_reload()
        assert all(alert.get("kind") != "lexicon_stale" for alert in alerts)


class TestLexiconCoverageAlerts:
    def test_low_coverage_triggers_callback_after_grace_period(self) -> None:
        current = {"t": 0.0}
        callbacks: list[dict[str, object]] = []

        def current_time() -> float:
            return current["t"]

        sink = TelemetrySink(clock=current_time)
        sink.register_nlp_alert_callback(lambda payload: callbacks.append(payload))

        sink.record_nlp_lexicon_coverage("team_query", 0.5)
        assert callbacks == []

        current["t"] = 1800.1
        sink.record_nlp_lexicon_coverage("team_query", 0.5)

        assert len(callbacks) == 1
        assert callbacks[0]["kind"] == "lexicon_coverage_below_floor"
        assert callbacks[0]["severity"] == "warn"
        assert callbacks[0]["subject"] == "team_query"

    def test_coverage_above_floor_does_not_alert(self) -> None:
        sink = TelemetrySink(clock=lambda: 0.0)
        sink.register_nlp_alert_callback(lambda payload: (_ for _ in ()).throw(AssertionError("unexpected alert")))
        sink.record_nlp_lexicon_coverage("team_query", 0.7)
        sink.record_nlp_lexicon_coverage("team_query", 0.8)
        sink.record_nlp_lexicon_coverage("team_query", 0.9)

        assert True

    def test_empty_input_anomaly_alerts_after_threshold(self) -> None:
        current = {"t": 0.0}
        callbacks: list[dict[str, object]] = []

        def current_time() -> float:
            return current["t"]

        sink = TelemetrySink(clock=current_time)
        sink.register_nlp_alert_callback(lambda payload: callbacks.append(payload))

        subject = "subject_sha8"
        for index in range(19):
            sink.record_nlp_empty_input_rate(subject, False)
            current["t"] += 1.0
        sink.record_nlp_empty_input_rate(subject, True)

        assert len(callbacks) == 0

        for index in range(1, 8):
            sink.record_nlp_empty_input_rate(subject, True)
            current["t"] += 1.0

        assert callbacks == []

        sink.record_nlp_empty_input_rate(subject, True)
        current["t"] += 1.0

        assert len(callbacks) == 1
        assert callbacks[0]["kind"] == "nlp_empty_input_anomaly_per_subject"
        assert callbacks[0]["severity"] == "warn"
        assert callbacks[0]["subject"] == subject

    def test_empty_input_anomaly_does_not_alert_below_threshold(self) -> None:
        current = {"t": 0.0}
        callbacks: list[dict[str, object]] = []

        def current_time() -> float:
            return current["t"]

        sink = TelemetrySink(clock=current_time)
        sink.register_nlp_alert_callback(lambda payload: callbacks.append(payload))

        subject = "subject_sha8"
        for index in range(20):
            sink.record_nlp_empty_input_rate(subject, index % 4 == 0)
            current["t"] += 1.0

        assert callbacks == []

    def test_shout_rate_anomaly_alerts_after_threshold(self) -> None:
        current = {"t": 0.0}
        callbacks: list[dict[str, object]] = []

        def current_time() -> float:
            return current["t"]

        sink = TelemetrySink(clock=current_time)
        sink.register_nlp_alert_callback(lambda payload: callbacks.append(payload))

        subject = "subject_sha8"
        for index in range(19):
            sink.record_nlp_input_shout(subject, True)
            current["t"] += 1.0

        assert callbacks == []

        sink.record_nlp_input_shout(subject, True)
        current["t"] += 1.0

        assert len(callbacks) == 1
        assert callbacks[0]["kind"] == "nlp_shout_rate_anomaly_per_subject"
        assert callbacks[0]["severity"] == "warn"
        assert callbacks[0]["subject"] == subject
