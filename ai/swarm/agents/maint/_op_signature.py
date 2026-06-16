"""ai.swarm.agents.maint - Consumer-side envelope signature verification (Phase 8 S8.14.4 + S8.15.4).

Consumers of ``maint.event.v1`` call :func:`verify_envelope_signature`
before acting on any payload.  Invalid signature or unauthorized kind
result in an ack with ``accepted=false`` and a critical
``sec.alert.v1`` (bypasses debounce per the binding doctrine).

Phase 8 §8.15.4 enhancements:
* Revocation grace window (``cfg.opsctl_key_revocation_grace_s``)
* Age-based auto-revocation (``cfg.opsctl_key_max_age_days`` + grace days)
* Cache-coherent operators registry with atomic swap on reload
* Emergency kill-switch (file presence check per envelope)
* Per-key token-bucket rate-limit (``cfg.opsctl_key_rate_limit_per_min``)

The public operator registry lives at ``infra/maint/opsctl_operators.json``
and is read at runtime (not imported).  The per-subcommand authz map
lives at ``infra/maint/opsctl_authz.yaml``.
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import time
from pathlib import Path
from typing import Any, Optional

try:
    import yaml as _yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

from common.config import Config
from xops.maint.key_id import derive
from ._key_lifecycle import (
    OperatorsCache,
    check_kill_switch,
    get_operators_cache,
    get_rate_bucket,
    is_rate_limit_debounce_expired,
)

_REPO_ROOT = Path(__file__).resolve().parents[5]
_DEFAULT_OPERATORS_FILE = _REPO_ROOT / "infra" / "maint" / "opsctl_operators.json"
_DEFAULT_AUTHZ_FILE = _REPO_ROOT / "infra" / "maint" / "opsctl_authz.yaml"


def _resolve_operators_file(cfg: Config) -> Path:
    p = getattr(cfg, "opsctl_operators_file", "").strip()
    return Path(p).expanduser() if p else _DEFAULT_OPERATORS_FILE


def _resolve_authz_file(cfg: Config) -> Path:
    p = getattr(cfg, "opsctl_authz_file", "").strip()
    return Path(p).expanduser() if p else _DEFAULT_AUTHZ_FILE


def load_operators(operators_file: str | Path) -> dict[str, dict[str, Any]]:
    """Load ``infra/maint/opsctl_operators.json`` -> {key_id: {email, added_at, revoked_at, ...}}.

    Returns an empty dict when the file does not exist (no operators
    registered yet — every signature check will fail, which is the
    correct safe default).
    """
    path = Path(operators_file)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(data.get("operators", {}))


def load_authz(authz_file: str | Path) -> dict[str, Any]:
    """Load ``infra/maint/opsctl_authz.yaml`` -> raw authz mapping.

    Returns the defaults-only structure when the file is missing or
    YAML is unavailable (fail-open for non-destructive ops).
    """
    path = Path(authz_file)
    if not _YAML_AVAILABLE or not path.exists():
        return {"defaults": "*", "overrides": {}}
    try:
        import yaml  # noqa: PLC0415
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {"defaults": "*", "overrides": {}}
    return raw


def _compute_signature(
    key: bytes,
    request_id: str,
    kind: str,
    target: str,
    produced_at: str,
) -> str:
    msg = f"{request_id}|{kind}|{target}|{produced_at}".encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def _parse_iso(ts: str) -> Optional[float]:
    """Parse ISO-8601 timestamp to epoch float; return None on failure."""
    if not ts:
        return None
    try:
        return datetime.datetime.fromisoformat(
            ts.replace("Z", "+00:00")
        ).timestamp()
    except (ValueError, TypeError):
        return None


def _check_revocation_and_age(
    op_entry: dict[str, Any],
    cfg: Config,
    produced_at: str,
) -> tuple[bool, str]:
    """Check revocation grace window and age-based auto-revocation.

    Returns ``(True, "")`` when the key is acceptable.
    Returns ``(False, reason)`` with one of:
    * ``"grace_window_pre_revocation"`` — revoked but within grace window
      (caller should accept but log the grace context).
    * ``"key_revoked"`` — revoked and grace window has passed.
    * ``"key_age_exceeded"`` — key too old, auto-revoked at consumer.

    Note: ``"grace_window_pre_revocation"`` is a non-empty reason but
    ``accepted=True`` — callers handle this specially.
    """
    grace_s = getattr(cfg, "opsctl_key_revocation_grace_s", 60)
    max_age_days = getattr(cfg, "opsctl_key_max_age_days", 365)
    max_age_grace_days = getattr(cfg, "opsctl_key_revocation_grace_days", 30)
    now = time.time()

    # Age-based auto-revocation (§8.15.4 rotation cadence):
    # consumer rejects regardless of revoked_at if key is too old.
    added_at_ts = _parse_iso(op_entry.get("added_at", ""))
    if added_at_ts is not None:
        age_days = (now - added_at_ts) / 86400.0
        hard_limit_days = max_age_days + max_age_grace_days
        if age_days > hard_limit_days:
            return False, "key_age_exceeded"

    # Explicit revocation check with grace window (§8.15.4 revocation):
    revoked_at_str = op_entry.get("revoked_at")
    if revoked_at_str is None:
        return True, ""

    revoked_at_ts = _parse_iso(str(revoked_at_str))
    if revoked_at_ts is None:
        # revoked_at is non-null but unparseable — treat as hard revoke.
        return False, "key_revoked"

    # Determine the timestamp of the envelope being verified.
    # We use "now" as the reference when produced_at is unparseable
    # (conservative: if we can't tell when it was produced, use now).
    produced_ts = _parse_iso(produced_at) or now

    if produced_ts <= revoked_at_ts + grace_s:
        # Within grace window: accept with a non-empty grace reason.
        return True, "grace_window_pre_revocation"

    return False, "key_revoked"


def verify_envelope_signature(
    payload: dict[str, Any],
    cfg: Config,
) -> tuple[bool, str]:
    """Verify ``op_signature`` in the payload against the operators registry.

    Phase 8 §8.15.4 — enhanced with:
    * Emergency kill-switch (rejects ALL envelopes when active).
    * Cache-coherent operators registry (atomic swap on reload).
    * Revocation grace window.
    * Age-based auto-revocation.
    * Per-key token-bucket rate-limit.

    Returns ``(True, "")`` when the signature is valid or signature
    checking is disabled.  Returns ``(False, reason)`` on failure.

    Reasons:
    * ``"kill_switch_active"`` — emergency kill-switch file present.
    * ``"operators_unreadable"`` — operators.json reload failed (fail-safe).
    * ``"op_signature_missing"`` — field absent and require_signature=True
    * ``"op_key_id_missing"`` — key_id absent
    * ``"op_key_id_unknown"`` — key_id not in operators registry
    * ``"key_revoked"`` — revoked and grace window has passed
    * ``"key_age_exceeded"`` — auto-revoked due to age
    * ``"key_rate_limited"`` — per-key token bucket exhausted
    * ``"op_signature_invalid"`` — HMAC mismatch
    """
    if not getattr(cfg, "opsctl_require_signature", True):
        return True, ""

    # ── Kill-switch (§8.15.4 bullet 5) ───────────────────────────────
    if check_kill_switch(cfg):
        return False, "kill_switch_active"

    sig = payload.get("op_signature")
    if not sig:
        return False, "op_signature_missing"

    key_id = payload.get("op_key_id")
    if not key_id:
        return False, "op_key_id_missing"

    key_id_str = str(key_id)

    # ── Cache-coherent operators lookup (§8.15.4 bullet 4) ───────────
    operators_path = _resolve_operators_file(cfg)
    cache: OperatorsCache = get_operators_cache()
    operators, in_fail_safe = cache.get_snapshot(cfg, operators_path)

    if in_fail_safe:
        return False, "operators_unreadable"

    assert operators is not None  # in_fail_safe=False implies operators is set

    op_entry = operators.get(key_id_str)
    if op_entry is None:
        # Cache miss: may have been added after last poll.  Force a reload
        # once before failing (§8.15.4 on-demand reload on unknown key).
        cache.force_reload(operators_path)
        operators, in_fail_safe = cache.get_snapshot(cfg, operators_path)
        if in_fail_safe:
            return False, "operators_unreadable"
        assert operators is not None
        op_entry = operators.get(key_id_str)

    if op_entry is None:
        return False, "op_key_id_unknown"

    # ── Revocation + age check (§8.15.4 bullets 2 & 3) ──────────────
    produced_at = str(payload.get("produced_at", ""))
    rev_ok, rev_reason = _check_revocation_and_age(op_entry, cfg, produced_at)
    if not rev_ok:
        return False, rev_reason
    # grace_window_pre_revocation: key is technically revoked but within grace;
    # we will accept the signature below (rev_ok=True) but the caller can log
    # the grace reason via the non-empty reason string.
    grace_reason = rev_reason  # may be "" or "grace_window_pre_revocation"

    # ── Per-key rate-limit (§8.15.4 bullet 6) ────────────────────────
    rate_bucket = get_rate_bucket(cfg)
    if not rate_bucket.consume(key_id_str):
        return False, "key_rate_limited"

    # ── HMAC verification ─────────────────────────────────────────────
    # For the consumer to verify HMAC, it needs the raw key bytes (symmetric
    # shared-secret model).  In compose/test mode the key path is passed via
    # cfg; in K8s it will be a mounted Secret (Phase 14).
    key_path_str = getattr(cfg, "opsctl_key_path", "").strip()
    if not key_path_str:
        key_path = Path.home() / ".negelir" / "opsctl_key"
    else:
        key_path = Path(key_path_str).expanduser()

    if not key_path.exists():
        return False, "op_key_file_missing"

    raw_key = key_path.read_bytes()[:32]
    operator_email = str(op_entry.get("email", ""))
    if key_id_from_bytes(raw_key, operator_email=operator_email) != key_id_str:
        return False, "op_key_id_unknown"

    expected_sig = _compute_signature(
        raw_key,
        request_id=str(payload.get("request_id", "")),
        kind=str(payload.get("kind", "")),
        target=str(payload.get("target", "")),
        produced_at=produced_at,
    )
    if not hmac.compare_digest(str(sig), expected_sig):
        return False, "op_signature_invalid"

    # Return grace_reason so callers can log it without treating it as failure.
    return True, grace_reason


def key_id_from_bytes(raw_key: bytes, operator_email: str) -> str:
    """Derive canonical public key-id bound to operator identity + key bytes."""
    return derive(operator_email=operator_email, key_bytes=raw_key)


def check_authz(
    key_id: str,
    kind: str,
    cfg: Config,
) -> tuple[bool, str]:
    """Check per-subcommand authorization for ``key_id`` on ``kind``.

    Returns ``(True, "")`` when authorized.
    Returns ``(False, "op_not_authorized")`` when not.
    """
    if not getattr(cfg, "opsctl_require_signature", True):
        return True, ""

    authz = load_authz(_resolve_authz_file(cfg))
    overrides = authz.get("overrides", {})
    defaults = authz.get("defaults", "*")

    if kind in overrides:
        allowed = overrides[kind]
    else:
        allowed = defaults

    if allowed == "*":
        return True, ""
    if isinstance(allowed, list) and key_id in allowed:
        return True, ""
    return False, "op_not_authorized"


def gate_op_envelope(
    payload: dict[str, Any],
    cfg: Any,
) -> tuple[bool, str, str]:
    """Combined signature-then-authz gate for ``maint.event.v1`` consumers.

    Skipped for producer-driven signals that carry no opsctl fields
    (``op_key_id`` / ``op_signature`` absent) — they are NOT operator
    commands and carry no key material to verify.

    Returns ``(True, "", "")`` when the envelope passes both gates or
    when the envelope has no opsctl fields.
    On the first failure returns ``(False, reason, alert_kind)`` where:

    * ``alert_kind == "opsctl_signature_invalid"`` — any HMAC failure.
    * ``alert_kind == "opsctl_unauthorized"`` — key valid but not
      authorized for the requested kind.

    Agents MUST on failure:
    * Ack with ``accepted=False, reason=<reason>``.
    * Emit ``sec.alert.v1{kind=<alert_kind>, severity="critical"}``.
    """
    # Producer-driven signals (retrain_request, scale_decision, etc.) carry
    # no op_key_id / op_signature — skip the gate entirely.
    if not (payload.get("op_key_id") or payload.get("op_signature")):
        return True, "", ""

    sig_ok, sig_reason = verify_envelope_signature(payload, cfg)
    if not sig_ok:
        return False, sig_reason, "opsctl_signature_invalid"

    key_id = str(payload.get("op_key_id") or "")
    kind = str(payload.get("kind") or "")
    authz_ok, authz_reason = check_authz(key_id, kind, cfg)
    if not authz_ok:
        return False, authz_reason, "opsctl_unauthorized"

    return True, "", ""


__all__ = [
    "verify_envelope_signature",
    "check_authz",
    "load_operators",
    "load_authz",
    "key_id_from_bytes",
    "gate_op_envelope",
]
