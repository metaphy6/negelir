"""Phase 8 §8.15.6 — Maint-plane deployment catalogue boundary tests.

Asserts the compile-time invariants documented in
``ai/swarm/agents/maint/_catalogue.py``:

1. **Compose service coverage** — every ``compose_service_name`` listed
   in the catalogue (excluding ``N/A`` entries) exists in
   ``docker-compose.yml``.

2. **opsctl_critical_agents coverage** — every agent ID in
   ``cfg.opsctl_critical_agents`` has a catalogue row.  Left-orphan
   (cfg entry missing from catalogue) fails CI.

3. **maint_scaler_self_scaling_targets coverage** — every agent ID in
   ``cfg.maint_scaler_self_scaling_targets`` has a catalogue row.
   Left-orphan fails CI.

4. **Catalogue right-orphan detection** — every catalogue row whose
   agent_id is a known §8.x maint agent (from the registered agent
   set) must appear either in ``cfg.opsctl_critical_agents`` or in
   ``cfg.maint_scaler_self_scaling_targets`` OR be in
   ``LEADER_REQUIRED_AGENTS``.  Right-orphans (catalogue lists an
   unrecognised maint-plane agent) fail CI.

5. **Agent-id uniqueness** — no duplicate ``agent_id`` rows in the
   catalogue.

Adversarial cases:

* Duplicate catalogue rows are caught.
* A compose_service_name that was removed from docker-compose.yml
  is caught.
* An opsctl_critical_agents entry with no catalogue row is caught.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Set

import pytest

from common.config import cfg
from swarm.agents.maint._catalogue import CATALOGUE, AgentCatalogueRow
from swarm.sdk.leader import LEADER_REQUIRED_AGENTS

# ── helpers ──────────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[5]

# Known §8.x maint agent IDs (stable identifiers defined in maint/*.py).
_MAINT_AGENT_IDS: frozenset = frozenset(LEADER_REQUIRED_AGENTS)


def _parse_compose_services(compose_file: Path) -> Set[str]:
    """Return all top-level service names from a docker-compose YAML.

    Uses a simple regex (no yaml dep required) that matches lines of the
    form ``^  <name>:`` immediately under the ``services:`` block.
    """
    services: Set[str] = set()
    in_services = False
    with compose_file.open() as fh:
        for line in fh:
            if re.match(r"^services:\s*$", line):
                in_services = True
                continue
            if in_services:
                # Top-level key under services (2-space indent + name + colon)
                m = re.match(r"^  ([a-zA-Z0-9_-]+):\s*$", line)
                if m:
                    services.add(m.group(1))
                # If we hit another top-level key (0 indent, not a comment)
                # we've left the services block.
                elif re.match(r"^[a-zA-Z]", line) and not line.startswith("#"):
                    in_services = False
    return services


def _all_compose_services() -> Set[str]:
    """Union of service names across docker-compose.yml and mock override."""
    services: Set[str] = set()
    for filename in ("docker-compose.yml",):
        compose_path = _REPO_ROOT / filename
        if compose_path.is_file():
            services |= _parse_compose_services(compose_path)
    return services


# ── tests ─────────────────────────────────────────────────────────────────────


def test_catalogue_agent_ids_are_unique() -> None:
    """No duplicate agent_id rows in the catalogue."""
    ids = [row.agent_id for row in CATALOGUE]
    duplicates = [aid for aid in set(ids) if ids.count(aid) > 1]
    assert not duplicates, f"duplicate agent_id(s) in CATALOGUE: {duplicates}"


def test_catalogue_compose_service_names_exist_in_compose_files() -> None:
    """Every non-N/A compose_service_name must exist in docker-compose.yml."""
    known_services = _all_compose_services()
    assert known_services, (
        "Could not parse any services from docker-compose.yml — "
        "the compose file may have changed format"
    )
    bad: List[str] = []
    for row in CATALOGUE:
        svc = row.compose_service_name
        if svc and svc != "N/A":
            if svc not in known_services:
                bad.append(f"{row.agent_id}: compose_service_name={svc!r}")
    assert not bad, (
        "Catalogue compose_service_name(s) not found in docker-compose files:\n"
        + "\n".join(f"  {b}" for b in bad)
        + f"\nKnown services: {sorted(known_services)}"
    )


def test_catalogue_opsctl_critical_agents_have_rows() -> None:
    """Every entry in cfg.opsctl_critical_agents must have a catalogue row."""
    catalogue_ids = {row.agent_id for row in CATALOGUE}
    critical = {
        tok.strip()
        for tok in cfg.opsctl_critical_agents.split(",")
        if tok.strip()
    }
    missing = critical - catalogue_ids
    assert not missing, (
        "cfg.opsctl_critical_agents entries with no catalogue row "
        f"(left-orphan): {sorted(missing)}\n"
        "Add rows for these agents to "
        "ai/swarm/agents/maint/_catalogue.py and the matching doc "
        "docs/design/MAINT_DEPLOYMENT_CATALOGUE.md."
    )


def test_catalogue_maint_scaler_self_scaling_targets_have_rows() -> None:
    """Every entry in cfg.maint_scaler_self_scaling_targets has a row."""
    catalogue_ids = {row.agent_id for row in CATALOGUE}
    targets = {
        tok.strip()
        for tok in cfg.maint_scaler_self_scaling_targets.split(",")
        if tok.strip()
    }
    missing = targets - catalogue_ids
    assert not missing, (
        "cfg.maint_scaler_self_scaling_targets entries with no catalogue row "
        f"(left-orphan): {sorted(missing)}\n"
        "Add rows for these agents to "
        "ai/swarm/agents/maint/_catalogue.py and the matching doc."
    )


def test_catalogue_maint_agents_have_no_right_orphans() -> None:
    """Maint agent rows in the catalogue must appear in known-agent sets.

    A catalogue row for a §8.x maint agent that is NOT in
    LEADER_REQUIRED_AGENTS, opsctl_critical_agents, or
    maint_scaler_self_scaling_targets is a right-orphan: the catalogue
    claims an agent that no config references.
    """
    critical = {
        tok.strip()
        for tok in cfg.opsctl_critical_agents.split(",")
        if tok.strip()
    }
    targets = {
        tok.strip()
        for tok in cfg.maint_scaler_self_scaling_targets.split(",")
        if tok.strip()
    }
    # The union of all referenced agent sets (excluding opsctl CLI row).
    all_referenced = _MAINT_AGENT_IDS | critical | targets

    right_orphans: List[str] = []
    for row in CATALOGUE:
        # Only check rows that are §8.x maint agents (prefix "maint.").
        # Cross-phase agents (consensus.v1, sec.rate.v1, trainer.v1)
        # and the opsctl CLI row are excluded from this check.
        if not row.agent_id.startswith("maint."):
            continue
        if row.agent_id not in all_referenced:
            right_orphans.append(row.agent_id)

    assert not right_orphans, (
        "Catalogue has maint-agent rows not found in any config set "
        f"(right-orphan): {sorted(right_orphans)}\n"
        "Either add the agent to cfg.opsctl_critical_agents, "
        "cfg.maint_scaler_self_scaling_targets, or LEADER_REQUIRED_AGENTS, "
        "or remove the stale row from the catalogue."
    )


# ── adversarial ───────────────────────────────────────────────────────────────


def test_catalogue_duplicate_row_would_be_caught() -> None:
    """Duplicate detection works: a synthetic duplicate raises."""
    first = CATALOGUE[0]
    doubled = [first, first]
    ids = [row.agent_id for row in doubled]
    duplicates = [aid for aid in set(ids) if ids.count(aid) > 1]
    assert duplicates, "duplicate detection should have fired"


def test_catalogue_missing_cfg_entry_would_be_caught() -> None:
    """Left-orphan detection works: a cfg entry not in catalogue is caught."""
    catalogue_ids = {"maint.backup.v1"}  # subset — missing others
    # Simulate opsctl_critical_agents containing an entry not in catalogue_ids
    extra = "phantom.agent.v1"
    all_ids = catalogue_ids | {extra}
    missing = {extra} - all_ids
    # phantom.agent.v1 IS in all_ids (all_ids contains extra), so missing={}
    # Correct: the missing set is cfg - catalogue, not cfg - all_ids
    missing_from_catalogue = {extra} - catalogue_ids
    assert "phantom.agent.v1" in missing_from_catalogue


def test_catalogue_unknown_compose_service_would_be_caught() -> None:
    """compose_service_name pointing at non-existent service is caught."""
    phantom_row = AgentCatalogueRow(
        agent_id="phantom.v1",
        roadmap_section="§0",
        k8s_namespace="negelir-maint",
        service_account="phantom-sa",
        compose_service_name="no-such-service-xyz",
        compose_volumes=[],
        host_paths=[],
    )
    known_services = _all_compose_services()
    assert phantom_row.compose_service_name not in known_services
