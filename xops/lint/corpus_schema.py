"""
Phase 12.2 — Adversarial corpus schema (expected_catcher binding).

Defines the schema for adversarial corpus entries. Each entry:
- Maps to a trust boundary (via expected_catcher)
- Declares its owning phase
- References a catalogue ID
- Is synthetic-only (no captured PII)

Inherits governance pattern from Phase 10 §10.33.4 + Phase 13 §13.48.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, List


class CatcherKind(str, Enum):
    """Enumeration of catcher kinds (see sec.alert.v1 KNOWN_SEC_ALERT_KINDS)."""
    # Phase 7: sec.input.v1
    LENGTH_VIOLATION = "input_length_violation"
    SCRIPT_INJECTION = "script_injection"
    HOMOGLYPH_ABUSE = "homoglyph_abuse"
    RTL_FLIP = "rtl_flip_abuse"
    
    # Phase 7: sec.scrape.v1
    DOM_ANOMALY = "dom_anomaly"
    SIZE_DELTA = "size_delta_pct"
    COMPRESSION_BOMB = "compression_bomb"
    
    # Phase 7: sec.rate.v1
    RATE_BURST = "rate_burst"
    CREDENTIAL_STUFFING = "credential_stuffing"
    
    # Generic
    QUARANTINE = "quarantine"
    UNKNOWN = "unknown"


@dataclass
class ExpectedCatcher:
    """Specification of the catcher that must catch this adversarial input."""
    agent: str  # e.g. "sec.input.v1", "sec.scrape.v1"
    kind: str   # enum value from CatcherKind or open-ended string
    
    def validate(self) -> bool:
        """Ensure kind is a valid catcher signal."""
        # TODO: validate against KNOWN_SEC_ALERT_KINDS
        return True


@dataclass
class AdversarialCorpusEntry:
    """A single adversarial corpus entry."""
    id: str  # e.g. "adv-001", globally unique within corpus set
    text: str  # The adversarial input (Turkish or English)
    expected_catcher: ExpectedCatcher  # Which agent must catch this
    owning_phase: int  # e.g. 10 (the phase that registered the test)
    catalogue_family: str  # e.g. "P12-7.1", "P12-10"
    category: str  # e.g. "prompt_injection", "html_bomb", "homoglyph"
    severity: str  # "info" | "warn" | "error" | "critical"
    provenance: Optional[str] = None  # Public CVE/technique the shape models
    notes: str = ""  # Human-readable description


class CorpusGovernanceSidecar:
    """
    Schema for corpus.yaml governance sidecar.
    
    Mirrors Phase 10 §10.33.4. Each corpus directory carries:
    - seed: deterministic generation seed
    - sha256: content hash of all entries
    - provenance_entries: per-family technique/CVE  
    - reviewers: two sign-offs (security families need sec CODEOWNER)
    - pii_scrub: independent verifier stamp (reuses Phase 10 PII detectors)
    """
    
    version: int = 1
    seed: int  # e.g. 42 (reproducible generation)
    sha256: str  # hash of corpus payload files
    
    # Per-family metadata
    families: dict  # {family_id: {technique, cve, date_added}}
    reviewers: List[str]  # ["alice@example.com", "bob@example.com"]
    pii_scrub_timestamp: Optional[str] = None  # ISO 8601 UTC, e.g. "2026-06-08T14:40:00+00:00"
    pii_scrub_tool_version: str = "xops/lint/adversarial_pii_scan.py v1.0"


def template_corpus_yaml() -> str:
    """Generate a template corpus.yaml for a new corpus directory."""
    return """# Phase 12 §12.2.1 — Corpus governance sidecar

# Schema version
version: 1

# Deterministic generation seed (for reproducibility and diffability)
seed: 42

# Content hash: sha256 of all entries in this corpus (detect drift)
# Re-generate via: make verify.adversarial-corpora
sha256: "TBD"

# Provenance: per family, the public technique/CVE the shape models
provenance:
  prompt_injection:
    - technique: "Prompt injection via 'ignore previous instructions'"
      cve: ~
      date_added: "2026-06-08"
  
  html_dom:
    - technique: "Compression bomb (zip bomb, gzip bomb)"
      cve: "CWE-409"
      date_added: "2026-06-08"

# Two required reviewers (security-relevant families require sec CODEOWNER)
reviewers:
  - "security-team@example.com"
  - "phase-12-lead@example.com"

# PII scrub verification (independent re-scan via xops/lint/adversarial_pii_scan.py)
pii_scrub:
  timestamp: "2026-06-08T14:40:00+00:00"
  tool_version: "xops/lint/adversarial_pii_scan.py v1.0"
  status: "passed"
  notes: "No TR-PII (kimlik, IBAN, phone, plate) detected. No real-looking secrets."
"""


if __name__ == "__main__":
    print("Corpus schema loaded successfully")
    print("Template corpus.yaml:")
    print(template_corpus_yaml())
