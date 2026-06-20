"""Phase 10 §10.23.1 — per-tenant fair queue at NLP intake.

Deterministic round-robin scheduler over per-key virtual queues.
Each key has its own inflight cap so a noisy key cannot consume all
dispatch slots.
"""
from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass
from time import monotonic
from threading import Lock
from typing import Callable, Deque, Dict, Generic, Mapping, TypeVar

from ai.common.config import cfg

_ALLOWED_FAIRNESS_KEYS = ("tenant_id", "account_id", "ip_bucket")
_TENANT_CLASS_ENUM = tuple(cfg.nlp_tenant_class_enum)
_TENANT_ABUSE_ALERT_DEBOUNCE_S = 300.0

T = TypeVar("T")


@dataclass(frozen=True)
class FairQueueDispatch(Generic[T]):
    """One dispatch unit selected by the scheduler."""

    key: str
    item: T


class NlpIntakeFairQueue(Generic[T]):
    """Weighted-fair queue keyed by tenant/account/ip bucket.

    The scheduler is deterministic round-robin across keys with non-empty
    queues. Per-key inflight cap isolates noisy tenants.
    """

    def __init__(
        self,
        *,
        fairness_key: str | None = None,
        per_tenant_inflight_max: int | None = None,
        max_tracked_keys: int | None = None,
        on_key_evicted: Callable[[str], None] | None = None,
        tenant_abuse_qps_threshold: float | None = None,
        tenant_abuse_window_s: int | None = None,
        on_tenant_intake_rate: Callable[[str, float], None] | None = None,
        on_tenant_abuse_detected: Callable[[str, float], None] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.fairness_key = fairness_key or cfg.nlp_fairness_key
        self.per_tenant_inflight_max = int(
            per_tenant_inflight_max
            if per_tenant_inflight_max is not None
            else cfg.nlp_per_tenant_inflight_max
        )
        self.max_tracked_keys = int(
            max_tracked_keys
            if max_tracked_keys is not None
            else cfg.nlp_fairness_max_tracked_keys
        )
        self.on_key_evicted = on_key_evicted
        self.tenant_abuse_qps_threshold = float(
            tenant_abuse_qps_threshold
            if tenant_abuse_qps_threshold is not None
            else cfg.nlp_tenant_abuse_qps_threshold
        )
        self.tenant_abuse_window_s = int(
            tenant_abuse_window_s
            if tenant_abuse_window_s is not None
            else cfg.nlp_tenant_abuse_window_s
        )
        self.on_tenant_intake_rate = on_tenant_intake_rate
        self.on_tenant_abuse_detected = on_tenant_abuse_detected
        self._clock = clock or monotonic

        if self.fairness_key not in _ALLOWED_FAIRNESS_KEYS:
            raise ValueError(
                f"nlp_fairness_key must be one of {_ALLOWED_FAIRNESS_KEYS}; "
                f"got {self.fairness_key!r}"
            )
        if self.per_tenant_inflight_max < 1:
            raise ValueError("per_tenant_inflight_max must be >= 1")
        if self.max_tracked_keys < 1:
            raise ValueError("max_tracked_keys must be >= 1")
        if self.tenant_abuse_qps_threshold <= 0.0:
            raise ValueError("tenant_abuse_qps_threshold must be > 0")
        if self.tenant_abuse_window_s < 1:
            raise ValueError("tenant_abuse_window_s must be >= 1")

        self._lock = Lock()
        self._queues: Dict[str, Deque[T]] = {}
        self._rr_keys: Deque[str] = deque()
        self._inflight: Dict[str, int] = {}
        self._tracked_lru: OrderedDict[str, None] = OrderedDict()
        self._intake_window_by_key: Dict[str, Deque[float]] = {}
        self._abuse_alert_last_emitted_by_class: Dict[str, float] = {}

    def _resolve_key(self, attrs: Mapping[str, object]) -> str:
        def _as_str(value: object | None) -> str:
            return str(value).strip() if value is not None else ""

        tenant_id = _as_str(attrs.get("tenant_id"))
        account_id = _as_str(attrs.get("account_id"))
        ip_bucket = _as_str(attrs.get("ip_bucket")) or "ip:unknown"

        if self.fairness_key == "tenant_id":
            return tenant_id or account_id or ip_bucket
        if self.fairness_key == "account_id":
            return account_id or ip_bucket
        return ip_bucket

    def _track_key(self, key: str) -> None:
        if key in self._tracked_lru:
            self._tracked_lru.move_to_end(key)
            return
        self._tracked_lru[key] = None
        if len(self._tracked_lru) > self.max_tracked_keys:
            evicted_key, _ = self._tracked_lru.popitem(last=False)
            self._intake_window_by_key.pop(evicted_key, None)
            if self.on_key_evicted is not None:
                self.on_key_evicted(evicted_key)

    def _resolve_key_class(self, attrs: Mapping[str, object]) -> str:
        account_id = str(attrs.get("account_id") or "").strip()
        if account_id:
            account_tier = str(attrs.get("account_tier") or "").strip().lower()
            is_paid = bool(attrs.get("is_paid"))
            if is_paid or account_tier in {"paid", "pro", "premium", "enterprise"}:
                return "account_paid"
            return "account_free"
        if bool(attrs.get("ip_known_proxy")):
            return "ip_known_proxy"
        return "ip_anonymous"

    def enqueue(self, item: T, attrs: Mapping[str, object]) -> str:
        """Enqueue one request under the configured fairness key."""
        key = self._resolve_key(attrs)
        key_class = self._resolve_key_class(attrs)
        observed_qps = 0.0
        should_emit_abuse_alert = False
        with self._lock:
            self._track_key(key)
            q = self._queues.setdefault(key, deque())
            was_empty = not q
            q.append(item)
            if was_empty:
                self._rr_keys.append(key)

            now_s = float(self._clock())
            window = self._intake_window_by_key.setdefault(key, deque())
            window.append(now_s)
            cutoff_s = now_s - float(self.tenant_abuse_window_s)
            while window and window[0] < cutoff_s:
                window.popleft()

            observed_qps = float(len(window)) / float(self.tenant_abuse_window_s)

            sustained_over_window = False
            if window:
                sustained_over_window = (now_s - window[0]) >= float(self.tenant_abuse_window_s)

            if sustained_over_window and observed_qps > self.tenant_abuse_qps_threshold:
                last_emit = self._abuse_alert_last_emitted_by_class.get(key_class)
                if last_emit is None or (now_s - last_emit) >= _TENANT_ABUSE_ALERT_DEBOUNCE_S:
                    self._abuse_alert_last_emitted_by_class[key_class] = now_s
                    should_emit_abuse_alert = True

        if self.on_tenant_intake_rate is not None and key_class in _TENANT_CLASS_ENUM:
            self.on_tenant_intake_rate(key_class, observed_qps)
        if should_emit_abuse_alert and self.on_tenant_abuse_detected is not None:
            self.on_tenant_abuse_detected(key_class, observed_qps)
        return key

    def dequeue(self) -> FairQueueDispatch[T] | None:
        """Select the next dispatchable request via deterministic round-robin."""
        with self._lock:
            if not self._rr_keys:
                return None

            rotations = len(self._rr_keys)
            for _ in range(rotations):
                key = self._rr_keys.popleft()
                queue_for_key = self._queues.get(key)
                if not queue_for_key:
                    continue

                inflight = self._inflight.get(key, 0)
                if inflight >= self.per_tenant_inflight_max:
                    self._rr_keys.append(key)
                    continue

                item = queue_for_key.popleft()
                self._inflight[key] = inflight + 1

                if queue_for_key:
                    self._rr_keys.append(key)
                return FairQueueDispatch(key=key, item=item)

            return None

    def complete(self, key: str) -> None:
        """Release one inflight slot for *key*."""
        with self._lock:
            inflight = self._inflight.get(key, 0)
            if inflight > 0:
                self._inflight[key] = inflight - 1

    def inflight_for(self, key: str) -> int:
        with self._lock:
            return self._inflight.get(key, 0)

    def pending_for(self, key: str) -> int:
        with self._lock:
            queue_for_key = self._queues.get(key)
            return len(queue_for_key) if queue_for_key is not None else 0

    def tracked_key_count(self) -> int:
        with self._lock:
            return len(self._tracked_lru)
