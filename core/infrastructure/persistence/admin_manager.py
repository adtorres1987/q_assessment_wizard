# -*- coding: utf-8 -*-
"""
AdminManager — metadata repository over the central admin.sqlite database.

Satisfies MetadataRepositoryPort by duck typing. The class only owns the
connection; each responsibility lives in its own mixin module:

  schema.py         table creation, column migrations, legacy table cleanup
  projects.py       projects + per-project SpatiaLite path and base layers
  assessments.py    assessments, assessment layers, layer visibility
  analysis.py       MCDA analysis config (weights) and per-version snapshots
  provenance.py     provenance records and task trees
  portfolios.py     portfolio (LPA) configurations
  legacy_import.py  one-off import from the old metadata.db

All mixins share ``self.connection`` / ``self.plugin_dir``. Add a new
responsibility as a new mixin module rather than growing an existing one.
"""

import sqlite3
import os

from .schema import SchemaMixin
from .projects import ProjectsMixin
from .assessments import AssessmentsMixin
from .analysis import AnalysisMixin
from .provenance import ProvenanceMixin
from .portfolios import PortfoliosMixin
from .legacy_import import LegacyImportMixin


class AdminManager(SchemaMixin, ProjectsMixin, AssessmentsMixin, AnalysisMixin,
                   ProvenanceMixin, PortfoliosMixin, LegacyImportMixin):
    """Manages project and assessment metadata in admin.sqlite."""

    def __init__(self, plugin_dir):
        self.plugin_dir = plugin_dir
        self.db_path = os.path.join(plugin_dir, "admin.sqlite")
        self.projects_dir = os.path.join(plugin_dir, "projects")
        self.connection = None

    # ------------------------------------------------------------------ #
    #  Connection
    # ------------------------------------------------------------------ #

    def connect(self):
        """Open SQLite connection, ensure schema and projects directory exist."""
        self.connection = sqlite3.connect(self.db_path)
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._create_tables()
        self._migrate_schema()
        self._drop_unused_tables()
        os.makedirs(self.projects_dir, exist_ok=True)

    def disconnect(self):
        """Close the SQLite connection."""
        if self.connection:
            self.connection.close()
            self.connection = None

    # ------------------------------------------------------------------ #
    #  Projects CRUD
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    #  Assessments CRUD
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    #  Analysis Configurations CRUD (MCDA weights)
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    #  Assessment Layers
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    #  Layer Visibility State
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    #  Provenance CRUD
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    #  Task Details CRUD
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    #  Portfolios (LPA configuration)
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    #  Analysis Results CRUD (new schema)
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    #  Utilities
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    #  Migration from metadata.db
    # ------------------------------------------------------------------ #

