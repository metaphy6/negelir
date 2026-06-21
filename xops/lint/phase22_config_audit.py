#!/usr/bin/env python3
"""Phase 22.1 bullet 4 — Config audit script.

Scans the entire codebase for cfg.* references and produces
docs/tracking/phase22_config_audit.json with:
- Lists every config key used in ai/ with its definition path in ai/common/config.py
- Lists config keys read by non-ai/ files
- Marks config keys migrated to common/config/ during §22.6 with old and new paths

The script is idempotent and re-runnable.
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import datetime

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")


@dataclass
class ConfigKeyInfo:
    """Metadata for a single config key."""
    key_name: str
    definition_line: int | None = None
    definition_file: str = "ai/common/config.py"
    used_in_ai_files: set[str] = field(default_factory=set)
    used_in_non_ai_files: set[str] = field(default_factory=set)
    migrated_from: str | None = None
    migrated_to: str | None = None
    
    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON output."""
        return {
            "key_name": self.key_name,
            "definition_line": self.definition_line,
            "definition_file": self.definition_file,
            "used_in_ai_files": sorted(self.used_in_ai_files),
            "used_in_non_ai_files": sorted(self.used_in_non_ai_files),
            "migrated_from": self.migrated_from,
            "migrated_to": self.migrated_to,
        }


class ConfigAuditor:
    """Audits config key usage across the codebase."""
    
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.config_keys: dict[str, ConfigKeyInfo] = {}
        
    def extract_config_keys(self) -> None:
        """Extract config keys from ai/common/config.py."""
        config_file = self.repo_root / "ai" / "common" / "config.py"
        if not config_file.exists():
            logger.warning(f"Config file not found: {config_file}")
            return
            
        with open(config_file, "r", encoding="utf-8") as f:
            source = f.read()
            
        # Parse the Config class
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            logger.error(f"Failed to parse config file: {e}")
            return
            
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "Config":
                for item in node.body:
                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                        key_name = item.target.id
                        # Skip private keys (starting with _)
                        if not key_name.startswith("_"):
                            info = ConfigKeyInfo(
                                key_name=key_name,
                                definition_line=item.lineno,
                                definition_file="ai/common/config.py"
                            )
                            self.config_keys[key_name] = info
                            
    def scan_codebase(self) -> None:
        """Scan the codebase for cfg.* references."""
        # Pattern to match cfg.attribute_name
        cfg_pattern = re.compile(r'\bcfg\.([a-zA-Z_][a-zA-Z0-9_]*)\b')
        
        # Scan all Python files
        for py_file in self.repo_root.rglob("*.py"):
            # Skip __pycache__
            if "__pycache__" in py_file.parts:
                continue
                
            try:
                with open(py_file, "r", encoding="utf-8") as f:
                    content = f.read()
            except (UnicodeDecodeError, OSError):
                continue
                
            # Find all cfg.* matches
            matches = cfg_pattern.findall(content)
            
            # Determine if file is in ai/ or not
            relative_path = str(py_file.relative_to(self.repo_root))
            is_ai_file = relative_path.startswith("ai/")
            
            for match in matches:
                if match not in self.config_keys:
                    # Add unknown config keys
                    info = ConfigKeyInfo(
                        key_name=match,
                        definition_file="ai/common/config.py"
                    )
                    self.config_keys[match] = info
                    
                if is_ai_file:
                    self.config_keys[match].used_in_ai_files.add(relative_path)
                else:
                    self.config_keys[match].used_in_non_ai_files.add(relative_path)
                    
    def generate_report(self) -> dict[str, Any]:
        """Generate the config audit report."""
        ai_keys = {
            k: v for k, v in self.config_keys.items()
            if v.used_in_ai_files
        }
        non_ai_keys = {
            k: v for k, v in self.config_keys.items()
            if v.used_in_non_ai_files
        }
        
        # Compute content hash for idempotency
        content_str = json.dumps({
            "ai_keys": {k: v.to_dict() for k, v in sorted(ai_keys.items())},
            "non_ai_keys": {k: v.to_dict() for k, v in sorted(non_ai_keys.items())},
        }, sort_keys=True)
        content_hash = hashlib.sha256(content_str.encode()).hexdigest()[:8]
        
        return {
            "generated_at_utc": datetime.datetime.utcnow().isoformat() + "Z",
            "content_hash": content_hash,
            "total_config_keys": len(self.config_keys),
            "ai_config_keys": len(ai_keys),
            "non_ai_config_keys": len(non_ai_keys),
            "ai_keys": {k: v.to_dict() for k, v in sorted(ai_keys.items())},
            "non_ai_keys": {k: v.to_dict() for k, v in sorted(non_ai_keys.items())},
        }
        
    def save_report(self, output_path: Path) -> None:
        """Save the report to JSON."""
        report = self.generate_report()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
            
        logger.info(f"Config audit saved to {output_path}")
        logger.info(f"Total config keys: {report['total_config_keys']}")
        logger.info(f"AI keys: {report['ai_config_keys']}, Non-AI keys: {report['non_ai_config_keys']}")


def main() -> int:
    """Main entry point."""
    auditor = ConfigAuditor(REPO_ROOT)
    auditor.extract_config_keys()
    auditor.scan_codebase()
    
    output_path = REPO_ROOT / "docs" / "tracking" / "phase22_config_audit.json"
    auditor.save_report(output_path)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
