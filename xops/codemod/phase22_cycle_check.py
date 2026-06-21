#!/usr/bin/env python3
"""Phase 22.2 bullet 6 — Cycle detection and topological sort.

Builds a directed import graph from all ai/ packages, detects cycles via
strongly connected components (Tarjan's algorithm), and produces a valid
topological sort order for safe sequential rewriting.

The dependency ordering is the safety mechanism — parallelising rewrites
defeats the cycle-detection guarantee.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from collections import defaultdict, deque
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))


class ImportGraphBuilder:
    """Builds a directed import graph from ai/ packages.
    
    Nodes are package names (e.g., 'ai.common', 'ai.nlp').
    Edges represent 'imports from' relationships (u → v means v depends on u).
    """
    
    def __init__(self, repo_root: Path = REPO_ROOT):
        self.repo_root = repo_root
        self.graph: Dict[str, Set[str]] = defaultdict(set)
        self.packages: Set[str] = set()
    
    def _extract_imports_from_ast(self, content: str) -> Set[str]:
        """Extract ai.* package names from Python source via AST.
        
        Returns a set of imported package names (e.g., {'ai.common', 'ai.nlp'}).
        """
        imports = set()
        try:
            tree = ast.parse(content, type_comments=False)
        except SyntaxError:
            return imports
        
        for node in ast.walk(tree):
            # from ai.X import Y
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("ai."):
                    # Extract the top-level package (ai.X)
                    parts = node.module.split(".")
                    if len(parts) >= 2:
                        pkg = f"{parts[0]}.{parts[1]}"
                        imports.add(pkg)
            # import ai.X
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("ai."):
                        parts = alias.name.split(".")
                        if len(parts) >= 2:
                            pkg = f"{parts[0]}.{parts[1]}"
                            imports.add(pkg)
        
        return imports
    
    def _get_package_from_path(self, file_path: Path) -> Optional[str]:
        """Extract the top-level package name from a file path.
        
        E.g., ai/common/config.py → ai.common
        """
        try:
            relative = file_path.relative_to(self.repo_root)
            parts = relative.parts
            if len(parts) >= 2 and parts[0] == "ai":
                return f"ai.{parts[1]}"
        except ValueError:
            pass
        return None
    
    def build(self) -> Dict[str, Set[str]]:
        """Build the import graph from all .py files under ai/.
        
        Returns the graph dict where graph[pkg] = {set of packages it imports from}.
        """
        # Find all .py files under ai/
        result = subprocess.run(
            ["find", str(self.repo_root / "ai"), "-type", "f", "-name", "*.py"],
            capture_output=True,
            text=True,
            check=True,
        )
        
        for line in result.stdout.strip().split("\n"):
            if not line or "__pycache__" in line:
                continue
            
            file_path = Path(line)
            pkg = self._get_package_from_path(file_path)
            if not pkg:
                continue
            
            self.packages.add(pkg)
            
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                imports = self._extract_imports_from_ast(content)
                # Filter to only ai.* packages (ignore stdlib, external deps)
                ai_imports = {imp for imp in imports if imp.startswith("ai.") and imp != pkg}
                self.graph[pkg].update(ai_imports)
            except (OSError, UnicodeDecodeError):
                pass
        
        # Ensure all packages are in the graph (even if they don't import anything)
        for pkg in self.packages:
            if pkg not in self.graph:
                self.graph[pkg] = set()
        
        return self.graph


class CycleDetector:
    """Detects cycles in a directed graph using Tarjan's strongly connected components.
    
    Uses Tarjan's algorithm to find SCCs; any SCC with size > 1 is a cycle.
    """
    
    def __init__(self, graph: Dict[str, Set[str]]):
        self.graph = graph
        self.index = 0
        self.stack: List[str] = []
        self.indices: Dict[str, int] = {}
        self.lowlinks: Dict[str, int] = {}
        self.on_stack: Set[str] = set()
        self.sccs: List[List[str]] = []
    
    def detect(self) -> Tuple[List[List[str]], bool]:
        """Run Tarjan's algorithm to find all SCCs.
        
        Returns (sccs, has_cycles) where has_cycles=True if:
        - Any SCC has size > 1, OR
        - Any node has a self-loop (imports itself)
        """
        # First, check for self-loops
        for node in self.graph:
            if node in self.graph.get(node, set()):
                # Self-loop detected
                return [[node]], True
        
        # Run Tarjan's algorithm
        for node in self.graph:
            if node not in self.indices:
                self._strongconnect(node)
        
        has_cycles = any(len(scc) > 1 for scc in self.sccs)
        return self.sccs, has_cycles
    
    def _strongconnect(self, v: str) -> None:
        """Tarjan's algorithm recursive step."""
        self.indices[v] = self.index
        self.lowlinks[v] = self.index
        self.index += 1
        self.stack.append(v)
        self.on_stack.add(v)
        
        for w in self.graph.get(v, set()):
            if w not in self.indices:
                self._strongconnect(w)
                self.lowlinks[v] = min(self.lowlinks[v], self.lowlinks[w])
            elif w in self.on_stack:
                self.lowlinks[v] = min(self.lowlinks[v], self.indices[w])
        
        if self.lowlinks[v] == self.indices[v]:
            scc = []
            while True:
                w = self.stack.pop()
                self.on_stack.discard(w)
                scc.append(w)
                if w == v:
                    break
            self.sccs.append(scc)


