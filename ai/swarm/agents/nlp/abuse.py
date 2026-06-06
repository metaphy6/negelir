from __future__ import annotations

import math
import statistics
import datetime as _dt
from collections import defaultdict, deque
from typing import Any, Iterable

from common.config import cfg
from swarm.agents.topics import NLP_ALERT_V1, NLP_SHADOW_V1
from swarm.sdk import AlertDebouncer
from swarm.sdk.types import Message


class NlpAbuseAgent:
    name = "nlp.abuse.v1"
    subscribes = [NLP_SHADOW_V1]
    publishes = [NLP_ALERT_V1]

    def __init__(self, monotonic: Any | None = None):
        self._monotonic = monotonic or _dt.datetime.now
        self._window: deque[tuple[float, dict[str, Any]]] = deque()
        self._dym_counts: dict[tuple[str, str], int] = defaultdict(int)
        self._dym_offered: dict[str, int] = defaultdict(int)
        self._dym_accepted: dict[tuple[str, str], int] = defaultdict(int)
        self._style_history: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._shadow_counts: dict[tuple[str, str], int] = defaultdict(int)
        self._fingerprint_accounts: dict[str, set[str]] = defaultdict(set)
        self._abuse_alert_debouncer = AlertDebouncer(
            ttl_s=300,
            max_buckets=10_000,
            clock=self._now_s,
        )

    def _now_s(self) -> float:
        result = self._monotonic()
        if isinstance(result, float):
            return result
        if isinstance(result, _dt.datetime):
            return result.timestamp()
        return float(result)

    def _expire(self, now_s: float) -> None:
        horizon_s = float(cfg.nlp_abuse_window_h) * 3600.0
        while self._window and now_s - self._window[0][0] > horizon_s:
            self._window.popleft()

    def _emit_alert(self, kind: str, severity: str, subject: str, details: dict[str, Any]) -> Message | None:
        decision = self._abuse_alert_debouncer.decide(
            kind=kind,
            subject=subject,
            severity=severity,
            reason=f"abuse_{kind}",
        )
        if not decision.emit:
            return None
        return Message.new(
            topic=NLP_ALERT_V1,
            payload={
                "schema_version": 1,
                "alert_id": f"abuse-{kind}-{subject}",
                "kind": kind,
                "severity": severity,
                "source": self.name,
                "subject": subject,
                "details": details,
                "emitted_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            },
            producer=self.name,
        )

    def handle(self, msg: Message) -> Iterable[Message]:
        payload = msg.payload
        now_s = self._now_s()
        self._window.append((now_s, payload))
        self._expire(now_s)

        events: list[Message] = []
        maybe = self._detect_dym(payload)
        if maybe is not None:
            events.append(maybe)

        maybe = self._detect_style_shift(payload)
        if maybe is not None:
            events.append(maybe)

        maybe = self._detect_shadow_concentration(payload)
        if maybe is not None:
            events.append(maybe)

        maybe = self._detect_account_farm(payload)
        if maybe is not None:
            events.append(maybe)

        return events

    def _detect_dym(self, payload: dict[str, Any]) -> Message | None:
        offered = str(payload.get("offered_intent") or "")
        accepted = str(payload.get("accepted_intent") or "")
        if not offered or not accepted:
            return None
        key = (offered, accepted)
        self._dym_offered[offered] += 1
        self._dym_counts[key] += 1
        offered_total = self._dym_offered[offered]
        if offered_total < 5:
            return None
        ratio = float(self._dym_counts[key]) / float(offered_total)
        if ratio > float(cfg.nlp_abuse_dym_acceptance_anomaly_ratio):
            return self._emit_alert(
                kind="nlp_abuse_did_you_mean_anomaly",
                severity="warn",
                subject=f"{offered}->{accepted}",
                details={"ratio": ratio, "window_count": offered_total},
            )
        return None

    def _detect_style_shift(self, payload: dict[str, Any]) -> Message | None:
        account_id = str(payload.get("account_id_h") or "")
        if not account_id:
            return None
        current = {
            "locale": str(payload.get("locale") or ""),
            "intent_class": str(payload.get("intent_class") or ""),
            "mean_token_length": float(payload.get("mean_token_length") or 0.0),
            "input_source": str(payload.get("input_source") or ""),
        }
        history = self._style_history[account_id]
        history.append(current)
        if len(history) < 5:
            return None
        baseline = history[:-1]
        current_dist = self._distribution(current)
        baseline_dist = self._aggregate_distribution(baseline)
        kl = self._kl_divergence(current_dist, baseline_dist)
        if kl > float(cfg.nlp_abuse_style_shift_kl):
            return self._emit_alert(
                kind="nlp_abuse_style_shift",
                severity="warn",
                subject=account_id,
                details={"kl": kl},
            )
        return None

    def _distribution(self, record: dict[str, Any]) -> dict[str, float]:
        keys = [f"locale:{record['locale']}", f"intent:{record['intent_class']}", f"source:{record['input_source']}"]
        if record["mean_token_length"] > 0:
            keys.append(f"len:{int(record['mean_token_length'])}")
        dist = {k: 1.0 for k in keys}
        total = len(dist)
        return {k: v / total for k, v in dist.items()}

    def _aggregate_distribution(self, history: list[dict[str, Any]]) -> dict[str, float]:
        counts: dict[str, int] = defaultdict(int)
        for record in history:
            for k, v in self._distribution(record).items():
                counts[k] += 1
        total = sum(counts.values())
        if total == 0:
            return {}
        return {k: v / total for k, v in counts.items()}

    def _kl_divergence(self, p: dict[str, float], q: dict[str, float]) -> float:
        if not p or not q:
            return 0.0
        divergence = 0.0
        for key, p_val in p.items():
            q_val = q.get(key) or 1e-6
            divergence += p_val * math.log(p_val / q_val)
        return divergence

    def _detect_shadow_concentration(self, payload: dict[str, Any]) -> Message | None:
        subject_bucket = str(payload.get("subject_key_sha8_prefix_2") or "")
        intent_class = str(payload.get("intent_class") or "")
        if not subject_bucket or not intent_class:
            return None
        key = (intent_class, subject_bucket)
        self._shadow_counts[key] += 1
        total = sum(v for (intent, _), v in self._shadow_counts.items() if intent == intent_class)
        if total < 10:
            return None
        prefix_counts = [v for (intent, _), v in self._shadow_counts.items() if intent == intent_class]
        unique_buckets = len(prefix_counts)
        if unique_buckets < int(cfg.nlp_abuse_shadow_concentration_distinct_buckets_min):
            return None
        top = max(prefix_counts)
        if top / total > 0.3:
            return self._emit_alert(
                kind="nlp_abuse_shadow_concentration",
                severity="warn",
                subject=intent_class,
                details={"concentration": top / total, "distinct_buckets": unique_buckets},
            )
        return None

    def _detect_account_farm(self, payload: dict[str, Any]) -> Message | None:
        fingerprint = str(payload.get("client_fingerprint_hash") or "")
        account_id = str(payload.get("account_id_h") or "")
        subject_bucket = str(payload.get("subject_key_sha8_prefix_2") or "")
        if not fingerprint or not account_id:
            return None
        accounts = self._fingerprint_accounts[fingerprint]
        accounts.add(account_id)
        if len(accounts) < int(cfg.nlp_abuse_account_farm_account_count_min):
            return None
        if subject_bucket and len(accounts) > 0:
            jaccard = len(accounts) / max(1, len(accounts) + 1)
            if jaccard > float(cfg.nlp_abuse_account_farm_jaccard_min):
                return self._emit_alert(
                    kind="nlp_abuse_account_farm",
                    severity="error",
                    subject=fingerprint,
                    details={"account_count": len(accounts), "jaccard": jaccard},
                )
        return None
