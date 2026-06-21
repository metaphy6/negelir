# Phase 22.3b — Conftest Consolidation Plan

**Status:** Phase 22.3b bullet 1 (planning & kickoff)

**Created:** 2026-06-21

**Document:** Binding reference for all conftest.py consolidation during Phase 22.3b and beyond.

---

## Inventory: All Six Conftest Files

Per **Ledger Row #41** (`docs/planning/ROADMAP.md` §22.0), there are **six** conftest.py files in the repo:

### 1. Root conftest.py (`./conftest.py`)

**Path:** `/home/tech/code/negelir/conftest.py`

**Scope:** Top-level pytest configuration for the entire project.

**Responsibilities:**
- Detects Phase 18 → Phase 22 layout via `_phase22_layout` check (`ROOT / "common" / "config" / "__init__.py"` exists)
- Manages `sys.path`:
  - Phase 22+: Ensures repo root is first in `sys.path` (to resolve top-level `common` before `ai/common`)
  - Phase 18: Leaves path alone (ai/ in path via PYTHONPATH)
- Clears stale `common` module from `sys.modules` in Phase 22+ (in case it was imported as `ai/common` first)
- **Registers global pytest markers:**
  - `live`: opt-in tests hitting real upstreams
  - `cpu_only`: Phase 11 parity tests (CPU vs device identical output)
  - `slow`: tests taking noticeable wall time (excluded by `make test.fast`)
- **Enforces backup directory permissions** (0o600 on all files under `data/backups/`) — one-time per session

**Key code:**
```python
_phase22_layout = (ROOT / "common" / "config" / "__init__.py").exists()

if _phase22_layout:
    # Repo root first; Phase 22+ uses top-level common
    if _root_str in sys.path:
        sys.path.remove(_root_str)
    sys.path.insert(0, _root_str)
else:
    # Phase 18: ai/ in path via PYTHONPATH; do not manipulate
    pass

# In pytest_configure:
if _phase22_layout:
    # Clear stale ai/common import if present
    if 'common' in sys.modules:
        common_module = sys.modules['common']
        if '/ai/common' in common_module.__file__:
            sys.modules.pop('common', None)
            # Also remove submodules
```

**Migration status (Phase 22.3b):** ✓ Retained as primary; see consolidation logic below.

---

### 2. ai/tests/conftest.py (`./ai/tests/conftest.py`)

**Path:** `/home/tech/code/negelir/ai/tests/conftest.py`

**Scope:** AI test suite configuration (Phase 18 transitional layout).

