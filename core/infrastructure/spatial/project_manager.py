# -*- coding: utf-8 -*-
"""
ProjectManager — one project's SpatiaLite database (projects/<name>.sqlite).

The class owns the connection, the base schema and the base-layer registry;
the rest lives in mixins under ``project_db/``:

  spatialite.py      locating and loading mod_spatialite
  layer_migrator.py  QGIS layer → SpatiaLite table migration (+ type mapping)
  tables.py          exists / drop / rename / temp-table cleanup
  versions.py        immutable spatial version chain (HEAD pointer)
"""

import sqlite3
import os

from ...domain.rules.naming import sanitize_table_name
from .project_db.spatialite import SpatialiteLoaderMixin
from .project_db.layer_migrator import LayerMigrationMixin
from .project_db.tables import TablesMixin
from .project_db.versions import VersionsMixin


class ProjectManager(SpatialiteLoaderMixin, LayerMigrationMixin, TablesMixin, VersionsMixin):
    """Manages a per-project SpatiaLite database for spatial data."""

    def __init__(self, db_path):
        """
        Initialize project manager.

        Args:
            db_path: Absolute path to the project's .sqlite file
        """
        self.db_path = db_path
        self.connection = None

    # ------------------------------------------------------------------ #
    #  Connection
    # ------------------------------------------------------------------ #

    def connect(self):
        """Open SpatiaLite connection. Creates DB and initializes spatial metadata if new."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        is_new_db = not os.path.exists(self.db_path)

        self.connection = sqlite3.connect(self.db_path)
        self.connection.execute("PRAGMA foreign_keys = ON")

        # Load SpatiaLite extension
        self.connection.enable_load_extension(True)
        self._load_spatialite()

        # Initialize spatial metadata for new databases
        if is_new_db:
            self.connection.execute("SELECT InitSpatialMetaData(1)")
            self.connection.commit()

        self._create_tables()
        self.cleanup_temp_tables()

    def disconnect(self):
        """Close the SpatiaLite connection."""
        if self.connection:
            self.connection.close()
            self.connection = None

    def _create_tables(self):
        """Create registry tables if they do not exist."""
        cursor = self.connection.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS base_layers_registry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                layer_name TEXT UNIQUE NOT NULL,
                geometry_type TEXT DEFAULT '',
                srid INTEGER DEFAULT 4326,
                source TEXT DEFAULT '',
                feature_count INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS assessment_results_metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assessment_uuid TEXT NOT NULL,
                output_layer TEXT NOT NULL,
                operation TEXT NOT NULL,
                source_target TEXT DEFAULT '',
                source_assessment TEXT DEFAULT '',
                feature_count INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Phase 3: immutable version tracking per scenario (overlay analysis run)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS spatial_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scenario_name TEXT NOT NULL,
                table_name TEXT NOT NULL,
                description TEXT DEFAULT '',
                parent_version_id INTEGER DEFAULT NULL,
                is_current INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (parent_version_id) REFERENCES spatial_versions(id)
            )
        """)

        self.connection.commit()
        cursor.close()

    # ------------------------------------------------------------------ #
    #  Base Layers Registry
    # ------------------------------------------------------------------ #

    def register_base_layer(self, layer_name, geometry_type="", srid=4326,
                            source="", feature_count=0):
        """Register a base layer in the registry."""
        cursor = self.connection.cursor()
        cursor.execute(
            """INSERT OR REPLACE INTO base_layers_registry
               (layer_name, geometry_type, srid, source, feature_count)
               VALUES (?, ?, ?, ?, ?)""",
            (layer_name, geometry_type, srid, source, feature_count)
        )
        self.connection.commit()
        cursor.close()

    # ------------------------------------------------------------------ #
    #  Table operations
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    #  Layer migration (QGIS → SpatiaLite)
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    #  Table Operations
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    #  Spatial Versions  (Phase 3 — immutable version tracking)
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    #  Utilities
    # ------------------------------------------------------------------ #

    def sanitize_table_name(self, layer_name):
        """Convert layer name to valid SQLite table name.
        Preserves __ as separator between project and assessment names.
        """
        return sanitize_table_name(layer_name)

