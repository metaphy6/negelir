#!/usr/bin/env python3
"""`make docs.*` — documentation dispatcher.

Thin wrapper around doc-generation and validation tasks.
"""

from __future__ import annotations

import ast
import datetime
import os
import re
import sys
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from xops.makefile._common import dispatch, err, run  # noqa: E402


def cmd_api(_argv: List[str]) -> int:
    """Regenerate PUBLIC_API.md for each component from __all__.
    
    Walks each component root __init__.py, extracts the __all__ declaration,
    and regenerates <component>/PUBLIC_API.md with the discovered public API.
    """
    components = [
        "ai",
        "swarm",
        "common",
        "datasource_scraper",
        "datasource_watcher",
        "datasource_refresher",
        "datasource_patcher",
        "datasource_gitops",
    ]
    
    errors = []
    
    for component in components:
        # Special case mappings for Phase 22 components
        if component == "datasource_scraper":
            comp_path = REPO_ROOT / "scraper"
        elif component == "datasource_emitter":
            # Already at 1.0.0; might be at enrichment/ or ai/datasource/emitter
            comp_path = REPO_ROOT / "enrichment" / "emitter"
            if not comp_path.exists():
                comp_path = REPO_ROOT / "ai" / "datasource" / "emitter"
        elif component == "datasource_watcher" or component == "datasource_refresher" or component == "datasource_patcher" or component == "datasource_gitops":
            # Try Phase 22 layout: datasource/watcher, datasource/refresher, etc.
            comp_path = REPO_ROOT / component.split("_", 1)[1]  # removes "datasource_" prefix
            if not comp_path.exists():
                # Fall back to Phase 18 layout: ai/datasource/watcher, etc.
                comp_path = REPO_ROOT / "ai" / component.replace("_", "/")
        else:
            # Try Phase 22 layout first (swarm/, common/)
            comp_path = REPO_ROOT / component.replace("_", "/")
            if not comp_path.exists():
                # Fall back to Phase 18 layout (ai/)
                comp_path = REPO_ROOT / "ai" / component.replace("_", "/")
        
        if not comp_path.exists():
            print(f"⚠️  {component}: not found at {comp_path}")
            continue
        
        init_path = comp_path / "__init__.py"
        if not init_path.exists():
            print(f"⚠️  {component}: no __init__.py at {init_path}")
            continue
        
        # Parse __all__ from __init__.py
        try:
            with init_path.open("r", encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=str(init_path))
        except SyntaxError as e:
            err(f"{component}: parse error in {init_path}: {e}")
            errors.append(component)
            continue
        
        # Find __all__ assignment
        all_names: List[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__all__":
                        if isinstance(node.value, ast.List):
                            for elt in node.value.elts:
                                if isinstance(elt, ast.Constant):
                                    all_names.append(str(elt.value))
        
        if not all_names:
            print(f"⚠️  {component}: no __all__ found in {init_path}")
            continue
        
        # Generate PUBLIC_API.md
        public_api_path = comp_path / "PUBLIC_API.md"
        api_doc = f"""# {component.title()} — Public API

> **Component:** {component}
> **Frozen:** Phase 18.5 (§18.5 ledger #7)
> **Generated from:** `{component}/__init__.py::__all__`
> **Last regenerated:** Phase 18.5 (via `make docs.api`)

This document is **auto-generated** from the `__all__` declaration in
`{component}/__init__.py`. Do not edit by hand; regenerate with:

```bash
make docs.api
```

---

## Public Surface

The following symbols are part of the stable public API and must not change
without a major-version bump:

"""
        
        for name in sorted(all_names):
            api_doc += f"- `{name}`\n"
        
        api_doc += """

---

## Deprecation Policy

See [`docs/coding/component_versioning.md`](../../docs/coding/component_versioning.md)
for the full deprecation and breaking-change discipline.
"""
        
        public_api_path.write_text(api_doc, encoding="utf-8")
        print(f"✅ {component}: regenerated {public_api_path}")
    
    if errors:
        err(f"failed for components: {', '.join(errors)}")
        return 1
    
    print(f"\n✅ Regenerated PUBLIC_API.md for {len(components)} components")
    return 0


def cmd_verify(_argv: List[str]) -> int:
    """Verify that all anchor docs have current last_verified_against_code dates.
    
    Checks the 6 anchor docs (COMPONENT_LAYOUT.md, DATA_PIPELINE.md, EMITTER.md,
    SWARM.md, SCRAPER_PATCHER.md, SECURITY.md) and ensures their
    last_verified_against_code dates are not older than the configured
    docs_max_staleness_days threshold (default 90 days).
    
    Fails CI if any anchor doc is stale.
    """
    import os
    
    anchor_docs = [
        "docs/design/COMPONENT_LAYOUT.md",
        "docs/design/DATA_PIPELINE.md",
        "docs/design/EMITTER.md",
        "docs/design/SWARM.md",
        "docs/design/SCRAPER_PATCHER.md",
        "docs/design/SECURITY.md",
    ]
    
    today = datetime.date.today()
    max_staleness_days = int(os.getenv("NEGELIR_DOCS_MAX_STALENESS_DAYS", "90"))
    errors = []
    
    for doc_path_str in anchor_docs:
        doc_path = REPO_ROOT / doc_path_str
        if not doc_path.exists():
            err(f"{doc_path_str}: not found")
            errors.append(doc_path_str)
            continue
        
        # Extract last_verified_against_code from front-matter comment
        content = doc_path.read_text(encoding="utf-8")
        match = re.search(r"last_verified_against_code:\s*(\d{4}-\d{2}-\d{2})", content)
        
        if not match:
            err(f"{doc_path_str}: missing last_verified_against_code front-matter")
            errors.append(doc_path_str)
            continue
        
        date_str = match.group(1)
        try:
            verified_date = datetime.date.fromisoformat(date_str)
        except ValueError:
            err(f"{doc_path_str}: invalid date format (expected YYYY-MM-DD): {date_str}")
            errors.append(doc_path_str)
            continue
        
        age_days = (today - verified_date).days
        if age_days > max_staleness_days:
            err(
                f"{doc_path_str}: stale ({age_days} days old, > {max_staleness_days} day threshold). "
                f"Last verified: {date_str}. Update the front-matter and re-verify."
            )
            errors.append(doc_path_str)
        else:
            print(f"✅ {doc_path_str}: verified {age_days} days ago ({date_str})")
    
    if errors:
        err(f"\n❌ {len(errors)} anchor doc(s) are stale or missing front-matter. "
            f"Staleness threshold: {max_staleness_days} days.")
        return 1
    
    print(f"\n✅ All {len(anchor_docs)} anchor docs are current (threshold: {max_staleness_days} days)")
    return 0


COMMANDS = {
    "api": cmd_api,
    "verify": cmd_verify,
}


def main(argv: List[str]) -> int:
    return dispatch(argv, COMMANDS, script_name="docs.py")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
