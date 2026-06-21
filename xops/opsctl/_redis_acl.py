"""xops.opsctl - Redis ACL boot-validation gate (Phase 8 S8.14.4).

opsctl MUST authenticate to Redis as the dedicated ``negelir_opsctl``
ACL user, not the general application user.  The application user has
full bus access; ``negelir_opsctl`` is restricted to ``maint.event.v1``
publish + ``maint.ack.v1`` subscribe (no ``+set``, no ``+del``, no
``+evalsha``).  No ``+get``/``+set``/``+del``, no access to other streams.

At startup (before any publish), :func:`assert_opsctl_redis_user` calls
``ACL WHOAMI`` through the bus abstraction and refuses if the response
differs from ``cfg.opsctl_redis_expected_user``.

Boundary rule: this module MUST NOT import ``redis`` directly.
"""
from __future__ import annotations

import sys
from typing import Any, Optional

from common.config import Config

from ._exit_codes import ExitCode


def assert_opsctl_redis_user(
    bus: Any,
    cfg: Optional[Config] = None,
) -> Optional[int]:
    """Run the ACL WHOAMI boot gate.

    Returns ``None`` when the check passes (correct user or unchecked).
    Returns :attr:`ExitCode.FAIL_SAFE_WRONG_REDIS_USER` as an ``int``
    when the authenticated user is not ``cfg.opsctl_redis_expected_user``.
    """
    if cfg is None:
        cfg = Config()

    get_username = getattr(bus, "get_redis_username", None)
    if get_username is None:
        # Bus implementation predates S8.14.4 - skip check silently.
        return None

    actual = get_username()
    if actual is None:
        sys.stderr.write(
            "opsctl: ACL WHOAMI unavailable - cannot verify Redis user; "
            "refusing to continue (fail_safe_wrong_redis_user)\n"
        )
        return int(ExitCode.FAIL_SAFE_WRONG_REDIS_USER)

    expected = cfg.opsctl_redis_expected_user
    if actual != expected:
        sys.stderr.write(
            f"opsctl: wrong Redis user - expected {expected!r}, "
            f"got {actual!r}; refusing (fail_safe_wrong_redis_user)\n"
        )
        return int(ExitCode.FAIL_SAFE_WRONG_REDIS_USER)

    return None


__all__ = ["assert_opsctl_redis_user"]
