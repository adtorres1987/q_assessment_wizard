# -*- coding: utf-8 -*-
"""
Project — domain entity representing an assessment project.

Holds metadata only. No QGIS dependency. No database access.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Project:
    """Domain entity: a named project with one SpatiaLite database.

    Attributes:
        name:              Unique project name (also used as the .sqlite filename stem).
        db_path:           Relative path to the project's SpatiaLite file
                           (e.g. "projects/my_project.sqlite").
        id:                Database primary key (None until persisted).
        description:       Optional human-readable description.
        db_type:           Backend type: 'spatialite' | 'postgresql' | 'geodatabase'.
        base_layer_names:  Names of the base layers associated with this project
                           (cached from admin.sqlite for fast tree display).
        qgs_project_file:  Path to the linked .qgs/.qgz file (optional).
        is_deleted:        True when the project has been soft-deleted.
    """

    name: str
    db_path: str

    id: Optional[int] = None
    description: str = ''
    db_type: str = 'spatialite'
    base_layer_names: List[str] = field(default_factory=list)
    qgs_project_file: str = ''
    is_deleted: bool = False

    # ------------------------------------------------------------------ #
    #  Properties
    # ------------------------------------------------------------------ #

    @property
    def is_persisted(self) -> bool:
        """True when the project has been saved to the database."""
        return self.id is not None

    @property
    def display_name(self) -> str:
        """Name shown in the TreeView (may be extended in future with version tag)."""
        return self.name

    # ------------------------------------------------------------------ #
    #  Factory helpers
    # ------------------------------------------------------------------ #

    @classmethod
    def from_dict(cls, data: dict) -> 'Project':
        """Build a Project from an AdminManager row dict."""
        import json
        raw_layers = data.get('base_layer_names', '')
        if raw_layers:
            try:
                layer_names = json.loads(raw_layers)
            except (ValueError, TypeError):
                layer_names = []
        else:
            layer_names = []

        return cls(
            id=data.get('id'),
            name=data.get('name', ''),
            description=data.get('description', ''),
            db_path=data.get('db_path', ''),
            db_type=data.get('db_type', 'spatialite'),
            base_layer_names=layer_names,
            qgs_project_file=data.get('qgs_project_file', ''),
            is_deleted=bool(data.get('is_deleted', False)),
        )
