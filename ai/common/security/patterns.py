"""Phase 7 §7.1 — defensive-pattern engine.

This module owns the **deterministic** half of `sec.input.v1`'s
classification pipeline:

1. The Go gateway (Phase 9) and the Python defense-in-depth check
   in `sec.input.v1` both call :func:`current_ruleset` to get the
   compiled regex set.
2. A background poller (driven by the agent — see
   `SecInputAgent._maybe_reload_patterns`) checks the file's mtime
   every ``cfg.sec_input_pattern_reload_s`` seconds and atomically
   swaps in a new :class:`RuleSet` if the file changed and parses
   cleanly.
3. The cross-pod fan-out topic ``sec.config.v1`` (`topics.SEC_CONFIG`)
   carries the new sha256; subscribing replicas use it as a hint to
   reload immediately rather than waiting for the next poll tick.

The loader is intentionally hardened:

* parse failure or schema mismatch leaves the previous ruleset in
  place (fail-open) and the caller surfaces a `pattern_reload`
  SecAlert with severity=`error`;
* every ``id`` is enforced unique and snake_case;
* every ``severity`` / ``kind`` is enforced against an allow-list;
* every ``pattern`` is compiled with ``re.IGNORECASE``; if any
  pattern fails to compile the WHOLE load is rejected (no partial
  rulesets) — this is by design so a typo cannot silently drop a
  rule.

Thread-safety: :class:`RuleSet` instances are immutable; readers
take a reference and may use it without locking. The shared
:func:`current_ruleset` getter is guarded by a module-level
``_LOCK`` only on swap.
"""
from __future__ import annotations

import hashlib
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple

import yaml

# ── Bundled default path. Operators may override via
# `cfg.sec_input_pattern_path` (empty = use this file).
_DEFAULT_PATH = Path(__file__).resolve().parent / "injection_patterns.yaml"

_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_ALLOWED_SEVERITIES = frozenset({"info", "warn", "error", "critical"})

# Subset of KNOWN_SEC_ALERT_KINDS that a YAML rule may bind to. We
# intentionally allow only the input-side kinds here — a YAML rule
# cannot fire `rate_throttled` (that belongs to sec.rate.v1) or
# scrape kinds. Keeping the allow-list tight makes the YAML's
# blast radius obvious from the file alone.
_ALLOWED_RULE_KINDS = frozenset({
    "prompt_injection",
    "homoglyph_attack",
    "language_spoof",
    "payload_oversize",
    "encoded_redirect",
})


@dataclass(frozen=True)
class CompiledRule:
    """A single regex rule, post-compile.

    Immutable so a worker thread can hold a reference safely while
    the loader swaps in a new RuleSet.
    """

    rule_id: str
    severity: str
    kind: str
    reason: str
    pattern_src: str
    pattern: re.Pattern[str] = field(repr=False)


@dataclass(frozen=True)
class RuleSet:
    """An immutable, ready-to-evaluate set of rules + provenance.

    `sha256` is the digest of the FILE BYTES (not of the parsed
    structure) so an operator can verify the on-disk file matches
    what the running agent loaded by running ``sha256sum`` from
    the shell.
    """

    rules: Tuple[CompiledRule, ...]
    sha256: str
    mtime_ns: int
    source_path: str
    version: int

    def match(self, text: str) -> Optional[CompiledRule]:
        """Return the first rule that matches ``text``, or None.

        Iteration order = file order, which gives operators control
        over which rule "wins" for a given payload.
        """
        if not text:
            return None
        for r in self.rules:
            if r.pattern.search(text):
                return r
        return None

    def all_matches(self, text: str) -> Tuple[CompiledRule, ...]:
        """Return every rule that matches ``text`` (file order)."""
        if not text:
            return ()
        return tuple(r for r in self.rules if r.pattern.search(text))


# ── Module state ────────────────────────────────────────────────
_LOCK = threading.Lock()
_CURRENT: Optional[RuleSet] = None


class PatternFileError(ValueError):
    """Raised when the YAML on disk fails validation.

    The agent catches this, leaves the previous RuleSet in place,
    and emits a `pattern_reload` SecAlert with severity=`error`.
    The exception's ``str`` is the diagnostic that lands in the
    alert's ``reasons`` list — keep it short and operator-friendly.
    """


def resolve_path(path: Optional[str]) -> Path:
    """Resolve the configured path, falling back to the bundled file."""
    if path:
        return Path(path).expanduser().resolve()
    return _DEFAULT_PATH


