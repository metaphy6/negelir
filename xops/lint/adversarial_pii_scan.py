#!/usr/bin/env python3
"""Phase 12 §12.2.1 — PII scrubbing verification for adversarial corpora.

Re-scans all adversarial corpus entries for Turkish PII markers:
- TC kimlik (ID numbers)
- IBAN (bank account)
- Phone numbers
- License plates
- Real-looking secrets (AWS keys, JWT patterns)
"""

import sys
import json
import re
import argparse
from pathlib import Path
from datetime import datetime
import yaml


# Turkish PII patterns (reuse Phase 10 §10.28.4 detectors)
TC_KIMLIK_PATTERN = re.compile(r'\b\d{11}\b')  # 11-digit ID
IBAN_PATTERN = re.compile(r'\b(TR|DE|FR|IT|ES)\d{2}[A-Z0-9]{1,30}\b')
PHONE_PATTERN = re.compile(r'(\+90|0)[0-9]{9,10}')  # Turkish phone
PLATE_PATTERN = re.compile(r'\b[A-Z]{1,3}\s?\d{1,5}\b')  # License plate
SECRET_PATTERN = re.compile(r'(AKIA[0-9A-Z]{16}|ey[A-Za-z0-9_-]{50,})')  # AWS, JWT


def _scan_text(text: str) -> list[str]:
    """Scan text for PII markers. Returns list of detected patterns."""
    if not isinstance(text, str):
        return []
    
    findings = []
    
    if TC_KIMLIK_PATTERN.search(text):
        findings.append("tc_kimlik")
    if IBAN_PATTERN.search(text):
        findings.append("iban")
    if PHONE_PATTERN.search(text):
        findings.append("phone")
    if PLATE_PATTERN.search(text):
        findings.append("plate")
    if SECRET_PATTERN.search(text):
        findings.append("secret")
    
    return findings


def _scan_dict(obj: dict) -> list[str]:
    """Recursively scan a dict for PII."""
    findings = []
    for k, v in obj.items():
        if isinstance(v, str):
            findings.extend(_scan_text(v))
        elif isinstance(v, dict):
            findings.extend(_scan_dict(v))
        elif isinstance(v, (list, tuple)):
            for item in v:
                if isinstance(item, str):
                    findings.extend(_scan_text(item))
                elif isinstance(item, dict):
                    findings.extend(_scan_dict(item))
    return findings


def scan_corpus_family(family_dir: Path) -> dict:
    """Scan all entries in a corpus family. Returns {path: findings}."""
    results = {}
    for yaml_file in family_dir.glob("*.yaml"):
        if yaml_file.name == "corpus.yaml":
            continue
        try:
            with open(yaml_file) as f:
                data = yaml.safe_load(f)
                entries = []
                if isinstance(data, list):
                    entries = data
                elif isinstance(data, dict) and "entries" in data:
                    entries = data["entries"]
                
                for i, entry in enumerate(entries):
                    if isinstance(entry, dict):
                        findings = _scan_dict(entry)
                        if findings:
                            results[f"{yaml_file.name}[{i}]"] = findings
        except Exception as e:
            results[str(yaml_file)] = [f"parse_error: {e}"]
    
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Scan adversarial corpora for PII (Phase 12 §12.2.1)"
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root",
    )
    parser.add_argument(
        "--fail-on-pii",
        action="store_true",
        default=True,
        help="Exit with code 1 if any PII found (default: enabled)",
    )
    
    args = parser.parse_args()
    
    adversarial_dir = args.repo_root / "ai" / "tests" / "fixtures" / "adversarial"
    if not adversarial_dir.exists():
        print(f"❌ {adversarial_dir} not found", file=sys.stderr)
        return 1
    
    all_findings = {}
    for family_dir in sorted(adversarial_dir.iterdir()):
        if family_dir.is_dir() and family_dir.name not in ("archived", "__pycache__"):
            findings = scan_corpus_family(family_dir)
            if findings:
                all_findings[family_dir.name] = findings
    
    if all_findings:
        print(f"❌ PII detected in {len(all_findings)} corpus families:", file=sys.stderr)
        for family, locations in all_findings.items():
            print(f"\n  {family}:", file=sys.stderr)
            for loc, types in locations.items():
                print(f"    {loc}: {', '.join(types)}", file=sys.stderr)
        
        if args.fail_on_pii:
            return 1
    else:
        print("✓ No PII detected in adversarial corpora", file=sys.stderr)
    
    # Update corpus.yaml timestamp
    for family_dir in sorted(adversarial_dir.iterdir()):
        if family_dir.is_dir() and family_dir.name not in ("archived", "__pycache__"):
            corpus_yaml = family_dir / "corpus.yaml"
            if corpus_yaml.exists():
                try:
                    with open(corpus_yaml) as f:
                        data = yaml.safe_load(f)
                    
                    if "pii_scrub" not in data:
                        data["pii_scrub"] = {}
                    
                    data["pii_scrub"]["timestamp"] = datetime.utcnow().isoformat() + "+00:00"
                    data["pii_scrub"]["tool_version"] = "xops/lint/adversarial_pii_scan.py v1.0"
                    data["pii_scrub"]["status"] = "failed" if all_findings.get(family_dir.name) else "passed"
                    
                    with open(corpus_yaml, "w") as f:
                        yaml.dump(data, f, default_flow_style=False)
                except Exception as e:
                    print(f"⚠ Could not update {corpus_yaml}: {e}", file=sys.stderr)
    
    return 0 if not all_findings else (1 if args.fail_on_pii else 0)


if __name__ == "__main__":
    sys.exit(main())
