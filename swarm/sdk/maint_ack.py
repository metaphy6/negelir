"""Phase 8 §8.1 — wire-level size-cap helper for ``maint.ack.v1``.

Every ``maint.ack.v1`` payload landing on the bus must fit inside
``cfg.maint_ack_payload_max_bytes`` (default 4096) so a misbehaving
consumer cannot wedge the ops console's wait-for-acks loop with a
DoS-shaped giant ack. The cap is enforced at emit time by
:func:`build_capped_maint_ack`; over-cap acks are truncated by
dropping ``details`` and setting ``reason='truncated:<N>'`` (where
``N`` is the original size of the rejected ``details`` JSON), and
the caller is signalled to publish a debounced
``sec.alert.v1{kind=maint_ack_oversize, severity=warn}`` so the
operator notices and the consumer's emitter can be hardened.

Boundary discipline:

* Truncation is **never** silent — the operator sees the
  ``reason='truncated:<N>'`` field on the ack itself AND a
  paired ``sec.alert.v1`` (debounced per ``accepted_by`` so a
  chronically-oversize consumer doesn't flood the bus).
* ``reason`` itself is independently capped at
  ``cfg.maint_ack_reason_max_bytes`` (default 512); over-cap
  reason strings are clipped with an ``…`` ellipsis suffix.
  This protects against a consumer stuffing the diagnostic
  payload into ``reason`` to dodge the ``details`` cap.
* The helper does NOT publish anything — it returns a notice
  the caller can debounce + publish through its own bus handle.
  This keeps the SDK helper bus-agnostic (matches the rest of
  ``ai.swarm.sdk`` design — emit-side helpers are pure).

The helper is the producer-side companion to the
:class:`~ai.swarm.agents.payloads.MaintAck` dataclass, which is
the in-process view (no enforcement; trust boundary is the wire).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from common.config import Config
from swarm.agents.payloads import MaintAck

__all__ = [
    "MaintAckOversizeNotice",
    "build_capped_maint_ack",
]


_TRUNCATION_ELLIPSIS = "…"


@dataclass(frozen=True)
class MaintAckOversizeNotice:
    """Side-channel signal for the caller to publish a debounced
    ``sec.alert.v1{kind=maint_ack_oversize}``.

    The caller is expected to fold ``accepted_by`` into its debounce
    key so each chronically-oversize consumer fires once per debounce
    window (not once per request). The fields here are exactly what
    the alert payload carries.
    """

    accepted_by: str
    request_id: str
    original_details_bytes: int
    capped_payload_bytes: int
    cap: int


def _serialize_payload(payload: Mapping[str, Any]) -> bytes:
    # Sort keys so the cap check is deterministic regardless of
    # insertion order. UTF-8 byte length matches what the bus codec
    # actually serialises (cf. ai.swarm.sdk.codec).
    return json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")


def _clip_reason(reason: str, *, cap: int) -> str:
    if cap <= 0 or len(reason.encode("utf-8")) <= cap:
        return reason
    # Reserve one byte for the ellipsis (UTF-8 encoded as 3 bytes,
    # so we shave 3 from the byte budget). Walk back by characters,
    # not bytes, to avoid splitting a UTF-8 sequence.
    suffix = _TRUNCATION_ELLIPSIS
    suffix_bytes = len(suffix.encode("utf-8"))
    budget = cap - suffix_bytes
    if budget <= 0:
        # Cap is so small the suffix alone would not fit — return
        # an empty string rather than a malformed marker.
        return ""
    out = reason
    while len(out.encode("utf-8")) > budget:
        out = out[:-1]
    return out + suffix


def build_capped_maint_ack(
    *,
    request_id: str,
    accepted: bool,
    accepted_by: str,
    processed_at: str,
    attempt: int = 1,
    reason: str = "",
    details: Optional[Mapping[str, Any]] = None,
    cfg: Optional[Config] = None,
) -> tuple[MaintAck, Optional[MaintAckOversizeNotice]]:
    """Construct a :class:`MaintAck` whose serialised payload is
    guaranteed to fit inside ``cfg.maint_ack_payload_max_bytes``.

    When ``details`` would push the payload over the cap, it is
    dropped and ``reason`` is rewritten to
    ``f"truncated:{original_details_bytes}"`` (preserving any
    operator-supplied prefix as ``"<orig> | truncated:<N>"`` so
    forensic context is not lost). The caller receives a
    :class:`MaintAckOversizeNotice` it can debounce + publish on
    ``sec.alert.v1``.

    The returned :class:`MaintAck` always satisfies the wire-level
    cap — callers do not need to re-check.
    """
    cfg = cfg if cfg is not None else Config()
    payload_cap = int(cfg.maint_ack_payload_max_bytes)
    reason_cap = int(cfg.maint_ack_reason_max_bytes)

    safe_reason = _clip_reason(reason or "", cap=reason_cap)
    safe_details: Optional[dict[str, Any]] = (
        dict(details) if details is not None else None
    )

    # First attempt: serialise with both reason and details intact.
    candidate = MaintAck(
        request_id=request_id,
        accepted=accepted,
        accepted_by=accepted_by,
        processed_at=processed_at,
        attempt=attempt,
        reason=safe_reason,
        details=safe_details,
    )
    serialised = _serialize_payload(candidate.as_dict())
    if len(serialised) <= payload_cap:
        return candidate, None

    # Over cap. Drop details (the most likely culprit) and rewrite
    # the reason to surface the truncation; preserve any
    # operator-supplied prefix to keep forensic context.
    if safe_details is not None:
        original_details_bytes = len(
            _serialize_payload({"details": safe_details})
        )
    else:
        # Reason alone overflowed — no details to drop. Still
        # report a notice so the operator hardens the producer.
        original_details_bytes = 0

    truncation_marker = f"truncated:{original_details_bytes}"
    if safe_reason:
        merged = f"{safe_reason} | {truncation_marker}"
    else:
        merged = truncation_marker
    capped_reason = _clip_reason(merged, cap=reason_cap)

    capped = MaintAck(
        request_id=request_id,
        accepted=accepted,
        accepted_by=accepted_by,
        processed_at=processed_at,
        attempt=attempt,
        reason=capped_reason,
        details=None,
    )
    capped_serialised = _serialize_payload(capped.as_dict())
    notice = MaintAckOversizeNotice(
        accepted_by=accepted_by,
        request_id=request_id,
        original_details_bytes=original_details_bytes,
        capped_payload_bytes=len(capped_serialised),
        cap=payload_cap,
    )
    return capped, notice
