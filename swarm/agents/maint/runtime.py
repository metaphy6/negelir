"""Phase 8 §8.2 — `RuntimeController` implementations.

The scaler's decision is one half of the loop; the runtime call is
the other. We keep them in separate modules so the scaler's
test suite can drive any controller (incl. `NoopController`) and the
production wiring lives in one place.

Three implementations land here:

* :class:`NoopController` — records actions in memory and returns
  success. Default for ``cfg.maint_runtime=none``.
* :class:`ComposeController` — invokes ``docker compose --scale`` via
  :mod:`subprocess`. Used in dev / on-prem ``cfg.maint_runtime=compose``.
* ``K8sController`` — Phase 14, NOT implemented yet. Selecting
  ``cfg.maint_runtime=k8s`` raises ``NotImplementedError`` at the
  factory boundary so a misconfigured prod refuses to start loud.

The factory ``make_runtime_controller`` is what the boot path calls
to materialise a controller for the active ``cfg.maint_runtime``;
the scaler accepts an injected controller too (test injection).
"""
from __future__ import annotations

import logging
import os
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from typing import Protocol

from common.config import cfg as _cfg

_log = logging.getLogger("swarm.agents.maint.runtime")


class RuntimeController(Protocol):
    """Pluggable shim that turns a ``(target, replicas)`` decision
    into a real platform action.

    Implementations MUST be idempotent for ``apply(t, n)`` calls
    issued back-to-back with the same ``(t, n)`` (the scaler's
    hysteresis already coalesces, but the runtime should not amplify
    a missed coalesce into a real outage). They MUST never raise on
    the happy path; failures are reported via the bool return so the
    scaler can log + emit ``scale_throttled`` instead of crashing.
    """

    name: str

    def apply(self, target: str, replicas: int) -> bool:
        """Return True iff the controller accepted the action."""
        ...


# ── Noop ─────────────────────────────────────────────────────────────
class NoopController:
    """Default — records actions, never touches the platform.

    Useful for tests, for shadow-mode rollout
    (``cfg.maint_runtime=none``), and for a leader replica that has no
    real driver wired. Records every call so a caller can introspect
    what the scaler decided without observing the wire.
    """

    name = "noop"

    def __init__(self) -> None:
        self.applied: list[tuple[str, int]] = []

    def apply(self, target: str, replicas: int) -> bool:
        self.applied.append((target, replicas))
        return True


# ── Compose ──────────────────────────────────────────────────────────
@dataclass
class ComposeController:
    """``docker compose -f <file> up -d --scale <svc>=N --no-recreate``.

    The compose file path comes from ``cfg.maint_scaler_compose_file``
    (boot validation in ``cfg`` already refuses if the file does not
    exist). Subprocess runs with ``check=False`` so a non-zero exit
    surfaces as ``apply()->False`` instead of a raised exception —
    the scaler logs + emits ``scale_throttled{reason=runtime_failed}``
    and tries again on the next decision tick.

    Explicitly forbidden in cloud (Phase 14 swaps to the K8s
    controller). The boot-time selector + the compose-file presence
    check together act as a guard rail; this class refuses to start
    if the docker binary is not on PATH.
    """

    compose_file: str
    timeout_s: float = 30.0
    name: str = field(default="compose")
    # Subprocess hook for tests (defaults to the real subprocess).
    _runner: object = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.compose_file:
            raise ValueError("ComposeController.compose_file must be set")
        if not os.path.exists(self.compose_file):
            raise FileNotFoundError(
                f"compose file not found: {self.compose_file!r}"
            )
        if self._runner is None:
            self._runner = subprocess.run

    def apply(self, target: str, replicas: int) -> bool:
        if not target or replicas < 0:
            return False
        cmd = [
            "docker", "compose",
            "-f", self.compose_file,
            "up", "-d", "--no-recreate",
            "--scale", f"{target}={int(replicas)}",
        ]
        started = time.monotonic()
        try:
            res = self._runner(  # type: ignore[misc]
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=float(self.timeout_s),
            )
        except subprocess.TimeoutExpired:
            _log.warning(
                "compose-controller: timeout after %.1fs — %s",
                self.timeout_s, shlex.join(cmd),
            )
            return False
        except FileNotFoundError:
            # docker binary missing — refuse loud, never silent-success.
            _log.error(
                "compose-controller: docker binary not on PATH "
                "(check container image)"
            )
            return False
        except Exception:  # pragma: no cover (defensive only)
            _log.exception("compose-controller: unexpected failure")
            return False
        ok = res.returncode == 0
        if not ok:
            _log.warning(
                "compose-controller: exit=%d stderr=%s",
                res.returncode, (res.stderr or "")[:512],
            )
        else:
            _log.info(
                "compose-controller: applied %s=%d (%.2fs)",
                target, replicas, time.monotonic() - started,
            )
        return ok


# ── Factory ──────────────────────────────────────────────────────────
def make_runtime_controller() -> RuntimeController:
    """Return the controller selected by ``cfg.maint_runtime``.

    Failure modes are loud:

    * ``cfg.maint_runtime=k8s`` raises ``NotImplementedError`` (the
      Phase 14 K8s adapter is not in tree yet — refusing is safer
      than silently falling back to noop).
    * An unknown value raises ``ValueError`` (cfg validation should
      catch this earlier, this is defence-in-depth).
    """
    runtime = str(_cfg.maint_runtime).strip().lower()
    if runtime == "none":
        return NoopController()
    if runtime == "compose":
        return ComposeController(
            compose_file=str(_cfg.maint_scaler_compose_file),
            timeout_s=float(_cfg.maint_scaler_runtime_timeout_s),
        )
    if runtime == "k8s":
        raise NotImplementedError(
            "maint_runtime='k8s' is reserved for Phase 14; the K8s "
            "controller is not in tree yet (refuse rather than fall "
            "back to noop in prod)."
        )
    raise ValueError(
        f"maint_runtime={runtime!r} is not one of: none, compose, k8s"
    )


__all__ = [
    "ComposeController",
    "NoopController",
    "RuntimeController",
    "make_runtime_controller",
]
