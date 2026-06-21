#!/usr/bin/env python3
"""make phase22.* — Phase 22 flat-layout migration dispatcher.

Implements pre-flight inventory, codemod, and migration coordination for
flattening ai/ to root.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from xops.makefile._common import dispatch, err, warn  # noqa: E402


def _blob_sha256(path: Path) -> str:
    """Compute the blob SHA-256 of a file."""
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        sha.update(f.read())
    return sha.hexdigest()


def _get_git_files_from_ai() -> Set[Path]:
    """Get all files tracked by git under ai/ (excluding __pycache__)."""
    result = subprocess.run(
        ["git", "ls-files", "ai/"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    files = set()
    for line in result.stdout.strip().split("\n"):
        if line and "__pycache__" not in line:
            files.add(Path(line))
    return files


def _find_non_ai_importers() -> Dict[str, List[str]]:
    """Find all non-ai/ files that import from ai.*.
    
    Returns a dict mapping package name to list of files importing from it.
    """
    # Find all Python files outside ai/
    result = subprocess.run(
        ["find", str(REPO_ROOT), "-type", "f", "-name", "*.py"],
        capture_output=True,
        text=True,
        check=True,
    )
    
    files = []
    for line in result.stdout.strip().split("\n"):
        if line and "ai/" not in line and "__pycache__" not in line:
            files.append(Path(line))
    
    # Grep each file for "from ai." or "import ai."
    importers: Dict[str, List[str]] = {}
    for fpath in files:
        try:
            content = fpath.read_text(errors="ignore")
            # Find all "from ai.X" or "import ai.X" patterns
            matches = re.findall(r"(?:from|import)\s+ai\.(\w+)", content)
            if matches:
                for match in set(matches):
                    pkg = match
                    rel_path = fpath.relative_to(REPO_ROOT).as_posix()
                    if pkg not in importers:
                        importers[pkg] = []
                    if rel_path not in importers[pkg]:
                        importers[pkg].append(rel_path)
        except (OSError, UnicodeDecodeError):
            pass
    
    return importers


# Move plan table (from ROADMAP §22.1)
MOVE_PLAN: Dict[str, Dict[str, Any]] = {
    "ai/scraper/": {"dest": "scraper/", "action": "move"},
    "ai/model/": {"dest": "model/", "action": "move"},
    "ai/nlp/": {"dest": "nlp/", "action": "move"},
    "ai/orchestrator/": {"dest": "orchestrator/", "action": "move"},
    "ai/pipeline/": {"dest": "pipeline/", "action": "move"},
    "ai/proofreader/": {"dest": "proofreader/", "action": "move"},
    "ai/qid/": {"dest": "qid/", "action": "move"},
    "ai/tqu/": {"dest": "tqu/", "action": "move"},
    "ai/trc/": {"dest": "trc/", "action": "move"},
    "ai/backtest/": {"dest": "backtest/", "action": "move"},
    "ai/tests/": {"dest": "tests/", "action": "merge"},
    "ai/datasource/enrichment/": {"dest": "enrichment/", "action": "move"},
    "ai/datasource/t3_resource_manager.py": {"dest": "enrichment/t3_resource_manager.py", "action": "move"},
    "datasource/quarantine.py": {"dest": "scraper/quarantine.py", "action": "move"},
    "ai/main.py": {"dest": "main.py", "action": "move"},
    "ai/scheduler.py": {"dest": "scheduler.py", "action": "move"},
    "ai/data_showcase.py": {"dest": "data_showcase.py", "action": "move"},
    "ai/requirements.txt": {"dest": "requirements.txt", "action": "merge"},
    "ai/requirements-dev.txt": {"dest": "requirements-dev.txt", "action": "merge"},
    "ai/Dockerfile": {"dest": "Dockerfile", "action": "merge"},
    "ai/common/": {"dest": "common/", "action": "merge"},
    "ai/swarm/": {"dest": "swarm/", "action": "merge"},
    "ai/docs/": {"dest": "docs/ai_pipeline/", "action": "merge"},
    "ai/reports/": {"dest": "docs/reports/ai_pipeline/", "action": "move"},
}


def _determine_destination(file_path: Path) -> Tuple[str, str]:
    """Determine destination path and action for a file under ai/.
    
    Returns (destination_path, action).
    """
    file_str = str(file_path)
    
    # Check each move plan entry in order (longest first for specificity)
    for src, plan in sorted(MOVE_PLAN.items(), key=lambda x: len(x[0]), reverse=True):
        if file_str.startswith(src):
            if src.endswith("/"):
                # Directory mapping
                relative = file_str[len(src):]
                dest = plan["dest"] + relative if plan["dest"].endswith("/") else plan["dest"] + "/" + relative
            else:
                # File mapping
                dest = plan["dest"]
            return dest, plan["action"]
    
    # Root datasource/quarantine.py special case
    if file_str == "datasource/quarantine.py":
        return "scraper/quarantine.py", "move"
    
    # Unmapped files default to root-level move
    return file_str.replace("ai/", ""), "move"


def cmd_inventory(_argv: List[str]) -> int:
    """Generate three JSON manifests for Phase 22.1 pre-flight inventory.
    
    Produces:
    - docs/tracking/phase22_file_accountability.json
    - docs/tracking/phase22_import_report.json
    - docs/tracking/phase22_move_plan.json
    """
    tracking_dir = REPO_ROOT / "docs" / "tracking"
    tracking_dir.mkdir(parents=True, exist_ok=True)
    
    # Collect all ai/ files and compute accountability manifest
    ai_files = _get_git_files_from_ai()
    accountability: Dict[str, Dict[str, Any]] = {}
    collision_map: Dict[str, List[str]] = {}
    
    for fpath in sorted(ai_files):
        dest, action = _determine_destination(fpath)
        blob_sha = _blob_sha256(REPO_ROOT / fpath)
        
        accountability[str(fpath)] = {
            "source": str(fpath),
            "destination": dest,
            "action": action,
            "blob_sha256": blob_sha,
        }
        
        # Track destination collisions
        if dest not in collision_map:
            collision_map[dest] = []
        collision_map[dest].append(str(fpath))
    
    # Find non-ai/ importers
    importers = _find_non_ai_importers()
    
    # Build import report
    import_report: Dict[str, Any] = {
        "generated_at_utc": str(Path(__file__).stat().st_mtime),
        "total_non_ai_importers": sum(len(v) for v in importers.values()),
        "by_package": {},
    }
    
    for pkg, files in sorted(importers.items()):
        import_report["by_package"][pkg] = {
            "count": len(files),
            "files": sorted(files),
        }
    
    # Build move plan summary
    move_plan_summary: Dict[str, Any] = {
        "total_ai_files": len(ai_files),
        "collision_summary": {
            "destinations_with_single_source": sum(1 for v in collision_map.values() if len(v) == 1),
            "destinations_with_collisions": sum(1 for v in collision_map.values() if len(v) > 1),
        },
        "collisions": {
            dest: srcs for dest, srcs in collision_map.items() if len(srcs) > 1
        },
    }
    
    # Write the three manifests
    accountability_path = tracking_dir / "phase22_file_accountability.json"
    import_report_path = tracking_dir / "phase22_import_report.json"
    move_plan_path = tracking_dir / "phase22_move_plan.json"
    
    accountability_path.write_text(json.dumps(accountability, indent=2), encoding="utf-8")
    import_report_path.write_text(json.dumps(import_report, indent=2), encoding="utf-8")
    move_plan_path.write_text(json.dumps(move_plan_summary, indent=2), encoding="utf-8")
    
    print(f"✓ {accountability_path.relative_to(REPO_ROOT)}")
    print(f"✓ {import_report_path.relative_to(REPO_ROOT)}")
    print(f"✓ {move_plan_path.relative_to(REPO_ROOT)}")
    
    # Report any collisions as warnings
    if move_plan_summary["collision_summary"]["destinations_with_collisions"] > 0:
        warn(
            f"Found {move_plan_summary['collision_summary']['destinations_with_collisions']} "
            "destination(s) with multiple sources — review before merge"
        )
    
    return 0


def cmd_import_report(_argv: List[str]) -> int:
    """Print a human-readable summary of non-ai/ callers from phase22_import_report.json.
    
    Shows per-package count of non-ai/ callers with file breakdown.
    """
    tracking_dir = REPO_ROOT / "docs" / "tracking"
    import_report_path = tracking_dir / "phase22_import_report.json"
    
    if not import_report_path.exists():
        err(f"Import report not found: {import_report_path.relative_to(REPO_ROOT)}")
        err("Run 'make phase22.inventory' first to generate it.")
        return 1
    
    try:
        report = json.loads(import_report_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        err(f"Failed to read import report: {e}")
        return 1
    
    # Print header
    total = report.get("total_non_ai_importers", 0)
    print(f"\n{'='*70}")
    print(f"Phase 22.1 — Non-ai/ Caller Inventory")
    print(f"{'='*70}")
    print(f"Total non-ai/ files importing from ai.*: {total}\n")
    
    # Print per-package breakdown
    by_package = report.get("by_package", {})
    if not by_package:
        print("(no non-ai/ importers found)")
        return 0
    
    for pkg in sorted(by_package.keys()):
        pkg_data = by_package[pkg]
        count = pkg_data.get("count", 0)
        files = pkg_data.get("files", [])
        
        print(f"{pkg:<20} {count:>3} caller{'s' if count != 1 else ' '}")
        
        # Print files with indentation
        for fpath in sorted(files):
            print(f"  • {fpath}")
        
        print()
    
    # Print summary by root package
    print(f"\n{'-'*70}")
    print("Summary by root package:")
    print(f"{'-'*70}")
    
    root_packages = {}
    for pkg_data in by_package.values():
        for fpath in pkg_data.get("files", []):
            # Extract root package (first component of path)
            parts = fpath.split("/")
            if parts:
                root_pkg = parts[0]
                if root_pkg not in root_packages:
                    root_packages[root_pkg] = 0
                root_packages[root_pkg] += 1
    
    for root_pkg in sorted(root_packages.keys()):
        count = root_packages[root_pkg]
        print(f"{root_pkg:<20} {count:>3} file{'s' if count != 1 else ' '}")
    
    print(f"{'='*70}\n")
    
    return 0


def cmd_preflight(_argv: List[str]) -> int:
    """Run Phase 18 pre-flight checks before Phase 22 migration begins.
    
    Verifies:
    1. All 14 Phase 18 isolation gates pass (blocks if any fail)
    2. No forbidden-edge violations detected
    3. CodeGraph index is fresh via `make codegraph.status`
    
    Exit 0 if all checks pass, non-zero otherwise.
    This gate must be green before any Phase 22 package moves.
    """
    # Import the preflight checker
    from xops.lint.phase22_preflight import PreflightChecker
    
    verbose = "--verbose" in _argv or "-v" in _argv
    checker = PreflightChecker(verbose=verbose)
    return checker.run_all_checks()


def _run_isort_on_file(fpath: Path, package: str) -> Tuple[bool, str]:
    """Run isort on a file with package-specific configuration.
    
    Args:
        fpath: Path to the Python file to format
        package: Package name (used for -p / known-first-party)
    
    Returns:
        (success: bool, status: str) where status is "formatted", "no-change", or "error"
    """
    try:
        result = subprocess.run(
            ["isort", "-p", package, str(fpath)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        
        if result.returncode != 0:
            return False, "error"
        
        # isort doesn't have a clear "no-change" indicator, so we'll assume
        # successful execution means either formatting happened or no change was needed
        return True, "formatted"
    except FileNotFoundError:
        err("isort not found in PATH. Ensure it's installed in your dev environment.")
        return False, "error"
    except Exception as e:
        err(f"Error running isort: {e}")
        return False, "error"


def cmd_codemod(argv: List[str]) -> int:
    """Apply or preview libcst-based import rewrites for a package (Phase 22.2).
    
    Usage:
        make phase22.codemod DRY_RUN=1 PACKAGE=<pkg>  — preview only (flag optional)
        make phase22.codemod PACKAGE=<pkg> --include-non-ai-callers  — apply rewrites (flag mandatory)
        make phase22.codemod.check                     — validate file scope boundary
    
    The --include-non-ai-callers flag is MANDATORY for non-dry-run execution.
    When set, also rewrites all non-ai/ files that import from the package.
    This command delegates to xops/codemod/phase22_rewriter.py for actual rewrites.
    Phase 22.2 bullet 2 enforces scope boundary: only *.py files are touched.
    Phase 22.2 bullet 9: After each package rewrite, isort is run on all changed files.
    """
    import os
    from xops.codemod.phase22_rewriter import (
        FileFilterValidator,
        FileScopeError,
        Phase22ImportRewriter,
    )
    
    # Check if this is a scope-check subcommand (Phase 22.2 bullet 2)
    if "check" in argv or "--check" in argv:
        # Validate scope boundary for all Python files under ai/
        ai_files = _get_git_files_from_ai()
        py_files = [f for f in ai_files if str(f).endswith('.py')]
        
        print(f"Checking scope boundary for {len(py_files)} Python files under ai/...")
        
        # Verify all py files pass validation
        try:
            FileFilterValidator.validate_file_list([REPO_ROOT / f for f in py_files])
            print(f"✓ All {len(py_files)} Python files pass scope boundary check")
            return 0
        except FileScopeError as e:
            err(f"Scope boundary violation: {e}")
            return 1
    
    # Get package from environment variable
    package = os.environ.get("PACKAGE", "")
    if not package:
        err("PACKAGE environment variable not set")
        print("Usage: make phase22.codemod PACKAGE=<pkg> [--include-non-ai-callers] [DRY_RUN=1]")
        print("Example: make phase22.codemod PACKAGE=common --include-non-ai-callers")
        return 1
    
    dry_run = os.environ.get("DRY_RUN", "").lower() in {"1", "true", "yes"}
    include_non_ai_callers = "--include-non-ai-callers" in argv
    
    # Enforce mandatory flag for non-dry-run execution
    if not dry_run and not include_non_ai_callers:
        err("ERROR: --include-non-ai-callers flag is MANDATORY for actual (non-dry-run) package moves.")
        print("This flag indicates you've reviewed the list of non-ai/ callers and consent to rewriting them.")
        print()
        print("For dry-run (preview-only): make phase22.codemod DRY_RUN=1 PACKAGE=common")
        print("For actual move:             make phase22.codemod PACKAGE=common --include-non-ai-callers")
        return 1
    
    # Get all *.py files in ai/ that will be moved to the target package
    ai_files = _get_git_files_from_ai()
    
    # Filter to only files that will be moved to the target package
    files_to_rewrite: Dict[Path, str] = {}  # path -> "ai_file" or "non_ai_caller"
    
    for fpath in ai_files:
        if not str(fpath).endswith('.py'):
            continue
        dest, _ = _determine_destination(fpath)
        # Check if this file moves to the target package
        if dest.startswith(package + "/") or dest == package:
            files_to_rewrite[REPO_ROOT / fpath] = "ai_file"
    
    # If --include-non-ai-callers flag is set, also add non-ai/ caller files
    if include_non_ai_callers:
        inventory_path = REPO_ROOT / "docs" / "tracking" / "phase22_import_report.json"
        non_ai_callers = Phase22ImportRewriter.get_non_ai_callers(package, inventory_path)
        
        for caller_file in non_ai_callers:
            caller_path = REPO_ROOT / caller_file
            # Only add if it exists and we haven't already added it
            if caller_path.exists() and caller_path not in files_to_rewrite:
                files_to_rewrite[caller_path] = "non_ai_caller"
    
    if not files_to_rewrite:
        warn(f"No Python files found that will be moved to package '{package}'")
        return 0
    
    # Validate all files are within scope (bullet 2)
    try:
        FileFilterValidator.validate_file_list(files_to_rewrite.keys())
    except FileScopeError as e:
        err(f"Scope boundary violation: {e}")
        return 1
    
    # Apply rewrites with rollback safety (.phase22.orig sidecars)
    rewriter = Phase22ImportRewriter(package=package)
    total_changes = 0
    rewritten_count = 0
    noop_count = 0
    rewritten_files: List[Path] = []  # Track files that were rewritten for isort
    
    for fpath in sorted(files_to_rewrite.keys()):
        try:
            source = fpath.read_text(encoding="utf-8")
            rewritten, status = Phase22ImportRewriter.rewrite_source(source, package=package)
            
            if status == "no-op":
                # File is already rewritten (no ai.* imports found)
                rel_path = fpath.relative_to(REPO_ROOT)
                file_type = files_to_rewrite[fpath]
                print(f"  {rel_path} ({file_type}): no-op (already rewritten)")
                noop_count += 1
            elif source != rewritten:
                # File was rewritten
                file_type = files_to_rewrite[fpath]
                rel_path = fpath.relative_to(REPO_ROOT)
                
                # Count changes
                changes = rewritten.count("\n") - source.count("\n") + sum(
                    1 for a, b in zip(source.split("\n"), rewritten.split("\n")) if a != b
                )
                print(f"  {rel_path} ({file_type}): rewritten")
                total_changes += changes
                rewritten_count += 1
                
                if not dry_run:
                    # Write .phase22.orig sidecar for rollback safety
                    orig_path = fpath.with_suffix(fpath.suffix + ".phase22.orig")
                    orig_path.write_text(source, encoding="utf-8")
                    # Write rewritten file
                    fpath.write_text(rewritten, encoding="utf-8")
                    # Track this file for isort formatting
                    rewritten_files.append(fpath)
        except Exception as ex:
            warn(f"Error processing {fpath}: {ex}")
    
    if dry_run:
        print(f"\nDRY_RUN: {len(files_to_rewrite)} files checked:")
        print(f"  {rewritten_count} would be rewritten with {total_changes} changes")
        print(f"  {noop_count} are no-ops (already rewritten)")
        return 0
    else:
        # Phase 22.2 bullet 9: Run isort on all rewritten files
        isort_errors = 0
        if rewritten_files:
            print(f"\nRunning isort on {len(rewritten_files)} rewritten files...")
            for fpath in rewritten_files:
                rel_path = fpath.relative_to(REPO_ROOT)
                success, status = _run_isort_on_file(fpath, package)
                if success:
                    print(f"  {rel_path}: {status}")
                else:
                    err(f"  {rel_path}: isort {status}")
                    isort_errors += 1
        
        if isort_errors > 0:
            err(f"\nisort failed on {isort_errors} file(s). Codemod aborted.")
            err("Reverting changes...")
            # Clean up sidecars and restore originals on isort failure
            for fpath in rewritten_files:
                orig_path = fpath.with_suffix(fpath.suffix + ".phase22.orig")
                if orig_path.exists():
                    orig_content = orig_path.read_bytes()
                    fpath.write_bytes(orig_content)
                    orig_path.unlink()
            return 1
        
        print(f"\n✓ Codemod complete:")
        print(f"  {rewritten_count} files rewritten with {total_changes} changes")
        print(f"  {noop_count} files are no-ops (already rewritten)")
        if rewritten_files:
            print(f"  {len(rewritten_files)} files formatted with isort")
        if include_non_ai_callers:
            print(f"  (including {sum(1 for v in files_to_rewrite.values() if v == 'non_ai_caller')} non-ai/ caller files)")
        return 0


def cmd_codemod_all(argv: List[str]) -> int:
    """Preview or apply rewrites for all packages in dependency order (Phase 22.2).
    
    ENFORCES SEQUENTIAL-ONLY REWRITING (bullet 6):
    1. Calls make phase22.cycle-check first (must pass — no cycles allowed)
    2. Reads topological sort from docs/tracking/phase22_topo_sort.json
    3. Iterates packages ONE AT A TIME in the order determined by cycle-check
    4. No parallel rewrites allowed
    
    Usage:
        make phase22.codemod.all DRY_RUN=1  — preview all rewrites (flag optional)
        make phase22.codemod.all --include-non-ai-callers  — apply all rewrites (flag mandatory)
    
    Generates docs/tracking/phase22_codemod_preview.diff (if DRY_RUN=1).
    The --include-non-ai-callers flag is required for non-dry-run execution.
    """
    import os
    
    dry_run = os.environ.get("DRY_RUN", "").lower() in {"1", "true", "yes"}
    include_non_ai_callers = "--include-non-ai-callers" in argv
    
    # Enforce mandatory flag for non-dry-run execution
    if not dry_run and not include_non_ai_callers:
        err("ERROR: --include-non-ai-callers flag is MANDATORY for actual (non-dry-run) execution.")
        print("For dry-run (preview-only): make phase22.codemod.all DRY_RUN=1")
        print("For actual application:     make phase22.codemod.all --include-non-ai-callers")
        return 1
    
    # PARALLEL REWRITE SAFETY (bullet 6):
    # Step 1: Run cycle detection (must pass)
    print("\n=== Phase 22.2 bullet 6: Cycle detection (enforcing sequential rewriting) ===")
    cycle_result = cmd_cycle_check([])
    if cycle_result != 0:
        err("Cycle detection FAILED. Rewriting BLOCKED until cycles are resolved.")
        return 1
    
    # Step 2: Load topological sort from JSON (written by cycle-check)
    topo_json = REPO_ROOT / "docs" / "tracking" / "phase22_topo_sort.json"
    if not topo_json.exists():
        err(f"Topological sort JSON not found: {topo_json}")
        print("Run 'make phase22.cycle-check' first.")
        return 1
    
    try:
        with open(topo_json) as f:
            topo_data = json.load(f)
        packages = topo_data.get("topo_sort", [])
        if not packages:
            err("Topological sort is empty or malformed.")
            return 1
    except (json.JSONDecodeError, KeyError) as e:
        err(f"Failed to parse {topo_json}: {e}")
        return 1
    
    # Step 3: Iterate packages ONE AT A TIME (sequential, non-parallel)
    print(f"\n✓ Cycle detection passed. Processing {len(packages)} packages in order:")
    failed_packages = []
    
    for i, pkg in enumerate(packages, 1):
        print(f"\n[{i}/{len(packages)}] Processing: {pkg}")
        cmd_args = argv.copy()
        os.environ["PACKAGE"] = pkg
        if dry_run:
            os.environ["DRY_RUN"] = "1"
        
        result = cmd_codemod(cmd_args)
        if result != 0:
            warn(f"Error processing package {pkg}")
            failed_packages.append(pkg)
            # Continue with next package (but track the failure)
    
    # Summary
    if dry_run:
        print(f"\n✓ DRY_RUN preview complete for all {len(packages)} packages (sequential)")
    else:
        if failed_packages:
            print(f"\n⚠ Codemod applied to {len(packages) - len(failed_packages)}/{len(packages)} packages")
            print(f"  Failed packages: {', '.join(failed_packages)}")
            return 1
        else:
            print(f"\n✓ Codemod successfully applied to all {len(packages)} packages (sequential)")
            print("  Guarantee: dependency order enforced, no cycles, no parallelization")
    
    return 0


def cmd_cycle_check(argv: List[str]) -> int:
    """Run cycle analysis on ai/ tree (Phase 22.2 bullet 6).
    
    Detects circular import dependencies via Tarjan's strongly connected components.
    If cycles are found, rewriting is BLOCKED (no parallel execution allowed).
    If no cycles, produces a deterministic topological sort order for safe sequential rewriting.
    
    Outputs: docs/tracking/phase22_topo_sort.json
      - topo_sort: list of packages in safe rewrite order
      - has_cycles: boolean flag
      - cycles: list of cycle components (if any)
      - packages: all packages found
    
    Exit code: 1 if cycles found, 0 if safe to proceed.
    """
    # Import the cycle checker module
    from xops.codemod.phase22_cycle_check import analyze_cycles_and_sort, write_topo_sort_json
    
    result, exit_code = analyze_cycles_and_sort(REPO_ROOT)
    
    if result["has_cycles"]:
        print("\n❌ CYCLES DETECTED — parallel rewriting is FORBIDDEN")
        print(f"\nFound {len(result['cycles'])} cycle(s):\n")
        for cycle in result["cycles"]:
            cycle_str = ' → '.join(cycle) + f" → {cycle[0]}"
            print(f"  {cycle_str}")
        print("\nRewriting is BLOCKED until all cycles are resolved.")
        print("Break the cycles by moving shared logic to a common/ subpackage.")
        return 1
    
    # Write topological sort to JSON for persistence
    write_topo_sort_json(result)
    
    print("✅ No cycles detected — safe to proceed with sequential rewriting\n")
    print(f"Topological sort ({len(result['topo_sort'])} packages):")
    for i, pkg in enumerate(result["topo_sort"], 1):
        print(f"  {i:2d}. {pkg}")
    
    print(f"\n✓ Topological sort written to docs/tracking/phase22_topo_sort.json")
    print("  Subsequent runs will use this order for sequential rewriting.")
    
    return exit_code


def cmd_dead_code(argv: List[str]) -> int:
    """Run vulture scan on ai/ tree (Phase 22.2).
    
    Produces docs/tracking/phase22_dead_code_candidates.md with symbols
    at 80% confidence threshold for pre-migration cleanup.
    """
    # TODO: Implement in Phase 22.2
    print("phase22.dead-code: not yet implemented")
    return 0


def cmd_go_path_check(argv: List[str]) -> int:
    """Scan Go source for ai/ path string literals (Phase 22.2).
    
    Classifies findings as load-bearing (runtime path constant, parity-test
    source-path table) vs. comment-only, producing
    docs/tracking/phase22_go_path_hits.txt for §22.5 migration.
    """
    # TODO: Implement in Phase 22.2
    print("phase22.go-path-check: not yet implemented")
    return 0


def cmd_swarm_collision_check(argv: List[str]) -> int:
    """Check swarm agents for module name collisions (Phase 22.2).
    
    Enumerates module names in ai/swarm/agents/ vs swarm/agents/ and asserts
    zero collisions (ledger #34).
    """
    ai_agents_dir = REPO_ROOT / "ai" / "swarm" / "agents"
    root_agents_dir = REPO_ROOT / "swarm" / "agents"
    
    # Collect module names from ai/swarm/agents/
    ai_modules: Set[str] = set()
    if ai_agents_dir.exists():
        for item in ai_agents_dir.iterdir():
            # Skip __pycache__, __init__.py, test files
            if item.name.startswith("__"):
                continue
            if item.name.startswith("test_"):
                continue
            if item.suffix == ".py":
                # It's a module file: categorizer.py -> categorizer
                module_name = item.stem
                ai_modules.add(module_name)
            elif item.is_dir() and not item.name.startswith("."):
                # It's a package: agents/maint -> maint
                ai_modules.add(item.name)
    
    # Collect module names from swarm/agents/
    root_modules: Set[str] = set()
    if root_agents_dir.exists():
        for item in root_agents_dir.iterdir():
            # Skip __pycache__, __init__.py, test files
            if item.name.startswith("__"):
                continue
            if item.name.startswith("test_"):
                continue
            if item.suffix == ".py":
                # It's a module file
                module_name = item.stem
                root_modules.add(module_name)
            elif item.is_dir() and not item.name.startswith("."):
                # It's a package
                root_modules.add(item.name)
    
    # Check for collisions
    collisions = ai_modules & root_modules
    
    print("Phase 22.3c — Swarm Agent Collision Check (ledger #34)")
    print("=" * 70)
    print(f"\nai/swarm/agents/ modules:  {len(ai_modules)} total")
    print(f"  {sorted(ai_modules)}")
    print(f"\nswarm/agents/ modules:     {len(root_modules)} total")
    print(f"  {sorted(root_modules)}")
    
    if collisions:
        print(f"\n🛑 COLLISION DETECTED: {len(collisions)} module name(s) exist in both:")
        for name in sorted(collisions):
            print(f"  - {name}")
        print("\nRequire explicit rename decision per ROADMAP §22.3c:")
        print("  Documentation: docs/decisions/phase22/swarm_agent_collision_<name>.md")
        print("  Alias period: 90 days\n")
        return 1
    else:
        print(f"\n✓ No collisions detected — merge can proceed\n")
        return 0


def cmd_conftest_inventory(argv: List[str]) -> int:
    """List and classify all conftest.py files (Phase 22.2).
    
    Produces docs/tracking/phase22_conftest_inventory.json classifying each
    as move-target, merge-target, or untouched per ledger #41.
    """
    # TODO: Implement in Phase 22.2
    print("phase22.conftest-inventory: not yet implemented")
    return 0


def cmd_patcher_artifact_probe(argv: List[str]) -> int:
    """Record presence/absence of Phase 17 cassettes and bundles (Phase 22.2).
    
    Writes docs/tracking/phase22_patcher_artifact_state.txt recording whether
    xops/patcher/cassettes/ and feeds/ops/bundles/ exist (ledger #38).
    """
    # TODO: Implement in Phase 22.2
    print("phase22.patcher-artifact-probe: not yet implemented")
    return 0


def cmd_lockfile_baseline(argv: List[str]) -> int:
    """Capture pre-move requirements.lock and sbom.spdx.json digests (Phase 22.2).
    
    Records hash baselines for ai/swarm and ai/datasource components so
    post-move regeneration can be verified (ledger #37).
    """
    # TODO: Implement in Phase 22.2
    print("phase22.lockfile-baseline: not yet implemented")
    return 0


def cmd_lockfile_migrate(argv: List[str]) -> int:
    """Regenerate requirements.lock and sbom.spdx.json for new root paths (Phase 22.2).
    
    Usage:
        make phase22.lockfile-migrate PACKAGE=<pkg>
    
    Regenerates lockfiles and SBOMs after a package move, verifying they differ
    from pre-move baseline (ledger #37).
    """
    # TODO: Implement in Phase 22.2
    print("phase22.lockfile-migrate: not yet implemented")
    return 0


def cmd_collision_map(argv: List[str]) -> int:
    """Cross-check every destination for two-source collisions (Phase 22.2).
    
    Emits docs/decisions/phase22/common_merge.md decision stubs for each
    colliding+differing file (ledger #27, #43, #44).
    """
    # TODO: Implement in Phase 22.2
    print("phase22.collision-map: not yet implemented")
    return 0


def cmd_verify_no_loss(argv: List[str]) -> int:
    """Verify file-accountability, blob-SHA preservation, and no forced moves (Phase 22.2).
    
    Usage:
        make phase22.verify-no-loss PACKAGE=<pkg>
    
    Asserts for a package that:
    - Every source file is accounted for (moved, merged, or deleted with reason)
    - No destination received two sources without a recorded decision
    - No git mv used -f flag
    - Every verbatim-moved file is byte-identical (except authorised rewrites)
    
    Implements ledger #43–#45.
    """
    # TODO: Implement in Phase 22.2
    print("phase22.verify-no-loss: not yet implemented")
    return 0


def cmd_rollback_codemod(argv: List[str]) -> int:
    """Rollback codemod rewrites for a package (Phase 22.2 bullet 8).
    
    Restores all files from `.phase22.orig` sidecars, deletes sidecars,
    and re-runs isolation checks.
    
    Usage:
        make phase22.rollback STEP=codemod PACKAGE=<pkg>
    
    Implements rollback safety (Phase 22.2 bullet 8).
    """
    import os
    
    package = os.environ.get("PACKAGE", "")
    if not package:
        err("PACKAGE environment variable not set")
        print("Usage: make phase22.rollback STEP=codemod PACKAGE=<pkg>")
        return 1
    
    # Find all .phase22.orig sidecars
    ai_path = REPO_ROOT / "ai" / package
    non_ai_paths = []
    
    # Also scan non-ai/ callers that were touched
    inventory_path = REPO_ROOT / "docs" / "tracking" / "phase22_import_report.json"
    if inventory_path.exists():
        try:
            with open(inventory_path, "r", encoding="utf-8") as f:
                inventory = json.load(f)
            by_package = inventory.get("by_package", {})
            if package in by_package:
                non_ai_paths = [
                    REPO_ROOT / f for f in by_package[package].get("files", [])
                ]
        except (json.JSONDecodeError, OSError):
            pass
    
    # Collect all sidecar files
    sidecar_files: List[Path] = []
    
    # From ai/<package>/
    if ai_path.exists():
        for sidecar in ai_path.glob("**/*.phase22.orig"):
            sidecar_files.append(sidecar)
    
    # From non-ai/ callers
    for caller_path in non_ai_paths:
        sidecar = caller_path.parent / (caller_path.name + ".phase22.orig")
        if sidecar.exists():
            sidecar_files.append(sidecar)
    
    if not sidecar_files:
        print(f"No .phase22.orig sidecars found for package '{package}'")
        # Still run isolation check for safety verification even if no sidecars
        print(f"\nRunning 'make isolation.check --full' to verify safety...")
        result = subprocess.run(
            ["make", "isolation.check", "--full"],
            cwd=REPO_ROOT,
            capture_output=False,
        )
        if result.returncode == 0:
            print(f"✓ Isolation check passed (no rollback needed)")
        else:
            err(f"Isolation check failed")
        return result.returncode
    
    print(f"\nRolling back {len(sidecar_files)} rewritten files for package '{package}':\n")
    
    restored_count = 0
    failed_count = 0
    
    for sidecar in sorted(sidecar_files):
        # Original file path (remove .phase22.orig suffix)
        # For a file like "config.py.phase22.orig", we want "config.py"
        orig_file = Path(str(sidecar).replace('.phase22.orig', ''))
        
        rel_orig = orig_file.relative_to(REPO_ROOT)
        rel_sidecar = sidecar.relative_to(REPO_ROOT)
        
        try:
            # Restore from sidecar
            sidecar_content = sidecar.read_bytes()
            orig_file.write_bytes(sidecar_content)
            
            # Delete sidecar
            sidecar.unlink()
            
            print(f"  ✓ Restored {rel_orig} from {rel_sidecar}")
            restored_count += 1
        except Exception as e:
            err(f"Failed to restore {rel_orig}: {e}")
            failed_count += 1
    
    print(f"\nRollback summary:")
    print(f"  Restored: {restored_count} files")
    if failed_count > 0:
        print(f"  Failed:   {failed_count} files")
        return 1
    
    # Run isolation.check --full
    print(f"\nRunning 'make isolation.check --full' to verify safety...")
    result = subprocess.run(
        ["make", "isolation.check", "--full"],
        cwd=REPO_ROOT,
        capture_output=False,
    )
    
    if result.returncode == 0:
        print(f"✓ Isolation check passed after rollback")
    else:
        err(f"Isolation check failed after rollback")
    
    return result.returncode


def cmd_rollback(argv: List[str]) -> int:
    """Rollback a migration step (Phase 22.2 bullet 8).
    
    Usage:
        make phase22.rollback STEP=codemod PACKAGE=<pkg>
    
    Dispatches to the appropriate rollback handler based on STEP.
    """
    import os
    
    step = os.environ.get("STEP", "")
    if not step:
        err("STEP environment variable not set")
        print("Usage: make phase22.rollback STEP=codemod PACKAGE=<pkg>")
        return 1
    
    if step == "codemod":
        return cmd_rollback_codemod(argv)
    else:
        err(f"Unknown rollback step: {step}")
        print("Supported steps: codemod")
        return 1


def cmd_burn_in_status(argv: List[str]) -> int:
    """Report five burn-in counter values (Phase 22.2).
    
    Queries Redis for:
    - isolation_regressions
    - ai_import_errors
    - resurrections
    - metric_name_violations
    - rollback_invocations
    
    Implements ledger #35.
    """
    # TODO: Implement in Phase 22.2
    print("phase22.burn-in.status: not yet implemented")
    return 0


def cmd_k8s_scan(argv: List[str]) -> int:
    """Scan infra/k8s/ for ai/ path references (Phase 22.2).
    
    YAML-aware scanner that finds ai/ references in ConfigMap, Deployment,
    init-container, and Helm chart specs (ledger #13).
    """
    # TODO: Implement in Phase 22.2
    print("phase22.k8s-scan: not yet implemented")
    return 0


def cmd_metric_scan(argv: List[str]) -> int:
    """List non-conforming metric names from TelemetrySink calls (Phase 22.2).
    
    Scans for metrics that don't conform to the pattern:
    ^(datasource|swarm|server|common|patcher|gitops)_[a-z0-9_]+_(seconds|bytes|total|ratio|count|gauge)$
    
    Produces a list for remediation in §22.9.
    """
    # TODO: Implement in Phase 22.2
    print("phase22.metric-scan: not yet implemented")
    return 0


COMMANDS = {
    "inventory": cmd_inventory,
    "import-report": cmd_import_report,
    "preflight": cmd_preflight,
    "codemod": cmd_codemod,
    "codemod-all": cmd_codemod_all,
    "cycle-check": cmd_cycle_check,
    "dead-code": cmd_dead_code,
    "go-path-check": cmd_go_path_check,
    "swarm-collision-check": cmd_swarm_collision_check,
    "conftest-inventory": cmd_conftest_inventory,
    "patcher-artifact-probe": cmd_patcher_artifact_probe,
    "lockfile-baseline": cmd_lockfile_baseline,
    "lockfile-migrate": cmd_lockfile_migrate,
    "collision-map": cmd_collision_map,
    "verify-no-loss": cmd_verify_no_loss,
    "rollback": cmd_rollback,
    "burn-in.status": cmd_burn_in_status,
    "k8s-scan": cmd_k8s_scan,
    "metric-scan": cmd_metric_scan,
}


def main(argv: List[str]) -> int:
    return dispatch(argv, COMMANDS, script_name="phase22.py")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
