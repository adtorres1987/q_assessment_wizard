# -*- coding: utf-8 -*-
"""
SpatialVersion — domain entity representing an immutable spatial result snapshot.

Phase 3 will introduce versionado real de overlays. This model defines the
concept now so the rest of the domain is aware of it.

No QGIS dependency. No database access.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class SpatialVersion:
    """An immutable snapshot of a spatial analysis result.

    Analogous to a Git commit: once created, a version is never overwritten.
    Rolling back means moving a HEAD pointer, not recalculating anything.

    Attributes:
        scenario_id:       FK to the owning Scenario.
        table_name:        SpatiaLite table that holds the geometry for this version.
        description:       Human-readable description of what this version represents.
        parent_version_id: Previous version (for chain navigation). None = root.
        id:                DB primary key (None until persisted).
        created_at:        ISO-8601 timestamp (populated after persistence).
        is_current:        True when this version is the active HEAD for its scenario.
    """

    scenario_id: int
    table_name: str

    description: str = ''
    parent_version_id: Optional[int] = None
    id: Optional[int] = None
    created_at: str = ''
    is_current: bool = True

    # ------------------------------------------------------------------ #
    #  Properties
    # ------------------------------------------------------------------ #

    @property
    def is_persisted(self) -> bool:
        """True when the version has been saved to the database."""
        return self.id is not None

    @property
    def is_root(self) -> bool:
        """True when this version has no parent (first analysis run)."""
        return self.parent_version_id is None

    def __str__(self) -> str:
        head_marker = ' [HEAD]' if self.is_current else ''
        parent = f' ← v{self.parent_version_id}' if self.parent_version_id else ''
        return (
            f"SpatialVersion(scenario={self.scenario_id}, "
            f"table={self.table_name!r}{parent}{head_marker})"
        )
