"""Phase 7 §7.1 — security primitives shared by Go gateway + Python agents."""

from .patterns import (
    CompiledRule,
    PatternFileError,
    PII_CREDIT_CARD_RE,
    PII_EMAIL_RE,
    PII_PATTERNS,
    PII_PHONE_RE,
    RuleSet,
    current_ruleset,
    detect_pii,
    load_ruleset,
    needs_reload,
    reload,
    reset_for_tests,
    resolve_path,
)

__all__ = [
    "CompiledRule",
    "PatternFileError",
    "PII_CREDIT_CARD_RE",
    "PII_EMAIL_RE",
    "PII_PATTERNS",
    "PII_PHONE_RE",
    "RuleSet",
    "current_ruleset",
    "detect_pii",
    "load_ruleset",
    "needs_reload",
    "reload",
    "reset_for_tests",
    "resolve_path",
]
