"""Versioning chart CLI — read & mutate ``xops/versioning/chart.json``.

Stdlib-only. Importable as a library (used by tests and the Makefile
dispatcher) and runnable as a script.

Concepts
--------
* **Project version** (`project.version`): SemVer for the umbrella
  Negelir application. Bumped explicitly via ``bump --component project``.
* **Build counter** (`project.build`): monotonically incremented on
  every successful component bump. Reset to ``0`` whenever
  ``project.version`` itself is bumped.
* **Component versions**: SemVer for each tracked main component
  (`ai`, `server`, `xops`, `docs`, `infra_mock`, `source_watcher`, …).
* **Changelog**: append-only list of bump events for audit/history.

Discipline
----------
Per AGENTS.md §versioning, every change to a tracked component must
be paired with a ``bump`` call in the same commit. The
``test_chart_is_canonical`` round-trip test guards against hand edits.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

CHART_PATH = Path(__file__).resolve().parent / "chart.json"

LEVELS = ("major", "minor", "patch")
PROJECT_KEY = "project"
SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


# ── Errors ────────────────────────────────────────────────────


class VersionChartError(RuntimeError):
    """Raised on any chart-format or bump-rule violation."""


# ── Pure helpers ──────────────────────────────────────────────


def parse_semver(value: str) -> Tuple[int, int, int]:
    match = SEMVER_RE.match(value or "")
    if not match:
        raise VersionChartError(f"not a SemVer triple: {value!r}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def format_semver(parts: Tuple[int, int, int]) -> str:
    return ".".join(str(p) for p in parts)


def bump_semver(current: str, level: str) -> str:
    if level not in LEVELS:
        raise VersionChartError(f"level must be one of {LEVELS}, got {level!r}")
    major, minor, patch = parse_semver(current)
    if level == "major":
        return format_semver((major + 1, 0, 0))
    if level == "minor":
        return format_semver((major, minor + 1, 0))
    return format_semver((major, minor, patch + 1))


def now_utc() -> str:
    """ISO-8601 UTC timestamp truncated to seconds (matches tracker CLI)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ── Chart I/O ─────────────────────────────────────────────────


