"""
Schema version migration framework for league catalog.

Migrations enable incremental schema evolution while maintaining
backwards compatibility. Each migration inherits from BaseMigration
and is registered in the MIGRATIONS dict.

Usage:
    For schema_version bump from 1 → 2:
    1. Create xops/leagues/migrations/1__to__2.py
    2. Define class Migration_1_to_2(BaseMigration)
    3. Migration is auto-discovered and registered

Per Phase 13.1: "Bumping `schema_version` requires a migration entry
under `xops/leagues/migrations/<from>__to__<to>.py`; lint gates the
field name set per version."
"""

from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseMigration(ABC):
    """Base class for all schema version migrations."""
    
    from_version: int
    to_version: int
    
    @abstractmethod
    def migrate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Migrate catalog data from from_version to to_version.
        
        Args:
            data: Raw catalog dict at from_version schema
        
        Returns:
            Migrated catalog dict at to_version schema
        """
        pass


# Registry of all available migrations: (from_version, to_version) → Migration class
MIGRATIONS: Dict[tuple[int, int], type[BaseMigration]] = {}


def register_migration(from_v: int, to_v: int) -> None:
    """Decorator to register a migration."""
    def decorator(cls: type[BaseMigration]) -> type[BaseMigration]:
        key = (from_v, to_v)
        if key in MIGRATIONS:
            raise ValueError(f"Migration {from_v}→{to_v} already registered")
        MIGRATIONS[key] = cls
        return cls
    return decorator
