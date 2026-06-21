"""Phase 19 — Security modules.

This sub-package provides:
- Input sanitisation (`input_sanitiser.py`) — catalog field and URL sanitisation
- Pattern matching (`patterns.py`) — prompt-injection and PII detection patterns
- Turkish PII detection (`tr_pii.py`) — Turkish-specific PII redaction and detection
- Endpoint costs (`endpoint_costs.yaml`) — rate-limiting cost mapping
- Injection patterns (`injection_patterns.yaml`) — hot-reloadable pattern rules
"""

from common.security.input_sanitiser import (
    SanitationError,
    SSRFRiskError,
    sanitise_catalog_field,
    sanitise_source_url,
)
from common.security.patterns import (
    CompiledRule,
    PII_CREDIT_CARD_RE,
    PII_EMAIL_RE,
    PII_PATTERNS,
    PII_PHONE_RE,
    PatternFileError,
    RuleSet,
    current_ruleset,
    detect_pii,
    load_ruleset,
    needs_reload,
    reload,
    reset_for_tests,
    resolve_path,
)
from common.security.tr_pii import (
    IBAN_TR_RE,
    PHONE_TR_RE,
    PLATE_TR_RE,
    REDACTED_TOKEN_RE,
    TC_KIMLIK_RE,
    TrPiiSpan,
    VKN_RE,
    detect_tr_pii_spans,
    parse_redacted_tr_pii,
    redact_tr_pii,
)

__all__ = [
    # input_sanitiser
    "SanitationError",
    "SSRFRiskError",
    "sanitise_catalog_field",
    "sanitise_source_url",
    # patterns
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
    # tr_pii
    "IBAN_TR_RE",
    "PHONE_TR_RE",
    "PLATE_TR_RE",
    "REDACTED_TOKEN_RE",
    "TC_KIMLIK_RE",
    "TrPiiSpan",
    "VKN_RE",
    "detect_tr_pii_spans",
    "parse_redacted_tr_pii",
    "redact_tr_pii",
]