def load_chart(path: Path = CHART_PATH) -> Dict[str, Any]:
    if not path.exists():
        raise VersionChartError(f"chart not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        chart = json.load(fh)
    validate_chart(chart)
    return chart


def save_chart(chart: Dict[str, Any], path: Path = CHART_PATH) -> None:
    validate_chart(chart)
    text = json.dumps(chart, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")


def validate_chart(chart: Dict[str, Any]) -> None:
    if chart.get("schema") != 1:
        raise VersionChartError("chart.schema must be 1")
    project = chart.get(PROJECT_KEY)
    if not isinstance(project, dict):
        raise VersionChartError("chart.project missing")
    parse_semver(project.get("version", ""))
    if not isinstance(project.get("build"), int) or project["build"] < 0:
        raise VersionChartError("chart.project.build must be a non-negative int")
    components = chart.get("components")
    if not isinstance(components, dict) or not components:
        raise VersionChartError("chart.components must be a non-empty object")
    for name, data in components.items():
        if not isinstance(data, dict):
            raise VersionChartError(f"component {name!r} must be an object")
        parse_semver(data.get("version", ""))
        if "description" not in data or "last_changed" not in data:
            raise VersionChartError(
                f"component {name!r} missing description/last_changed"
            )
    validate_compatibility(chart)
    changelog = chart.get("changelog")
    if not isinstance(changelog, list):
        raise VersionChartError("chart.changelog must be a list")


def resolve_component_alias(chart: Dict[str, Any], component_key: str) -> Tuple[str, bool]:
    """Resolve a component key through the alias window.

    Returns (canonical_key, is_alias) where is_alias=True if the input key
    was an alias. Raises VersionChartError if the key is not found or the
    alias target does not exist.
    """
    components = chart.get("components", {})
    
    if component_key not in components:
        raise VersionChartError(
            f"component {component_key!r} not found; "
            f"known: {sorted(components)}"
        )
    
    data = components[component_key]
    if isinstance(data, dict) and "aliased_to" in data:
        # This key is an alias
        target = data["aliased_to"]
        if target not in components:
            raise VersionChartError(
                f"component {component_key!r} aliases to unknown target {target!r}"
            )
        return (target, True)
    
    # This key is canonical (not an alias)
    return (component_key, False)


def validate_compatibility(chart: Dict[str, Any]) -> None:
    """Validate per-component compatibility floors.

    Optional shape on each component entry::

        {
            "min_compatible_with": {
                "other_component": "X.Y.Z"
            }
        }

    For every declared floor, the referenced component must exist and its
    current version must be greater-than-or-equal to the pinned minimum.
    """
    components = chart.get("components")
    if not isinstance(components, dict):
        raise VersionChartError("chart.components must be a non-empty object")

    for component_name, data in components.items():
        if not isinstance(data, dict):
            raise VersionChartError(f"component {component_name!r} must be an object")

        min_map = data.get("min_compatible_with")
        if min_map is None:
            continue
        if not isinstance(min_map, dict):
            raise VersionChartError(
                f"component {component_name!r} min_compatible_with must be an object"
            )

        for other_component, required_version in min_map.items():
            if other_component not in components:
                raise VersionChartError(
                    f"component {component_name!r} requires unknown component "
                    f"{other_component!r}"
                )
            required = str(required_version)
            required_parts = parse_semver(required)
            other_version = str(components[other_component].get("version", ""))
            other_parts = parse_semver(other_version)
            if other_parts < required_parts:
                raise VersionChartError(
                    f"component {component_name!r} requires {other_component!r} "
                    f">= {required}, found {other_version}"
                )


# ── Bump operation ────────────────────────────────────────────


def bump_component(
    chart: Dict[str, Any],
    component: str,
    level: str,
    note: str = "",
    *,
    timestamp: str = "",
) -> Dict[str, Any]:
    """Mutate ``chart`` in place and return the changelog entry written.

    ``component`` can be ``"project"`` for the umbrella version, or any
    key from ``chart.components``.
    """
    ts = timestamp or now_utc()
    entry: Dict[str, Any] = {
        "timestamp": ts,
        "component": component,
        "level": level,
        "note": note,
    }

    if component == PROJECT_KEY:
        old = chart[PROJECT_KEY]["version"]
        new = bump_semver(old, level)
        chart[PROJECT_KEY]["version"] = new
        chart[PROJECT_KEY]["build"] = 0
        entry.update({"from": old, "to": new, "build": 0})
    else:
        components = chart["components"]
        if component not in components:
            raise VersionChartError(
                f"unknown component {component!r}; "
                f"known: {sorted(components)}"
            )
        old = components[component]["version"]
        new = bump_semver(old, level)
        components[component]["version"] = new
        components[component]["last_changed"] = ts
        chart[PROJECT_KEY]["build"] = chart[PROJECT_KEY]["build"] + 1
        entry.update(
            {
                "from": old,
                "to": new,
                "build": chart[PROJECT_KEY]["build"],
            }
        )

    chart.setdefault("changelog", []).append(entry)
    return entry


# ── Rename operation ──────────────────────────────────────────


def rename_component(
    chart: Dict[str, Any],
    old_name: str,
    new_name: str,
    note: str = "",
    *,
    timestamp: str = "",
) -> Dict[str, Any]:
    """Rename a component key in the chart and record the change.

    Preserves the version number and all metadata. Returns the changelog entry.
    """
    ts = timestamp or now_utc()

    components = chart["components"]
    if old_name not in components:
        raise VersionChartError(
            f"component {old_name!r} not found; known: {sorted(components)}"
        )
    if new_name in components:
        raise VersionChartError(
            f"component {new_name!r} already exists in chart"
        )

    # Move the component data
    old_data = components.pop(old_name)
    old_version = old_data.get("version", "")
    components[new_name] = old_data

    # Record the rename in the changelog
    entry: Dict[str, Any] = {
        "timestamp": ts,
        "component": f"{old_name} → {new_name}",
        "level": "rename",
        "from": old_name,
        "to": new_name,
        "version": old_version,
        "note": note,
    }
    chart.setdefault("changelog", []).append(entry)
    return entry


# ── CLI ───────────────────────────────────────────────────────


def cmd_show(args: argparse.Namespace) -> int:
    chart = load_chart()
    project = chart[PROJECT_KEY]
    print(
        f"{project['name']} v{project['version']} (build {project['build']})"
    )
    print()
    print("Components:")
    width = max(len(name) for name in chart["components"])
    for name in sorted(chart["components"]):
        data = chart["components"][name]
        # Check if this component is an alias
        is_deprecated = "aliased_to" in data
        status_mark = " ⚠️  (deprecated)" if is_deprecated else ""
        print(
            f"  {name.ljust(width)}  v{data['version']}  "
            f"— {data['description']}{status_mark}"
        )
    if args.changelog:
        print()
        print("Changelog (most recent last):")
        for entry in chart["changelog"][-args.changelog :]:
            note = f" — {entry['note']}" if entry.get("note") else ""
            print(
                f"  [{entry['timestamp']}] {entry['component']} "
                f"{entry['from']} → {entry['to']} ({entry['level']}, "
                f"build {entry['build']}){note}"
            )
    return 0


def cmd_bump(args: argparse.Namespace) -> int:
    chart = load_chart()
    
    # Handle --to-1.0.0 gate (Bullet 2)
    if args.to_1_0_0:
        component = args.component
        canonical, is_alias = resolve_component_alias(chart, component)
        
        # Check three required conditions for 1.0.0 bump
        repo_root = CHART_PATH.parent.parent.parent
        
        # Resolve component path with special mappings
        if component == "datasource_scraper":
            component_path = repo_root / "scraper"
        elif component == "datasource_watcher":
            component_path = repo_root / "watcher"
            if not component_path.exists():
                component_path = repo_root / "ai" / "datasource" / "watcher"
        elif component == "datasource_refresher":
            component_path = repo_root / "refresher"
            if not component_path.exists():
                component_path = repo_root / "ai" / "datasource" / "refresher"
        else:
            # Try Phase 22 layout first (root-level)
            component_path = repo_root / component.replace("_", "/")
            # Fall back to Phase 18 layout (ai/)
            if not component_path.exists():
                component_path = repo_root / "ai" / component.replace("_", "/")
        
        # (a) <component>/PUBLIC_API.md must exist
        public_api_path = component_path / "PUBLIC_API.md"
        if not public_api_path.exists():
            raise VersionChartError(
                f"cannot bump {component!r} to 1.0.0: "
                f"{public_api_path} does not exist"
            )
        
        # (b) <component>/tests/test_public_api_compat.py must exist
        compat_test_path = component_path / "tests" / "test_public_api_compat.py"
        if not compat_test_path.exists():
            raise VersionChartError(
                f"cannot bump {component!r} to 1.0.0: "
                f"{compat_test_path} does not exist"
            )
        
        # (c) docs/coding/component_versioning.md must exist
        versioning_doc = repo_root / "docs" / "coding" / "component_versioning.md"
        if not versioning_doc.exists():
            raise VersionChartError(
                f"cannot bump {component!r} to 1.0.0: "
                f"{versioning_doc} does not exist"
            )
        
        # All checks passed; bump to 1.0.0
        entry = bump_component(
            chart,
            component=canonical,
            level="major",  # Semantic: move from 0.x.x to 1.0.0
            note=args.note or "frozen public API",
        )
        save_chart(chart)
        print(
            f"✅ {entry['component']}: {entry['from']} → {entry['to']} "
            f"({entry['level']}); project build = {chart[PROJECT_KEY]['build']}"
        )
        return 0
    
    # Standard bump (no --to-1.0.0)
    entry = bump_component(
        chart,
        component=args.component,
        level=args.level,
        note=args.note or "",
    )
    save_chart(chart)
    print(
        f"✅ {entry['component']}: {entry['from']} → {entry['to']} "
        f"({entry['level']}); project build = {chart[PROJECT_KEY]['build']}"
    )
    return 0


def cmd_rename(args: argparse.Namespace) -> int:
    chart = load_chart()
    entry = rename_component(
        chart,
        old_name=args.component,
        new_name=args.new_name,
        note=args.note or "",
    )
    save_chart(chart)
    print(
        f"✅ {entry['from']} → {entry['to']} (v{entry['version']})"
    )
    return 0


def check_top_level_compatibility(chart: Dict[str, Any]) -> List[str]:
    """Check the top-level ``compatibility`` block; return list of violation messages.

    Reads ``chart.compatibility`` (a dict of ``{component: {min_compatible_with:
    {other: version}}}``), compares each pinned floor against the current version
    from ``chart.components``, and returns a list of human-readable violation
    strings (empty list = all constraints satisfied).
    """
    compat = chart.get("compatibility")
    if compat is None:
        return []
    if not isinstance(compat, dict):
        raise VersionChartError("chart.compatibility must be an object")

    components = chart.get("components", {})
    violations: List[str] = []

    for component_name, data in compat.items():
        if not isinstance(data, dict):
            raise VersionChartError(
                f"compatibility[{component_name!r}] must be an object"
            )
        min_map = data.get("min_compatible_with", {})
        if not isinstance(min_map, dict):
            raise VersionChartError(
                f"compatibility[{component_name!r}].min_compatible_with must be an object"
            )
        for other_component, required_version in min_map.items():
            if other_component not in components:
                violations.append(
                    f"compatibility[{component_name!r}] references unknown "
                    f"component {other_component!r}"
                )
                continue
            required_parts = parse_semver(str(required_version))
            other_version = str(components[other_component].get("version", ""))
            other_parts = parse_semver(other_version)
            if other_parts < required_parts:
                violations.append(
                    f"compatibility[{component_name!r}] requires "
                    f"{other_component!r} >= {required_version}, "
                    f"found {other_version}"
                )

    return violations


def cmd_compatibility_check(_args: argparse.Namespace) -> int:
    """Exit 0 if all top-level compatibility constraints are satisfied, 1 otherwise."""
    chart = load_chart()
    violations = check_top_level_compatibility(chart)
    if violations:
        for msg in violations:
            print(f"\u274c {msg}", file=sys.stderr)
        return 1
    print("\u2705 all compatibility constraints satisfied")
    return 0


def cmd_validate(_args: argparse.Namespace) -> int:
    load_chart()  # raises on bad
    print("\u2705 chart.json is valid")
    return 0


def cmd_components(_args: argparse.Namespace) -> int:
    chart = load_chart()
    for name in sorted(chart["components"]):
        print(name)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="version.py",
        description="Negelir versioning chart CLI.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    show = sub.add_parser("show", help="Print the project + component table.")
    show.add_argument(
        "--changelog",
        type=int,
        default=0,
        metavar="N",
        help="Also print the last N changelog entries.",
    )
    show.set_defaults(func=cmd_show)

    bump = sub.add_parser("bump", help="Bump a component (or project) version.")
    bump.add_argument(
        "--component",
        required=True,
        help="Component key from chart.json, or 'project' for umbrella.",
    )
    bump.add_argument(
        "--level",
        default=None,
        choices=LEVELS,
        help="SemVer level to bump (ignored if --to-1.0.0 used).",
    )
    bump.add_argument(
        "--to-1.0.0",
        dest="to_1_0_0",
        action="store_true",
        help="Bump to 1.0.0 (frozen API). Requires PUBLIC_API.md, test_public_api_compat.py, and component_versioning.md.",
    )
    bump.add_argument(
        "--note",
        default="",
        help="Short human note appended to the changelog entry.",
    )
    
    def validate_bump_args(args: argparse.Namespace) -> None:
        if args.to_1_0_0:
            if args.level:
                raise argparse.ArgumentTypeError("--level and --to-1.0.0 are mutually exclusive")
        else:
            if not args.level:
                raise argparse.ArgumentTypeError("--level required unless --to-1.0.0 is used")
    
    bump.set_defaults(func=cmd_bump, validate=validate_bump_args)

    rename = sub.add_parser("rename", help="Rename a component key.")
    rename.add_argument(
        "--component",
        required=True,
        help="Current component key to rename.",
    )
    rename.add_argument(
        "--new-name",
        required=True,
        dest="new_name",
        help="New component key name.",
    )
    rename.add_argument(
        "--note",
        default="",
        help="Short human note appended to the changelog entry.",
    )
    rename.set_defaults(func=cmd_rename)

    val = sub.add_parser("validate", help="Validate chart.json.")
    val.set_defaults(func=cmd_validate)

    comps = sub.add_parser("components", help="List component keys.")
    comps.set_defaults(func=cmd_components)

    compat_check = sub.add_parser(
        "compatibility-check",
        help="Validate top-level compatibility constraints in chart.json.",
    )
    compat_check.set_defaults(func=cmd_compatibility_check)

    return parser


def main(argv: List[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    
    # Call validate if it exists (used by bump command)
    if hasattr(args, 'validate'):
        try:
            args.validate(args)
        except argparse.ArgumentTypeError as e:
            print(f"❌ {e}", file=sys.stderr)
            return 2
    
    try:
        return int(args.func(args))
    except VersionChartError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