**Responsibilities:**
- Detects Phase 18 → Phase 22 layout (same check as root)
- **Manages `sys.path` per-phase:**
  - Phase 22+: Imports cfg from `common.config` (root), adds root to sys.path first, then ai/ for nlp/* imports
  - Phase 18: Ensures ai/ is first; clears cached `common` modules to force re-import from ai/common
- **Imports cfg** from the right location based on layout
- **Sets up hypothesis profile** (CI-safe: `database=None`, `derandomize=True`, max_examples from cfg)
- **Registers pytest markers:**
  - `integration`: end-to-end tests with real data
  - `chaos`: Phase 12 resilience tests
- **Provides fixture:** `clear_default_scaler_noise_windows` (monkeypatches cfg to disable time-based noise)

**Migration status (Phase 22.3b):** ⚠️ Moves to `tests/conftest.py`; content is merged with root conftest, stale parts removed (see consolidation below).

---

### 3. common/tests/conftest.py (`./common/tests/conftest.py`)

**Path:** `/home/tech/code/negelir/common/tests/conftest.py`

**Scope:** Minimal; relies on root conftest.py.

**Content:** Single docstring comment:
```python
# The root conftest.py handles sys.path setup for the repo root,
# ensuring that top-level 'common' imports work even with PYTHONPATH=ai.
```

**Migration status (Phase 22.3b):** ✓ Retained as-is (does not move); stays under `common/tests/conftest.py`.

---

### 4. ai/swarm/agents/tests/conftest.py (`./ai/swarm/agents/tests/conftest.py`)

**Path:** `/home/tech/code/negelir/ai/swarm/agents/tests/conftest.py`

**Scope:** Phase 7 security-critical isolation for swarm-agent tests.

**Responsibilities:**
- **Autouse fixture:** `_restore_phase7_cfg_knobs` — snapshots and restores Phase 7 security config knobs around every test
  - Prevents mutation leaks across tests (e.g., a test that lowers `sec_input_max_len` must not affect the next test)
  - Binding for Phase 7 test isolation; non-negotiable
  - Tuple of 48 Phase 7 knob names (all security-related config)
- Runs even on test failure (try/finally semantics)

**Migration status (Phase 22.3b):** ⏳ Moves in §22.3c (swarm merge); stays in its current location (`swarm/agents/tests/conftest.py`) after move.

---

### 5. ai/swarm/agents/maint/tests/conftest.py (`./ai/swarm/agents/maint/tests/conftest.py`)

**Path:** `/home/tech/code/negelir/ai/swarm/agents/maint/tests/conftest.py`

**Scope:** Maint-agent test isolation.

**Responsibilities:**
- **Autouse fixture:** `clear_default_scaler_noise_windows` — identical to fixture in ai/tests/conftest.py
  - Monkeypatches cfg to disable time-based scaler noise (Phase 8.15.9 feature)
  - Tests exercising that feature override the fixture explicitly

**Migration status (Phase 22.3b):** ⏳ Moves in §22.3c (swarm merge); stays in its current location (`swarm/agents/maint/tests/conftest.py`) after move.

---

### 6. xops/backup/tests/conftest.py (`./xops/backup/tests/conftest.py`)

**Path:** `/home/tech/code/negelir/xops/backup/tests/conftest.py`

**Scope:** Backup tooling test configuration.

**Responsibilities:**
- Imports and registers `xops.backup.secret_smoke` pytest plugin (via comment `# registers plugin via pytest_configure`)
- Single-line registration; minimal

**Migration status (Phase 22.3b):** ✓ Retained as-is; stays under `xops/backup/tests/conftest.py` (not touched in Phase 22.3b).

---

## Consolidation Strategy

**Goal:** Merge `ai/tests/conftest.py` into a new root-level `tests/conftest.py` while retaining critical functionality and removing stale Phase 18 baggage.

### Phase 22.3b (Tests Merge): What Moves

- **Source:** `ai/tests/conftest.py` → **Destination:** `tests/conftest.py`
- **Merge partner:** Root `conftest.py` (already exists; provides the primary layout detection)
- **Action:** Create `tests/conftest.py` with consolidated logic

### Phase 22.3c (Swarm Merge): What Moves Later

- **Source:** `ai/swarm/agents/tests/conftest.py` → **Destination:** `swarm/agents/tests/conftest.py` (stays in place after directory move)
- **Source:** `ai/swarm/agents/maint/tests/conftest.py` → **Destination:** `swarm/agents/maint/tests/conftest.py` (stays in place after directory move)

**These two remain separate and are reconciled in §22.3c, not in §22.3b.**

### Untouched (Already at Root)

- `common/tests/conftest.py` — stays as-is
- `xops/backup/tests/conftest.py` — stays as-is

---

## Consolidation Logic (Binding)

### Step 1: Create `tests/conftest.py`

**Content:** Union of the **useful** portions of root `conftest.py` and `ai/tests/conftest.py`:

| Feature | Root source | AI source | Post-merge decision | Reason |
|---|---|---|---|---|
| Phase 22 layout detection (`_phase22_layout`) | ✓ (primary) | ✓ (duplicate) | Keep root's version; AI version removed | Root is authoritative |
| `sys.path` management (Phase 22+) | ✓ (correct) | ⚠️ (has stale logic) | Root version + AI's insertion of ai/ for nlp/* | Phase 22+: root first, ai/ second (nlp imports from ai/) |
| `sys.path` management (Phase 18) | ✓ (correct) | ⚠️ (stale) | Root version only | Phase 18 code in root conftest is sufficient |
| `sys.modules` clearing | ✓ (careful) | ⚠️ (too aggressive) | Root version only; AI version removed | AI's blanket clear of `common.*` is Phase 18 baggage |
| cfg import & hypothesis setup | ✗ | ✓ (belongs in tests) | Move to `tests/conftest.py` | Tests need the hypothesis profile |
| Marker registration (root markers) | ✓ | ✗ | Keep: `live`, `cpu_only`, `slow` | Global scope markers |
| Marker registration (AI markers) | ✗ | ✓ | Keep: `integration`, `chaos` | AI-layer-specific markers |
| Backup permission enforcement | ✓ | ✗ | Keep | One-time per session; scoped to data/backups |
| `clear_default_scaler_noise_windows` fixture (phase 8 maint) | ✗ | ✓ | Move to `tests/conftest.py` | Needed by any test importing cfg |

### Step 2: Marker Deduplication

**After merge, the marker set is:**
- `live` (root)
- `cpu_only` (root)
- `slow` (root)
- `integration` (from AI)
- `chaos` (from AI)

**Verification:** Grep for all `config.addinivalue_line("markers", ...)` — should appear **exactly 5 times**, one per marker. No duplicates.

### Step 3: Fixture Consolidation

**`clear_default_scaler_noise_windows` fixture:**
- Exists in both `ai/tests/conftest.py` AND `ai/swarm/agents/maint/tests/conftest.py`
- Identical implementation
- Post-move locations:
  - **`tests/conftest.py`** (from ai/tests)
  - **`swarm/agents/maint/tests/conftest.py`** (stays; used by maint tests)
- **Action:** Keep in both places initially (§22.3c harmonizes if needed); tests override explicitly if they don't want the scaler noise clearing.

### Step 4: cfg Import

**Current state (Phase 22 layout):**
- Root `conftest.py` does NOT import cfg (not needed there)
- `ai/tests/conftest.py` imports cfg and sets up hypothesis

**Post-merge:**
- `tests/conftest.py` imports cfg and sets up hypothesis
- Fixtures in `tests/conftest.py` and `common/tests/conftest.py` can use cfg

---

## Remaining Conftest Files: No Merge

### `common/tests/conftest.py` — Stays Untouched

**Path:** `common/tests/conftest.py`

**Reason:** Minimal file that just documents that root conftest handles sys.path. Merging it into root conftest.py doesn't change behavior.

**Post-Phase-22:** Still present; can be deleted in a later phase if desired (low priority).

---

### `swarm/agents/tests/conftest.py` — Phase 7 Isolation Fixture

**Current path:** `ai/swarm/agents/tests/conftest.py`

**Moves to:** `swarm/agents/tests/conftest.py` (in §22.3c)

**Why separate:** Phase 7 security isolation is non-negotiable; cannot be merged without risking test contamination. Stays local to swarm agents.

---

### `swarm/agents/maint/tests/conftest.py` — Maint-Specific Fixture

**Current path:** `ai/swarm/agents/maint/tests/conftest.py`

**Moves to:** `swarm/agents/maint/tests/conftest.py` (in §22.3c)

**Why separate:** Maint tests are physically separate from general swarm agents; local conftest provides clear test isolation.

---

### `xops/backup/tests/conftest.py` — Plugin Registration

**Path:** `xops/backup/tests/conftest.py`

**Why it stays:** Already at root; not touched in Phase 22.3b.

---

## Pyproject.toml Update

**Current `testpaths`:**
```toml
testpaths = ["ai/tests", "common/tests", "swarm/tests", "server/tests"]
```

**Phase 22.3b update (after tests merge):**
```toml
testpaths = ["tests", "common/tests", "swarm/tests", "server/tests"]
```

**Rationale:** Add `tests/` (root AI test suite post-merge) alongside existing paths.

**Timing:** Updated in the same commit as the first conftest reconciliation to avoid transient test-discovery failures.

---

## Testing Strategy

### Before Moving Any Files

**Baseline (current state with ai/tests):**
```bash
cd /home/tech/code/negelir
PYTHONPATH=. make test.fast  # Should pass
# OR manually:
pytest ai/tests/ common/tests/ -q
```

### During §22.3b (Creating tests/ Directory and Conftest)

**Transient state: both old and new paths exist:**
- `ai/tests/` ← old path (will be renamed)
- `tests/` ← new path (newly created, will receive contents)
- `tests/conftest.py` ← new consolidated conftest

**Verification after creating `tests/conftest.py` with consolidated logic:**
```bash
pytest tests/ common/tests/ swarm/tests/ -q
# Should pass with zero import errors, cfg loaded correctly, hypothesis profile active
```

### After Moving Test Files (§22.3b)

**Final state: only new paths remain:**
- `tests/` ← root AI tests (former `ai/tests/`)
- `common/tests/` ← common tests (unchanged)
- `swarm/tests/` ← swarm tests (unchanged, maint agents conftest moves in §22.3c)

**Verification:**
```bash
pytest tests/ common/tests/ swarm/tests/ -q
# Must pass
```

---

## Post-Merge Deferred Items

**These decisions are NOT made in §22.3b; they happen later:**

1. **Decide if `common/tests/conftest.py` should be deleted** — it's a 1-line comment. Minimal value.
   - Decision in: Phase 22.5 (post-migration cleanup)

2. **Harmonize swarm conftest fixtures** (`clear_default_scaler_noise_windows` in both `tests/` and `swarm/agents/maint/tests/`)
   - Decision in: §22.3c or Phase 22.5
   - Options: (a) keep both (minimal overhead), (b) remove from one (requires checking all callers)

3. **Audit if any fixtures in root `tests/conftest.py` are unused** — once the migration is stable
   - Target: Phase 22.13 (30-day burn-in) wrap-up

---

## File Accountability (Ledger #43)

**Sources moved in Phase 22.3b:**
| Source path | Destination | Action | Reason |
|---|---|---|---|
| `ai/tests/conftest.py` | `tests/conftest.py` | **Move** (after consolidation) | Test suite infrastructure consolidation |
| `ai/tests/**/*.py` (all test files) | `tests/**/*.py` | **Move** | Root test suite migration |

**Root conftest no longer edits (stays in place):**
| Path | Action | Reason |
|---|---|---|
| `conftest.py` | Retain as-is | Primary layout detection; referenced by multiple test runners |
| `common/tests/conftest.py` | Retain as-is | Minimal stub; can be cleaned up later |
| `xops/backup/tests/conftest.py` | Retain as-is | Plugin registration; not part of Phase 22.3b |

---

## Verification Checklist

- [ ] `tests/` directory created at repo root
- [ ] `tests/conftest.py` created with consolidated logic (see Step 1–3 above)
- [ ] Root `conftest.py` left unchanged
- [ ] `common/tests/conftest.py` left unchanged
- [ ] `xops/backup/tests/conftest.py` left unchanged
- [ ] `ai/swarm/agents/tests/conftest.py` remains in place (moves in §22.3c)
- [ ] `ai/swarm/agents/maint/tests/conftest.py` remains in place (moves in §22.3c)
- [ ] `pyproject.toml` `testpaths` updated to include `tests/`
- [ ] `PYTHONPATH=. pytest tests/ common/tests/ swarm/tests/ -q` passes
- [ ] No duplicate marker registrations (grep for `markers` line count)
- [ ] `cfg` imported correctly; hypothesis profile active
- [ ] Tracker row created
- [ ] `make version.bump` run
- [ ] Phase 22.3b bullet 1 checkbox ticked in ROADMAP

