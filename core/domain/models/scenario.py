# -*- coding: utf-8 -*-
"""
Scenario and LayerRef — core domain entities for an analysis run.

No QGIS dependency. All state is IDs, names, and enums.

Terminology mapping:
    Plugin UI term       → Domain term
    "Assessment"         → Scenario
    "Target layer"       → LayerRef(role=LayerRole.TARGET)
    "Assessment layer"   → LayerRef(role=LayerRole.ASSESSMENT)
    "Output table"       → listed in Scenario.output_tables
"""

from dataclasses import dataclass, field
from typing import List, Optional

from .layer_role import LayerRole


@dataclass
class LayerRef:
    """Value object: an immutable reference to a named spatial layer.

    Attributes:
        name:       Original layer name as it appears in the QGIS project.
        role:       Semantic role in the analysis (TARGET / ASSESSMENT / MARKER).
        table_name: Sanitized SpatiaLite table name — populated by the
                    infrastructure layer after migration. Empty string means
                    the layer has not yet been migrated.
    """

    name: str
    role: LayerRole
    table_name: str = ''

    @property
    def is_migrated(self) -> bool:
        """True once the layer has been copied into SpatiaLite."""
        return bool(self.table_name)

    def __str__(self) -> str:
        status = self.table_name if self.is_migrated else '<not migrated>'
        return f"LayerRef({self.role.value}: {self.name!r} → {status})"


@dataclass
class Scenario:
    """Aggregate root for one analysis run inside a project.

    Encapsulates the inputs (target + assessment layers) and outputs (tables)
    of a spatial overlay analysis. The domain object is built before any
    database or QGIS operations occur, making business logic testable in
    isolation.

    Attributes:
        project_id:         FK to the owning Project.
        name:               Unique scenario name within the project.
        description:        Optional human-readable description.
        target_layer:       The TARGET LayerRef (or None for simple assessments).
        assessment_layers:  List of ASSESSMENT LayerRefs.
        output_tables:      SpatiaLite table names produced by this scenario.
                            Populated after execution.
        id:                 DB primary key (None until persisted).
        is_deleted:         True when soft-deleted.
    """

    project_id: int
    name: str
    description: str = ''
    target_layer: Optional[LayerRef] = None
    assessment_layers: List[LayerRef] = field(default_factory=list)
    output_tables: List[str] = field(default_factory=list)
    id: Optional[int] = None
    is_deleted: bool = False

    # ------------------------------------------------------------------ #
    #  Computed properties
    # ------------------------------------------------------------------ #

    @property
    def is_spatial(self) -> bool:
        """True when the scenario has assessment layers (spatial analysis case)."""
        return bool(self.assessment_layers)

    @property
    def is_persisted(self) -> bool:
        """True when the scenario has been saved to the database."""
        return self.id is not None

    @property
    def all_layers(self) -> List[LayerRef]:
        """All LayerRefs: target first, then assessment layers."""
        layers = []
        if self.target_layer:
            layers.append(self.target_layer)
        layers.extend(self.assessment_layers)
        return layers

    @property
    def assessment_layer_names(self) -> List[str]:
        """Original names of all assessment layers."""
        return [lr.name for lr in self.assessment_layers]

    # ------------------------------------------------------------------ #
    #  Mutations (called by the application layer after migration)
    # ------------------------------------------------------------------ #

    def set_table_name(self, layer_name: str, table_name: str) -> None:
        """Record the SpatiaLite table name for a migrated layer.

        Args:
            layer_name:  Original QGIS layer name.
            table_name:  Sanitized SpatiaLite table name returned by the engine.
        """
        if self.target_layer and self.target_layer.name == layer_name:
            self.target_layer.table_name = table_name
        for lr in self.assessment_layers:
            if lr.name == layer_name:
                lr.table_name = table_name

    def add_output_table(self, table_name: str) -> None:
        """Append a result table name after a successful overlay operation."""
        if table_name not in self.output_tables:
            self.output_tables.append(table_name)

    # ------------------------------------------------------------------ #
    #  Factory helpers
    # ------------------------------------------------------------------ #

    @classmethod
    def from_dict(cls, data: dict, assessment_layers: Optional[List[str]] = None,
                  output_tables: Optional[List[str]] = None) -> 'Scenario':
        """Build a Scenario from an AdminManager assessment row dict."""
        target_name = data.get('target_layer', '')
        target_ref = LayerRef(name=target_name, role=LayerRole.TARGET) \
            if target_name else None

        a_layers = [
            LayerRef(name=n, role=LayerRole.ASSESSMENT)
            for n in (assessment_layers or [])
        ]

        return cls(
            id=data.get('id'),
            project_id=data.get('project_id'),
            name=data.get('name', ''),
            description=data.get('description', ''),
            target_layer=target_ref,
            assessment_layers=a_layers,
            output_tables=list(output_tables or []),
        )
