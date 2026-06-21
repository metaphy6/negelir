"""Phase 10 §10.12 — Singleflight collapse test.

Validates that concurrent identical queries collapse to a single execution,
mirroring Phase 9 §9.17.4 singleflight contract.
"""
from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from swarm.sdk import Singleflight
from swarm.sdk.singleflight import _Flight


def test_singleflight_collapses_concurrent_identical_queries():
    """500 parallel calls with the same key → exactly 1 execution."""
    sf = Singleflight[str]()
    execution_count = {"value": 0}
    lock = threading.Lock()
    # Barrier ensures all threads start do() at the same time
    barrier = threading.Barrier(500)

    def do_work() -> str:
        with lock:
            execution_count["value"] += 1
        # Simulate some work
        time.sleep(0.01)
        return "result-abc"

    # Launch 500 concurrent calls with the same key
    results: list[str | None] = [None] * 500
    errors: list[Exception | None] = [None] * 500
    threads: list[threading.Thread] = []

    def worker(idx: int) -> None:
        # Wait for all threads to be ready
        barrier.wait()
        try:
            results[idx] = sf.do(key="abc", fn=do_work)
        except Exception as err:
            errors[idx] = err

    for i in range(500):
        t = threading.Thread(target=worker, args=(i,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # All 500 should have succeeded
    assert all(r == "result-abc" for r in results)
    assert all(e is None for e in errors)
    # But do_work() should have been called exactly once
    assert execution_count["value"] == 1


def test_singleflight_different_keys_execute_independently():
    """Different keys do not collapse."""
    sf = Singleflight[str]()
    execution_counts: dict[str, int] = {"key1": 0, "key2": 0}
    lock = threading.Lock()
    barrier = threading.Barrier(20)  # 10 threads per key

    def do_work_key1() -> str:
        with lock:
            execution_counts["key1"] += 1
        time.sleep(0.01)  # Simulate work
        return "result-key1"

    def do_work_key2() -> str:
        with lock:
            execution_counts["key2"] += 1
        time.sleep(0.01)  # Simulate work
        return "result-key2"

    # Run 10 concurrent calls per key
    results: list[str | None] = [None] * 20
    threads: list[threading.Thread] = []

    def worker_key1(idx: int) -> None:
        barrier.wait()
        results[idx] = sf.do(key="key1", fn=do_work_key1)

    def worker_key2(idx: int) -> None:
        barrier.wait()
        results[idx] = sf.do(key="key2", fn=do_work_key2)

    for i in range(10):
        t1 = threading.Thread(target=worker_key1, args=(i,))
        t2 = threading.Thread(target=worker_key2, args=(i + 10,))
        threads.extend([t1, t2])
        t1.start()
        t2.start()

    for t in threads:
        t.join()

    # Each key should have executed once
    assert execution_counts["key1"] == 1
    assert execution_counts["key2"] == 1
    # All results should be correct
    assert all(results[i] == "result-key1" for i in range(10))
    assert all(results[i] == "result-key2" for i in range(10, 20))


def test_singleflight_propagates_exception():
    """When fn() raises, all waiters receive the same exception."""
    sf = Singleflight[str]()
    barrier = threading.Barrier(100)

    class CustomError(Exception):
        pass

    def do_work() -> str:
        time.sleep(0.01)
        raise CustomError("work failed")

    results: list[str | None] = [None] * 100
    errors: list[Exception | None] = [None] * 100
    threads: list[threading.Thread] = []

    def worker(idx: int) -> None:
        barrier.wait()
        try:
            results[idx] = sf.do(key="failing-key", fn=do_work)
        except Exception as err:
            errors[idx] = err

    for i in range(100):
        t = threading.Thread(target=worker, args=(i,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # All should have gotten the error
    assert all(r is None for r in results)
    assert all(isinstance(e, CustomError) for e in errors)
    assert all(str(e) == "work failed" for e in errors if e is not None)


def test_singleflight_inflight_count():
    """inflight_count() returns the number of active keys."""
    sf = Singleflight[str]()
    barrier = threading.Barrier(5)  # 4 workers + 1 main thread

    def do_work() -> str:
        # Wait until all 4 threads have entered do_work
        barrier.wait()
        time.sleep(0.05)
        return "done"

    threads: list[threading.Thread] = []

    def worker(key: str) -> None:
        sf.do(key=key, fn=do_work)

    # Launch 4 threads with 4 different keys
    for i in range(4):
        t = threading.Thread(target=worker, args=(f"key-{i}",))
        threads.append(t)
        t.start()

    # Wait for all to enter
    barrier.wait()
    # At this point, all 4 should be inflight
    assert sf.inflight_count() == 4

    for t in threads:
        t.join()

    # After completion, inflight should be zero
    assert sf.inflight_count() == 0


def test_singleflight_sequential_calls_do_not_share():
    """Sequential calls with the same key execute independently (not a cache)."""
    sf = Singleflight[int]()
    counter = {"value": 0}
    lock = threading.Lock()

    def do_work() -> int:
        with lock:
            counter["value"] += 1
            return counter["value"]

    # First call
    result1 = sf.do(key="same", fn=do_work)
    assert result1 == 1

    # Second call with same key (should execute again, not reuse)
    result2 = sf.do(key="same", fn=do_work)
    assert result2 == 2

    # Third call
    result3 = sf.do(key="same", fn=do_work)
    assert result3 == 3


# ── Phase 10 §10.21.2 — Singleflight sweeper tests ────────────────────


def test_singleflight_sweeper_drops_orphans():
    """Sweeper drops events older than event_max_age_s."""
    swept_events: list[int] = []

    def on_swept(count: int) -> None:
        swept_events.append(count)

    fake_clock = {"now": 0.0}

    def clock() -> float:
        return fake_clock["now"]

    sf = Singleflight[str](
        sweep_interval_s=0.1,  # sweep every 100ms (fast for test)
        event_max_age_s=1.0,  # orphan threshold = 1s
        on_swept=on_swept,
        clock=clock,
    )

    try:
        # Create an orphaned event by manually inserting it
        # (simpler than trying to create a stuck thread)
        with sf._lock:
            sf._inflight["orphan-1"] = _Flight[str](event=threading.Event())
            sf._inflight["orphan-1"].created_at = 0.0  # Created at t=0

        # Verify it's inflight
        assert sf.inflight_count() == 1

        # Advance clock past event_max_age_s (1.0s)
        fake_clock["now"] = 2.0

        # Wait for sweeper to run (runs every 0.1s)
        time.sleep(0.5)

        # Sweeper should have dropped it
        assert sf.inflight_count() == 0
        assert len(swept_events) >= 1
        assert swept_events[0] == 1
    finally:
        sf.stop()


# ── Phase 10 §10.21.4 — AST guard: singleflight is per-pod (no Redis) ────


def test_nlp_singleflight_does_not_use_redis():
    """§10.21.4: Singleflight scope is per-pod; no Redis coordination.
    
    AST scan rejects `redis.lock` import in:
    - ai/swarm/sdk/singleflight.py (the implementation)
    - ai/swarm/agents/nlp/dispatcher.py (when it exists — future NLP dispatcher)
    
    Rationale (per §10.21.4): Cross-pod collapse via Redis lock adds one Redis
    round-trip per query. At v1 scale (< 1000 qps), the cost outweighs the
    benefit. Each pod independently collapses duplicate requests using
    in-process threading.Event.
    """
    import ast
    import pathlib
    
    ai_dir = pathlib.Path(__file__).parent.parent
    
    # Paths to scan
    scan_paths = [
        ai_dir / "swarm" / "sdk" / "singleflight.py",
        ai_dir / "swarm" / "agents" / "nlp" / "dispatcher.py",  # future
    ]
    
    # Filter to only existing files
    scan_paths = [p for p in scan_paths if p.exists()]
    
    assert len(scan_paths) > 0, "singleflight.py must exist"
    
    violations: list[str] = []
    
    class _RedisLockChecker(ast.NodeVisitor):
        def __init__(self, filepath: pathlib.Path):
            self.filepath = filepath
        
        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # type: ignore[override]
            # Reject: from redis import lock, from redis.lock import ...
            if node.module is not None:
                if node.module.startswith("redis"):
                    # Check if any imported name contains 'lock'
                    if node.names:
                        for alias in node.names:
                            if "lock" in alias.name.lower():
                                rel_path = self.filepath.relative_to(ai_dir)
                                violations.append(
                                    f"{rel_path}:{node.lineno}: imports redis.lock "
                                    f"(violates §10.21.4 per-pod singleflight contract)"
                                )
            self.generic_visit(node)
        
        def visit_Import(self, node: ast.Import) -> None:  # type: ignore[override]
            # Reject: import redis.lock
            for alias in node.names:
                if "redis" in alias.name and "lock" in alias.name.lower():
                    rel_path = self.filepath.relative_to(ai_dir)
                    violations.append(
                        f"{rel_path}:{node.lineno}: imports redis.lock "
                        f"(violates §10.21.4 per-pod singleflight contract)"
                    )
            self.generic_visit(node)
        
        def visit_Attribute(self, node: ast.Attribute) -> None:  # type: ignore[override]
            # Reject: redis.lock(...) usage even if imported differently
            if node.attr == "lock":
                if isinstance(node.value, ast.Name):
                    if node.value.id == "redis":
                        rel_path = self.filepath.relative_to(ai_dir)
                        violations.append(
                            f"{rel_path}:{node.lineno}: uses redis.lock "
                            f"(violates §10.21.4 per-pod singleflight contract)"
                        )
            self.generic_visit(node)
    
    # Scan each file
    for py_file in scan_paths:
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))
            _RedisLockChecker(py_file).visit(tree)
        except SyntaxError:
            # Should not happen for committed code
            violations.append(f"{py_file}: syntax error during AST parse")
    
    assert violations == [], (
        "Singleflight uses Redis coordination (violates §10.21.4 per-pod contract). "
        "Cross-pod collapse is intentionally NOT implemented — the cost (Redis "
        "round-trip per query) outweighs the benefit at v1 scale. Violations:\n"
        + "\n".join(violations)
    )


def test_singleflight_max_inflight_enforced():
    """Over-cap → reject new do() calls and invoke on_overflow callback."""
    overflow_calls: list[int] = []

    def on_overflow(current: int) -> None:
        overflow_calls.append(current)

    sf = Singleflight[str](max_inflight=2, on_overflow=on_overflow)

    barrier = threading.Barrier(3)  # 2 workers + main thread

    def slow_work() -> str:
        barrier.wait()
        time.sleep(0.05)
        return "done"

    # Start 2 concurrent flights (at the limit)
    threads: list[threading.Thread] = []
    for i in range(2):

        def worker(key: str) -> None:
            sf.do(key=key, fn=slow_work)

        # Use closure to capture the current value of i
        t = threading.Thread(target=lambda k=f"key-{i}": worker(k))
        threads.append(t)
        t.start()

    # Wait for both to be inflight
    barrier.wait()
    time.sleep(0.02)
    assert sf.inflight_count() == 2

    # Try to start a third — should be rejected
    with pytest.raises(RuntimeError, match="Singleflight overflow"):
        sf.do(key="key-3", fn=slow_work)

    # on_overflow should have been called with current=2
    assert len(overflow_calls) == 1
    assert overflow_calls[0] == 2

    for t in threads:
        t.join()


def test_singleflight_sweeper_wakes_waiters_on_orphan():
    """When sweeper drops an orphaned event, waiters receive RuntimeError."""
    fake_clock = {"now": 0.0}

    def clock() -> float:
        return fake_clock["now"]

    sf = Singleflight[str](
        sweep_interval_s=0.1, event_max_age_s=1.0, clock=clock
    )

    try:
        # Manually insert an orphaned event
        with sf._lock:
            flight = _Flight[str](event=threading.Event())
            flight.created_at = 0.0  # Created at t=0
            sf._inflight["orphan"] = flight

        errors: list[Exception | None] = [None]

        def waiter() -> None:
            try:
                # This waiter will block on the event until sweeper sets error
                sf.do(key="orphan", fn=lambda: "never-called")
            except RuntimeError as err:
                errors[0] = err

        t_waiter = threading.Thread(target=waiter)
        t_waiter.start()

        time.sleep(0.05)  # Let waiter block on the event

        # Advance clock past event_max_age_s
        fake_clock["now"] = 2.0
        time.sleep(0.3)  # Wait for sweeper to run

        t_waiter.join(timeout=2.0)

        # Waiter should have received RuntimeError from sweeper
        assert errors[0] is not None
        assert "orphaned" in str(errors[0])
    finally:
        sf.stop()


def test_singleflight_no_sweeper_when_not_configured():
    """Singleflight without sweeper config works as before (backward compat)."""
    sf = Singleflight[int]()
    counter = {"value": 0}

    def do_work() -> int:
        counter["value"] += 1
        return counter["value"]

    result = sf.do(key="test", fn=do_work)
    assert result == 1
    assert sf.inflight_count() == 0
    # No sweeper thread should be running
    assert sf._sweeper_thread is None


# ── Phase 10 §10.21.4 — AST guard: lock ordering invariant ─────────────────


def test_nlp_lock_ordering_no_reverse_acquisition():
    """§10.21.4: Lock ordering invariant — lexicon → singleflight (never reverse).
    
    Across NLP plane, only two locks are held:
    (a) per-LexiconStore lock (self._lexicon_lock or self._lock in LexiconStore)
    (b) per-key singleflight lock/event (self._sf_lock, self._sf_event, or
        self._lock in Singleflight)
    
    Strict ordering: lexicon → singleflight (never reverse).
    
    This AST guard walks all NLP-plane Python files and:
    - Detects nested `with` blocks acquiring these locks
    - Rejects reverse ordering (singleflight → lexicon)
    - Allows lexicon → singleflight or no nesting
    
    Rationale: Enforcing a global lock hierarchy prevents deadlock.
    """
    import ast
    import pathlib
    
    ai_dir = pathlib.Path(__file__).parent.parent
    
    # Scan all NLP-plane Python files
    nlp_dirs = [
        ai_dir / "nlp",
        ai_dir / "swarm" / "agents" / "nlp",
        ai_dir / "swarm" / "sdk",  # includes singleflight.py
    ]
    
    scan_files: list[pathlib.Path] = []
    for dir_path in nlp_dirs:
        if dir_path.exists():
            scan_files.extend(dir_path.rglob("*.py"))
    
    # Filter out test files and __pycache__
    scan_files = [
        f for f in scan_files
        if "__pycache__" not in str(f) and not f.name.startswith("test_")
    ]
    
    violations: list[str] = []
    
    class _LockOrderChecker(ast.NodeVisitor):
        """AST visitor that detects nested lock acquisitions."""
        
        def __init__(self, filepath: pathlib.Path):
            self.filepath = filepath
            # Stack of (lock_type, lineno) tuples; lock_type in {"lexicon", "singleflight"}
            self.lock_stack: list[tuple[str, int]] = []
        
        def _classify_lock(self, node: ast.With) -> str | None:
            """Return 'lexicon' or 'singleflight' if the with-item is a known lock."""
            for item in node.items:
                # Check if this is `with self._lexicon_lock:` or similar
                if isinstance(item.context_expr, ast.Attribute):
                    attr_name = item.context_expr.attr
                    # Lexicon locks
                    if attr_name in ("_lexicon_lock",):
                        return "lexicon"
                    # Also check for _lock in LexiconStore context
                    if attr_name == "_lock":
                        # Heuristic: if the file path contains "lexicon", assume lexicon lock
                        if "lexicon" in str(self.filepath).lower():
                            return "lexicon"
                    # Singleflight locks/events
                    if attr_name in ("_sf_lock", "_sf_event"):
                        return "singleflight"
                    # Also check for _lock in singleflight.py
                    if attr_name == "_lock" and "singleflight" in str(self.filepath):
                        return "singleflight"
            return None
        
        def visit_With(self, node: ast.With) -> None:  # type: ignore[override]
            """Track nested with blocks and detect lock ordering violations."""
            lock_type = self._classify_lock(node)
            
            if lock_type is not None:
                # Check for reverse ordering violation
                if lock_type == "lexicon" and any(
                    lt == "singleflight" for lt, _ in self.lock_stack
                ):
                    # We're acquiring lexicon lock while holding singleflight lock
                    # This is REVERSE ordering — forbidden!
                    rel_path = self.filepath.relative_to(ai_dir)
                    violations.append(
                        f"{rel_path}:{node.lineno}: Reverse lock ordering detected: "
                        f"acquiring lexicon lock while holding singleflight lock "
                        f"(violates §10.21.4 lock ordering invariant: lexicon → singleflight)"
                    )
                
                # Push this lock onto the stack
                self.lock_stack.append((lock_type, node.lineno))
                # Visit nested nodes
                self.generic_visit(node)
                # Pop this lock from the stack
                self.lock_stack.pop()
            else:
                # Not a tracked lock, just visit children
                self.generic_visit(node)
    
    for filepath in scan_files:
        try:
            source = filepath.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(filepath))
            checker = _LockOrderChecker(filepath)
            checker.visit(tree)
        except (SyntaxError, UnicodeDecodeError) as exc:
            # Skip files that can't be parsed
            pass
    
    if violations:
        msg = "Lock ordering violations detected:\n" + "\n".join(violations)
        pytest.fail(msg)
    
    # If no violations, test passes (even if no locks were found — vacuous truth)


def test_nlp_no_io_under_lexicon_lock():
    """§10.21.4: Lexicon lock held only for pointer-swap (microseconds).
    
    The lexicon lock (self._lock in LexiconStore or self._lexicon_lock elsewhere)
    MUST NOT enclose any I/O, fastText predict, or CRF tag operations.
    
    This AST guard rejects `with self._lock:` or `with self._lexicon_lock:` blocks
    that contain:
    - open( — file I/O
    - requests. — network I/O
    - predict( — fastText/model inference
    - tag( — CRF tagging
    - predict_one( — single-item prediction
    
    Rationale (per §10.21.4): The lexicon lock is held only for atomic pointer-swap
    (target: < 50ms). Any GIL-releasing call inside the lock would block all
    in-flight requests attempting to read the lexicon → unacceptable latency spike.
    """
    import ast
    import pathlib
    
    ai_dir = pathlib.Path(__file__).parent.parent
    
    # Scan NLP-plane Python files (same scope as lock ordering test)
    nlp_dirs = [
        ai_dir / "nlp",
        ai_dir / "swarm" / "agents" / "nlp",
    ]
    
    scan_files: list[pathlib.Path] = []
    for dir_path in nlp_dirs:
        if dir_path.exists():
            scan_files.extend(dir_path.rglob("*.py"))
    
    # Filter out test files and __pycache__
    scan_files = [
        f for f in scan_files
        if "__pycache__" not in str(f) and not f.name.startswith("test_")
    ]
    
    violations: list[str] = []
    
    # Forbidden operation patterns (name → description)
    FORBIDDEN_OPS = {
        "open": "file I/O",
        "requests": "network I/O",
        "predict": "model inference",
        "tag": "CRF tagging",
        "predict_one": "single-item prediction",
    }
    
    class _NoIOUnderLockChecker(ast.NodeVisitor):
        """AST visitor that detects expensive ops inside lexicon lock blocks."""
        
        def __init__(self, filepath: pathlib.Path):
            self.filepath = filepath
            # Track whether we're currently inside a lexicon lock block
            self.inside_lexicon_lock = False
            self.lock_lineno: int | None = None
        
        def _is_lexicon_lock(self, node: ast.With) -> bool:
            """Return True if this with-statement acquires a lexicon lock."""
            for item in node.items:
                if isinstance(item.context_expr, ast.Attribute):
                    attr_name = item.context_expr.attr
                    # Lexicon lock names
                    if attr_name in ("_lexicon_lock", "_lock"):
                        # Heuristic: if the file contains "lexicon" or "locale_loader",
                        # assume _lock is the lexicon lock
                        if attr_name == "_lock" and (
                            "lexicon" in str(self.filepath).lower()
                            or "locale_loader" in str(self.filepath).lower()
                        ):
                            return True
                        if attr_name == "_lexicon_lock":
                            return True
            return False
        
        def visit_With(self, node: ast.With) -> None:  # type: ignore[override]
            """Track lexicon lock blocks and scan for forbidden operations."""
            if self._is_lexicon_lock(node):
                # We're entering a lexicon lock block
                old_inside = self.inside_lexicon_lock
                old_lineno = self.lock_lineno
                self.inside_lexicon_lock = True
                self.lock_lineno = node.lineno
                # Visit nested nodes
                self.generic_visit(node)
                # Restore state
                self.inside_lexicon_lock = old_inside
                self.lock_lineno = old_lineno
            else:
                # Not a lexicon lock, just visit children
                self.generic_visit(node)
        
        def visit_Call(self, node: ast.Call) -> None:  # type: ignore[override]
            """Check for forbidden operations inside lexicon lock blocks."""
            if self.inside_lexicon_lock:
                # Check if this call matches a forbidden operation
                call_name = None
                
                # Direct call: open(...)
                if isinstance(node.func, ast.Name):
                    call_name = node.func.id
                # Attribute call: requests.get(...), model.predict(...)
                elif isinstance(node.func, ast.Attribute):
                    # Check for requests.* (attribute is any method on requests module)
                    if isinstance(node.func.value, ast.Name) and node.func.value.id == "requests":
                        call_name = "requests"
                    # Check for method names
                    else:
                        call_name = node.func.attr
                
                # Check if call_name matches any forbidden operation
                if call_name and call_name in FORBIDDEN_OPS:
                    rel_path = self.filepath.relative_to(ai_dir)
                    op_desc = FORBIDDEN_OPS[call_name]
                    violations.append(
                        f"{rel_path}:{node.lineno}: Forbidden operation inside lexicon "
                        f"lock block (started at line {self.lock_lineno}): {call_name}(...) "
                        f"({op_desc}). Lexicon lock MUST be held only for pointer-swap "
                        f"(microseconds); GIL-releasing calls inside the lock block all "
                        f"in-flight requests (violates §10.21.4 bounded swap latency)."
                    )
            
            # Continue visiting nested nodes
            self.generic_visit(node)
    
    for filepath in scan_files:
        try:
            source = filepath.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(filepath))
            checker = _NoIOUnderLockChecker(filepath)
            checker.visit(tree)
        except (SyntaxError, UnicodeDecodeError):
            # Skip files that can't be parsed
            pass
    
    if violations:
        msg = (
            "Expensive operations detected inside lexicon lock blocks:\n"
            + "\n".join(violations)
        )
        pytest.fail(msg)
    
    # If no violations, test passes