_resolve_path = resolve_path  # back-compat alias


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _parse_and_compile(raw: bytes, source_path: str, mtime_ns: int) -> RuleSet:
    """Parse YAML bytes and return a fully-compiled RuleSet.

    Raises :class:`PatternFileError` for any structural problem.
    """
    try:
        doc = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise PatternFileError(f"yaml parse failed: {exc}") from exc

    if not isinstance(doc, dict):
        raise PatternFileError("top-level must be a mapping")

    version = doc.get("version", 0)
    if not isinstance(version, int) or version < 1:
        raise PatternFileError(f"version must be an int >= 1 (got {version!r})")

    raw_rules = doc.get("patterns")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise PatternFileError("`patterns` must be a non-empty list")

    seen_ids: set[str] = set()
    compiled: list[CompiledRule] = []
    for idx, item in enumerate(raw_rules):
        if not isinstance(item, dict):
            raise PatternFileError(f"rule[{idx}] must be a mapping")

        rule_id = item.get("id")
        if not isinstance(rule_id, str) or not _ID_RE.match(rule_id):
            raise PatternFileError(
                f"rule[{idx}].id must match {_ID_RE.pattern!r} (got {rule_id!r})"
            )
        if rule_id in seen_ids:
            raise PatternFileError(f"duplicate rule id {rule_id!r}")
        seen_ids.add(rule_id)

        pat = item.get("pattern")
        if not isinstance(pat, str) or not pat:
            raise PatternFileError(f"rule[{rule_id}].pattern must be a non-empty string")
        try:
            compiled_pat = re.compile(pat, re.IGNORECASE)
        except re.error as exc:
            raise PatternFileError(
                f"rule[{rule_id}].pattern failed to compile: {exc}"
            ) from exc

        severity = item.get("severity", "warn")
        if severity not in _ALLOWED_SEVERITIES:
            raise PatternFileError(
                f"rule[{rule_id}].severity={severity!r} not in {sorted(_ALLOWED_SEVERITIES)}"
            )

        kind = item.get("kind", "prompt_injection")
        if kind not in _ALLOWED_RULE_KINDS:
            raise PatternFileError(
                f"rule[{rule_id}].kind={kind!r} not in {sorted(_ALLOWED_RULE_KINDS)}"
            )

        reason = item.get("reason", rule_id)
        if not isinstance(reason, str):
            raise PatternFileError(f"rule[{rule_id}].reason must be a string")

        compiled.append(CompiledRule(
            rule_id=rule_id,
            severity=severity,
            kind=kind,
            reason=reason,
            pattern_src=pat,
            pattern=compiled_pat,
        ))

    return RuleSet(
        rules=tuple(compiled),
        sha256=_sha256_bytes(raw),
        mtime_ns=mtime_ns,
        source_path=source_path,
        version=version,
    )


def load_ruleset(path: Optional[str] = None) -> RuleSet:
    """Read + parse + compile the ruleset at ``path``.

    Raises :class:`PatternFileError` on any failure (the caller is
    expected to keep the previous ruleset and surface an alert).
    Caller-supplied empty / None path → the bundled default file.
    """
    p = _resolve_path(path)
    try:
        raw = p.read_bytes()
        st = p.stat()
    except OSError as exc:
        raise PatternFileError(f"cannot read {p}: {exc}") from exc
    return _parse_and_compile(raw, str(p), st.st_mtime_ns)


def current_ruleset(path: Optional[str] = None) -> RuleSet:
    """Return the currently-loaded RuleSet, loading on first call.

    Subsequent calls return the same instance until :func:`reload`
    swaps a new one in. If the first-load fails the exception
    propagates — the agent treats first-load failure as fatal
    because there is no previous ruleset to fall back to.
    """
    global _CURRENT
    if _CURRENT is None:
        with _LOCK:
            if _CURRENT is None:
                _CURRENT = load_ruleset(path)
    return _CURRENT


def reload(path: Optional[str] = None) -> Tuple[RuleSet, bool]:
    """Re-read the file; if it changed AND parses, swap it in.

    Returns ``(ruleset, did_swap)``. ``did_swap`` is ``False`` when
    the file is byte-identical to the current one — the caller
    can suppress a `pattern_reload` alert in that case. Raises
    :class:`PatternFileError` if the new file fails validation
    (the caller keeps the old ruleset and emits an `error` alert).
    """
    global _CURRENT
    new = load_ruleset(path)
    with _LOCK:
        prev = _CURRENT
        if prev is not None and prev.sha256 == new.sha256:
            # byte-identical — no swap, no alert
            return prev, False
        _CURRENT = new
        return new, True


