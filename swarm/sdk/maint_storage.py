"""Phase 8 §8.13.2 — cumulative ``data/maint/`` storage cap.

The :class:`MaintStorageWarden` is a tiny stateful helper meant to be
called once per heartbeat by every §8.x maint-plane agent. It walks
``<data_dir>/maint/`` (or any caller-supplied root), sums the byte
total per-subdir, and decides whether to:

* emit a warn-level pressure alert (≥ ``warn_pct`` of the cap),
* emit an error-level pressure alert AND flip the writer-blocking
  flag (≥ ``error_pct`` of the cap, default 100%),
* clear the writer-blocking flag once usage drops below
  ``release_pct`` of the cap (single hysteresis band — prevents
  thrash between writes and clears).

The warden does **not** itself enforce blocking on writers — that is
the writer's responsibility (each spool / audit / ledger should
short-circuit and exit code 6 ``maint_storage_full`` when
:meth:`is_blocking` returns True). Centralising the enforcement
would require touching every spool consumer in one diff; the
boundary lives at "alerts + flag", and §8.13.7 is where the
spool-side enforcement lands.

Doctrine boundaries this module honours:

* **No emission of `maint.event.v1`.** ROADMAP §8.16.9 reserves
  pressure signals for sec.alert.v1 (paging) only — successful
  ticks below the warn threshold produce zero output. The audit
  trail for the warden lives in operator-side telemetry gauges,
  not in the audit log.
* **One-shot debounce per band.** Once a warn alert has fired,
  subsequent warn-band ticks are silenced for ``debounce_s``
  (default 1h). Crossing into the error band re-arms warn
  emissions on the way down. This mirrors the §8.13.6 alert
  cadence pattern.
* **Cap of 0 = disabled.** Same opt-out sentinel pattern as
  ``maint_scaler_default_max_replicas`` — operators can disable
  the warden entirely while still wiring it into ticks.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable

from common.config import cfg as _cfg

from .types import Envelope, Message, Topic

SEC_ALERT_TOPIC: Topic = Topic("sec.alert.v1")

# Hysteresis band (binding per ROADMAP §8.13.2): once at 100% the
# blocking flag stays set until usage drops below 70%. Prevents
# rapid toggling at the cap boundary.
_RELEASE_PCT_DEFAULT = 70.0
_WARN_PCT_DEFAULT = 80.0
_ERROR_PCT_DEFAULT = 100.0
_DEBOUNCE_S_DEFAULT = 3600  # 1h


@dataclass
class MaintStorageDecision:
    """Snapshot returned by :meth:`MaintStorageWarden.check`.

    * ``alerts`` — list of ``sec.alert.v1`` :class:`Message` objects
      ready to publish (zero or more, never duplicates within the
      debounce window).
    * ``per_subdir_bytes`` — observed bytes per top-level subdir
      under the warden root (telemetry surface).
    * ``total_bytes`` — sum across subdirs.
    * ``cap_bytes`` — the hard cap converted to bytes (0 if disabled).
    * ``blocking`` — whether writers should refuse new writes.
    """

    alerts: list[Message] = field(default_factory=list)
    per_subdir_bytes: dict[str, int] = field(default_factory=dict)
    total_bytes: int = 0
    cap_bytes: int = 0
    blocking: bool = False


class MaintStorageWarden:
    """Stateful storage-cap accountant. Safe to instantiate once
    per process; not thread-safe (callers serialise via the agent's
    own tick loop).
    """

    def __init__(
        self,
        *,
        root: str | None = None,
        cap_mb: int | None = None,
        warn_pct: float = _WARN_PCT_DEFAULT,
        error_pct: float = _ERROR_PCT_DEFAULT,
        release_pct: float = _RELEASE_PCT_DEFAULT,
        debounce_s: int = _DEBOUNCE_S_DEFAULT,
        clock: Callable[[], float] | None = None,
        new_id: Callable[[], str] | None = None,
        clock_iso: Callable[[], str] | None = None,
        source: str = "maint.storage.v1",
    ) -> None:
        if not (0.0 < warn_pct < error_pct <= 100.0):
            raise ValueError(
                f"warn_pct must be in (0, error_pct]; got "
                f"warn={warn_pct}, error={error_pct}"
            )
        if not (0.0 < release_pct < warn_pct):
            raise ValueError(
                f"release_pct must be in (0, warn_pct); got "
                f"release={release_pct}, warn={warn_pct}"
            )
        self._root = root or os.path.join(_cfg.data_dir, "maint")
        self._cap_mb = int(cap_mb if cap_mb is not None
                           else _cfg.maint_storage_total_max_mb)
        self._warn_pct = warn_pct
        self._error_pct = error_pct
        self._release_pct = release_pct
        self._debounce_s = max(1, int(debounce_s))
        import time as _time
        from datetime import datetime, timezone
        from uuid import uuid4
        self._clock = clock or _time.monotonic
        self._new_id = new_id or (lambda: uuid4().hex)
        self._clock_iso = clock_iso or (
            lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
        )
        self._source = source
        # Debounce state: last emission monotonic seconds per band.
        # ``-inf`` = never emitted (so the first tick over a threshold
        # always fires).
        self._last_warn_at: float = float("-inf")
        self._last_error_at: float = float("-inf")
        self._blocking: bool = False
        # Telemetry cache: updated on every check() so metrics_snapshot()
        # can serve the last-seen values without a second filesystem walk.
        self._last_decision: MaintStorageDecision | None = None

    # ── Public API ────────────────────────────────────────────────

    @property
    def cap_bytes(self) -> int:
        return self._cap_mb * 1024 * 1024 if self._cap_mb > 0 else 0

    def is_blocking(self) -> bool:
        """True iff the warden has crossed the error band and not
        yet recovered below the release threshold."""
        return self._blocking

    def check(self) -> MaintStorageDecision:
        """Walk the root, compute totals, decide alerts + blocking.

        Safe to call when the cap is disabled (returns an empty
        decision with usage stats only) or when the root does not
        yet exist (returns zero usage)."""
        per_subdir = self._du_per_subdir()
        total = sum(per_subdir.values())
        cap = self.cap_bytes
        decision = MaintStorageDecision(
            per_subdir_bytes=per_subdir,
            total_bytes=total,
            cap_bytes=cap,
        )
        if cap <= 0:
            decision.blocking = False
            self._last_decision = decision
            return decision

        usage_pct = (total / cap) * 100.0
        now = self._clock()

        # Hysteresis: blocking persists until usage drops below release.
        if self._blocking:
            if usage_pct < self._release_pct:
                self._blocking = False
        else:
            if usage_pct >= self._error_pct:
                self._blocking = True

        decision.blocking = self._blocking

        # Alert emission. Error band takes precedence over warn band.
        if usage_pct >= self._error_pct:
            if (now - self._last_error_at) >= self._debounce_s:
                decision.alerts.append(self._alert(
                    severity="error",
                    usage_pct=usage_pct,
                    total=total, cap=cap,
                ))
                self._last_error_at = now
                # Crossing into error re-arms warn for the way down
                # (operators see one warn after recovery starts).
                self._last_warn_at = float("-inf")
        elif usage_pct >= self._warn_pct:
            if (now - self._last_warn_at) >= self._debounce_s:
                decision.alerts.append(self._alert(
                    severity="warn",
                    usage_pct=usage_pct,
                    total=total, cap=cap,
                ))
                self._last_warn_at = now
        # Below warn → no alert; debounces are NOT reset (operators
        # don't need a "we're ok now" page).
        self._last_decision = decision
        return decision

    def metrics_snapshot(self) -> dict[str, float]:
        """Return a flat Prometheus-style snapshot of storage usage.

        Key shapes:

        * ``maint_storage_used_bytes{subdir=<name>}`` — per-subdir
          byte count observed during the last :meth:`check` call.
        * ``maint_storage_total_bytes`` — rollup across all subdirs.

        Returns an empty dict until the first :meth:`check` call has
        run (callers must call ``check()`` at least once per heartbeat
        before registering this as a metrics source).
        """
        d = self._last_decision
        if d is None:
            return {}
        out: dict[str, float] = {}
        for subdir, size_bytes in d.per_subdir_bytes.items():
            # Sanitise the subdir name for use as a label value: replace
            # characters that are invalid in Prometheus label values.
            safe = subdir.replace('"', '').replace('\\', '')
            out[f'maint_storage_used_bytes{{subdir="{safe}"}}'] = float(size_bytes)
        out["maint_storage_total_bytes"] = float(d.total_bytes)
        return out

    # ── Helpers ───────────────────────────────────────────────────

    def _du_per_subdir(self) -> dict[str, int]:
        """Sum bytes recursively per top-level entry under the root.

        Files directly under the root land under the synthetic
        ``"<root>"`` key. Symlinks are NOT followed (defensive against
        accidental loops). Permission errors per-file are silently
        skipped — partial measurement is better than crashing the
        warden tick (operators get the alert from the partial sum).
        """
        out: dict[str, int] = {}
        if not os.path.isdir(self._root):
            return out
        try:
            entries = os.listdir(self._root)
        except OSError:
            return out
        for name in entries:
            full = os.path.join(self._root, name)
            try:
                st = os.lstat(full)
            except OSError:
                continue
            if os.path.islink(full):
                continue
            if not os.path.isdir(full):
                # Top-level file: bucket under the root key.
                out["<root>"] = out.get("<root>", 0) + st.st_size
                continue
            out[name] = self._du_recursive(full)
        return out

    def _du_recursive(self, path: str) -> int:
        total = 0
        for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
            for fn in filenames:
                fp = os.path.join(dirpath, fn)
                try:
                    st = os.lstat(fp)
                except OSError:
                    continue
                if os.path.islink(fp):
                    continue
                total += st.st_size
        return total

    def _alert(self, *, severity: str, usage_pct: float,
               total: int, cap: int) -> Message:
        import secrets
        env = Envelope(
            message_id=self._new_id(),
            trace_id=self._new_id(),
            topic=SEC_ALERT_TOPIC,
            producer=self._source,
            created_at=self._clock_iso(),
            schema_version=1,
            attempt=1,
        )
        payload = {
            "alert_id": secrets.token_hex(8),
            "kind": "maint_storage_pressure",
            "severity": severity,
            "source": self._source,
            "subject": self._root,
            "reason": (
                f"data/maint/ usage {total} bytes / cap {cap} bytes "
                f"({usage_pct:.1f}%); writers {'blocked' if self._blocking else 'allowed'}"
            )[:1024],
            "request_id": None,
            "client_id": None,
            "ip": None,
            "evidence_ref": None,
            "produced_at": self._clock_iso(),
        }
        return Message(envelope=env, payload=payload)


# ── Per-subdir budget audit (binding boot validator) ─────────────────


def assert_subdir_caps_within_global(
    subdir_caps_mb: dict[str, int],
    *,
    global_cap_mb: int | None = None,
) -> None:
    """Boot validation: refuse to start when the sum of per-subdir
    caps exceeds the global cap. ``cfg.maint_storage_total_max_mb``
    is the single source of truth — operators who widen a subdir
    cap past the global headroom hit ``fail_safe_subdir_caps_exceed_global``.

    A global cap of 0 (disabled) skips the check; same for any
    subdir cap of 0 (disabled subdirs do not contribute).
    """
    cap = int(global_cap_mb if global_cap_mb is not None
              else _cfg.maint_storage_total_max_mb)
    if cap <= 0:
        return
    total = sum(max(0, int(v)) for v in subdir_caps_mb.values())
    if total > cap:
        raise RuntimeError(
            f"fail_safe_subdir_caps_exceed_global: "
            f"sum(subdir_caps_mb)={total}MB > "
            f"maint_storage_total_max_mb={cap}MB; "
            f"caps={subdir_caps_mb}"
        )


__all__ = [
    "MaintStorageWarden",
    "MaintStorageDecision",
    "assert_subdir_caps_within_global",
]