class TopologicalSorter:
    """Computes a valid topological sort of the dependency graph.
    
    Uses Kahn's algorithm (BFS-based) with tie-breaking for determinism.
    
    Note: The input graph is stored as node → {nodes it depends on}.
    We compute the sort order such that dependencies appear BEFORE dependents.
    E.g., if ai.model imports from ai.nlp, then ai.nlp appears before ai.model.
    """
    
    def __init__(self, graph: Dict[str, Set[str]]):
        self.graph = graph
    
    def sort(self) -> List[str]:
        """Compute a topological sort (packages in safe rewrite order).
        
        Returns a list of package names ordered such that no package appears
        before any of its dependencies.
        
        Note: The sort order represents dependency order (dependencies first).
        For rewriting, we process packages in this order to ensure all their
        dependencies have been rewritten before the package itself is rewritten.
        """
        # Build the reverse graph: if A imports from B, then B → A (B has outgoing edge to A)
        # This lets us process dependencies before dependents.
        reverse_graph: Dict[str, Set[str]] = {node: set() for node in self.graph}
        in_degree: Dict[str, int] = {node: 0 for node in self.graph}
        
        for node in self.graph:
            # self.graph[node] = {nodes this package imports from}
            for dependency in self.graph[node]:
                if dependency in reverse_graph:
                    reverse_graph[dependency].add(node)
                    in_degree[node] += 1
        
        # Initialize queue with nodes of in-degree 0 (no incoming edges)
        # These are "root" packages that don't import from other ai packages
        queue: deque[str] = deque(node for node in self.graph if in_degree[node] == 0)
        sorted_nodes: List[str] = []
        
        while queue:
            # Deterministic ordering: sort before processing for stable output
            current = min(queue)
            queue.remove(current)
            sorted_nodes.append(current)
            
            # Process dependents of the current node
            for dependent in sorted(reverse_graph.get(current, set())):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)
        
        # If not all nodes were processed, there's a cycle (shouldn't happen
        # if detect_cycles() was called first, but we check anyway)
        if len(sorted_nodes) != len(self.graph):
            raise ValueError(
                f"Topological sort incomplete; graph has cycles. "
                f"Processed {len(sorted_nodes)}/{len(self.graph)} nodes."
            )
        
        return sorted_nodes


def analyze_cycles_and_sort(repo_root: Path = REPO_ROOT) -> Tuple[Dict[str, any], int]:
    """Analyze the import graph for cycles and compute topological sort.
    
    Returns (result_dict, exit_code) where result_dict contains:
    - sccs: list of all strongly connected components
    - cycles: list of cycle components (SCCs with size > 1)
    - has_cycles: bool indicating if cycles were found
    - topo_sort: topological sort order (if no cycles)
    - packages: set of all packages found
    
    Exit code is 1 if cycles were found, 0 otherwise.
    """
    # Build the graph
    builder = ImportGraphBuilder(repo_root)
    graph = builder.build()
    
    # Detect cycles
    detector = CycleDetector(graph)
    sccs, has_cycles = detector.detect()
    
    result = {
        "sccs": sccs,
        "has_cycles": has_cycles,
        "cycles": [scc for scc in sccs if len(scc) > 1],
        "packages": sorted(builder.packages),
        "topo_sort": [],
    }
    
    if has_cycles:
        return result, 1
    
    # Compute topological sort
    sorter = TopologicalSorter(graph)
    topo_sort = sorter.sort()
    result["topo_sort"] = topo_sort
    
    return result, 0


def write_topo_sort_json(
    result: Dict[str, any],
    output_file: Path = REPO_ROOT / "docs" / "tracking" / "phase22_topo_sort.json",
) -> None:
    """Write the topological sort result to a JSON file.
    
    Includes metadata for persistence and comparison on subsequent runs.
    """
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    import time
    
    data = {
        "generated_at": time.time(),
        "packages": result["packages"],
        "topo_sort": result["topo_sort"],
        "has_cycles": result["has_cycles"],
        "cycles": result["cycles"],
        "description": (
            "Topological sort of ai/ packages for safe sequential rewriting. "
            "If has_cycles=true, rewriting is blocked until cycles are broken. "
            "Otherwise, packages should be rewritten in the order listed in topo_sort."
        ),
    }
    
    output_file.write_text(json.dumps(data, indent=2) + "\n")


def main() -> int:
    """CLI entry point: run cycle detection and write results."""
    result, exit_code = analyze_cycles_and_sort()
    
    if result["has_cycles"]:
        print("❌ CYCLES DETECTED — parallel rewriting is FORBIDDEN")
        print(f"\nFound {len(result['cycles'])} cycle(s):\n")
        for cycle in result["cycles"]:
            print(f"  {' → '.join(cycle)} → {cycle[0]}")
        print("\nRewriting is BLOCKED until all cycles are resolved.")
        print("Break the cycles by moving shared logic to a common/ subpackage.")
        return 1
    
    print("✅ No cycles detected — safe to proceed with sequential rewriting\n")
    print(f"Rewrite order ({len(result['topo_sort'])} packages):")
    for i, pkg in enumerate(result["topo_sort"], 1):
        print(f"  {i:2d}. {pkg}")
    
    # Write JSON for persistence
    write_topo_sort_json(result)
    print(f"\n✓ Topological sort written to docs/tracking/phase22_topo_sort.json")
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
