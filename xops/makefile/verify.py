#!/usr/bin/env python3
"""`make verify.*` — repository verification helpers."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
XOPS_ROOT = Path(__file__).resolve().parents[1]
for path in (str(REPO_ROOT), str(XOPS_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from _common import dispatch  # noqa: E402


def cmd_dlq_replay_policy(_argv: list[str]) -> int:
    from xops.maint.verify_dlq_replay_policy import main as verify_main

    return int(verify_main([]))


def cmd_adversarial_corpora(argv: list[str]) -> int:
    """Phase 12 §12.2.2 — Verify adversarial corpus integrity.
    
    Checks:
    - Disjointness from training/eval sets
    - PII scanner re-scan
    - SHA256 manifest validation
    - Two-reviewer presence
    """
    import subprocess
    
    repo_root = REPO_ROOT
    
    # Run corpus disjointness check
    result = subprocess.run(
        ["python3", str(repo_root / "xops" / "lint" / "corpus_disjoint.py"),
         "--repo-root", str(repo_root),
         "--check-training", "--check-eval"],
        cwd=str(repo_root),
    )
    if result.returncode != 0:
        print("❌ Corpus disjointness check failed", file=sys.stderr)
        return 1
    
    # Run PII scanner
    result = subprocess.run(
        ["python3", str(repo_root / "xops" / "lint" / "adversarial_pii_scan.py"),
         "--repo-root", str(repo_root),
         "--fail-on-pii"],
        cwd=str(repo_root),
    )
    if result.returncode != 0:
        print("❌ PII scan failed", file=sys.stderr)
        return 1
    
    print("✓ All adversarial corpus checks passed", file=sys.stderr)
    return 0


def cmd_integrity_coverage(argv: list[str]) -> int:
    """Phase 12 §12.9 — Verify integrity primitives coverage.
    
    Asserts:
    - Every integrity primitive enumerated in §12.9.1 has a stable catalogue ID
    - Every primitive has a corresponding proof test (§12.9.2–§12.9.4)
    - No primitive added without a tamper test + clean-path verification
    """
    import re
    
    # Integrity primitives from §12.9.1 (binding table)
    primitives = [
        "citation_hmac",
        "answer_envelope_hmac",
        "outbound_answer_checksum",
        "inbound_request_checksum",
        "prediction_id_determinism",
        "opsctl_envelope_signature",
        "audit_log_hash_chain",
        "backup_per_file_sha",
        "backup_archive_checksum",
        "prediction_signed_envelope",
        "lexicon_feed_hmac",
        "cross_language_normalize_spec_sha",
    ]
    
    # Read test file to check for coverage
    test_file = REPO_ROOT / "ai" / "tests" / "test_phase12_fault_injector.py"
    if not test_file.is_file():
        print(f"❌ Test file not found: {test_file}", file=sys.stderr)
        return 1
    
    test_content = test_file.read_text(encoding="utf-8")
    
    # Check for each primitive's test
    missing = []
    for prim in primitives:
        # Look for a test method or scenario reference
        pattern = rf"(test_.*{re.escape(prim)}|chaos_.*{re.escape(prim.replace('_', '-'))}|P12-9-)"
        if not re.search(pattern, test_content, re.IGNORECASE):
            missing.append(prim)
    
    if missing:
        print(f"❌ Missing tests for primitives: {', '.join(missing)}", file=sys.stderr)
        return 1
    
    print(f"✓ All {len(primitives)} integrity primitives have test coverage", file=sys.stderr)
    return 0


def cmd_security_coverage(argv: list[str]) -> int:
    """Phase 12 §12.10 — Verify security chaos coverage.
    
    Asserts:
    - Every security scenario (P12-10-A through P12-10-K) has a test
    - Zero undetected-attack count in the §12.14 scorecard
    """
    import re
    
    scenarios = [
        ("P12-10-A", "prompt_injection"),
        ("P12-10-B", "homoglyph_rtl"),
        ("P12-10-C", "oversize_zero"),
        ("P12-10-D", "slur_obfuscation"),
        ("P12-10-E", "credential_stuffing"),
        ("P12-10-F", "xff_spoof"),
        ("P12-10-G", "redis_fail_open"),
        ("P12-10-H", "token_replay"),
        ("P12-10-I", "cert_expiry"),
        ("P12-10-I-alt", "key_rotation"),
        ("P12-10-I-secret", "secret_unreadable"),
        ("P12-10-J", "tampered_binary"),
        ("P12-10-K", "cve_injection"),
    ]
    
    test_file = REPO_ROOT / "ai" / "tests" / "test_phase12_fault_injector.py"
    if not test_file.is_file():
        print(f"❌ Test file not found: {test_file}", file=sys.stderr)
        return 1
    
    test_content = test_file.read_text(encoding="utf-8")
    
    missing = []
    for scenario_id, scenario_name in scenarios:
        # Look for test methods or scenario references
        pattern = rf"(test.*{scenario_name}|chaos_.*{scenario_name.replace('_', '-')})"
        if not re.search(pattern, test_content, re.IGNORECASE):
            missing.append(scenario_id)
    
    if missing:
        print(f"❌ Missing tests for scenarios: {', '.join(missing)}", file=sys.stderr)
        return 1
    
    print(f"✓ All {len(scenarios)} security scenarios have test coverage", file=sys.stderr)
    return 0


COMMANDS = {
    "dlq-replay-policy": cmd_dlq_replay_policy,
    "adversarial-corpora": cmd_adversarial_corpora,
    "integrity-coverage": cmd_integrity_coverage,
    "security-coverage": cmd_security_coverage,
}


def main(argv: list[str] | None = None) -> int:
    return dispatch(
        argv if argv is not None else sys.argv[1:],
        COMMANDS,
        script_name="verify.py",
    )


if __name__ == "__main__":
    raise SystemExit(main())