def needs_reload(path: Optional[str] = None) -> bool:
    """Cheap mtime-based check used by the polling loop.

    Returns ``True`` when the file's mtime is newer than the
    currently-loaded RuleSet's recorded mtime. False on any I/O
    error (fail-open: the next poll cycle will retry).
    """
    if _CURRENT is None:
        return True
    p = resolve_path(path)
    try:
        return p.stat().st_mtime_ns > _CURRENT.mtime_ns
    except OSError:
        return False


def reset_for_tests() -> None:
    """Drop the cached singleton — TESTS ONLY."""
    global _CURRENT
    with _LOCK:
        _CURRENT = None


# ── PII detection patterns (single source; §10.5, §10.9) ─────────────────
#
# Used by the NLP entity extractor (§10.5 PII guard at extraction) and
# the proofreader (§10.9 PII redaction).  Keep in sync with any equivalent
# patterns in the Go gateway (server/internal/sec/).
#
# Patterns match on the *joined token text* of a CRF span (for extraction)
# and on the full answer text (for proofreading).  Turkish phone formats:
#   0[0-9]{10}   (0 + 10 digits, e.g. 0532 123 45 67)
#   +90 / 0090   (international prefix)
# Credit card covers Visa 13/16, Mastercard, Amex, Discover.

PII_PHONE_RE: re.Pattern[str] = re.compile(
    r"(?<!\d)"
    r"(?:"
    r"(?:\+90|0090)[\s\-]?[0-9]{3}[\s\-]?[0-9]{3}[\s\-]?[0-9]{2}[\s\-]?[0-9]{2}"
    r"|0[0-9]{3}[\s\-]?[0-9]{3}[\s\-]?[0-9]{2}[\s\-]?[0-9]{2}"
    r")"
    r"(?!\d)",
    re.ASCII,
)

PII_EMAIL_RE: re.Pattern[str] = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    re.ASCII,
)

PII_CREDIT_CARD_RE: re.Pattern[str] = re.compile(
    r"(?<!\d)"
    r"(?:"
    r"4[0-9]{3}[\s\-]?[0-9]{4}[\s\-]?[0-9]{4}[\s\-]?[0-9]{4}"   # Visa 16
    r"|4[0-9]{3}[\s\-]?[0-9]{4}[\s\-]?[0-9]{4}[\s\-]?[0-9]"      # Visa 13 (4-4-4-1)
    r"|4[0-9]{3}[\s\-]?[0-9]{4}[\s\-]?[0-9]{5}"                   # Visa 13 (4-4-5)
    r"|5[1-5][0-9]{2}[\s\-]?[0-9]{4}[\s\-]?[0-9]{4}[\s\-]?[0-9]{4}"  # Mastercard
    r"|3[47][0-9]{2}[\s\-]?[0-9]{6}[\s\-]?[0-9]{5}"               # Amex
    r"|6(?:011|5[0-9]{2})[\s\-]?[0-9]{4}[\s\-]?[0-9]{4}[\s\-]?[0-9]{4}"  # Discover
    r")"
    r"(?!\d)",
    re.ASCII,
)

# Ordered tuple for a single-pass check: (kind_name, compiled_pattern).
# First match wins.
PII_PATTERNS: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    ("phone", PII_PHONE_RE),
    ("email", PII_EMAIL_RE),
    ("credit_card", PII_CREDIT_CARD_RE),
)


def detect_pii(text: str) -> Optional[str]:
    """Return the PII kind name if *text* matches any PII pattern, else None.

    Used by the NLP entity extractor (§10.5 PII guard at extraction) and
    the proofreader (§10.9 PII redaction).  This is the **single source**
    for PII regex definitions across the Python codebase.

    Returns one of ``"phone"``, ``"email"``, ``"credit_card"``, or ``None``.
    """
    for kind, pattern in PII_PATTERNS:
        if pattern.search(text):
            return kind
    return None


__all__ = [
    "CompiledRule",
    "RuleSet",
    "PatternFileError",
    "PII_CREDIT_CARD_RE",
    "PII_EMAIL_RE",
    "PII_PATTERNS",
    "PII_PHONE_RE",
    "detect_pii",
    "load_ruleset",
    "current_ruleset",
    "reload",
    "needs_reload",
    "reset_for_tests",
    "resolve_path",
]
