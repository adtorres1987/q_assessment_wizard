# -*- coding: utf-8 -*-
"""
Admin Manager Module
Manages project and assessment metadata in a central admin.sqlite database.
Replaces metadata_manager.py with normalized schema, UUIDs, and project DB paths.

Active tables: projects, assessments, assessment_layers, layer_visibility_state,
provenance, task_details, app_settings, assessment_criteria, analyses,
analysis_weights, analysis_results.
"""

import sqlite3
import os
import re
import json
import uuid


class AdminManager:
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

    def _create_tables(self):
        """Create all admin tables if they do not exist (new-database schema)."""
        cursor = self.connection.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL UNIQUE,
                description TEXT DEFAULT '',
                db_path TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                is_deleted INTEGER DEFAULT 0,
                base_layer_names TEXT DEFAULT '',
                db_type TEXT DEFAULT 'spatialite',
                qgs_project_file TEXT DEFAULT '',
                db_connection_string TEXT DEFAULT '',
                workspace_paths TEXT DEFAULT ''
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS assessments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid TEXT UNIQUE NOT NULL,
                project_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                target_layer TEXT DEFAULT '',
                spatial_extent TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                is_deleted INTEGER DEFAULT 0,
                UNIQUE(project_id, name),
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS assessment_layers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assessment_id INTEGER NOT NULL,
                layer_name TEXT NOT NULL,
                layer_type TEXT NOT NULL CHECK(layer_type IN ('input', 'output', 'reference')),
                geometry_type TEXT DEFAULT '',
                FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS layer_visibility_state (
                assessment_id INTEGER NOT NULL,
                layer_name TEXT NOT NULL,
                visible INTEGER DEFAULT 1,
                PRIMARY KEY (assessment_id, layer_name),
                FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS provenance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid TEXT UNIQUE NOT NULL,
                assessment_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS task_details (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid TEXT UNIQUE NOT NULL,
                provenance_id INTEGER NOT NULL,
                parent_task_id INTEGER DEFAULT NULL,
                step_order INTEGER NOT NULL,
                operation TEXT NOT NULL,
                category TEXT DEFAULT '',
                input_tables TEXT DEFAULT '',
                output_tables TEXT DEFAULT '',
                db_type TEXT DEFAULT 'spatialite',
                added_to_map INTEGER DEFAULT 1,
                scenario TEXT DEFAULT '',
                symbology TEXT DEFAULT '',
                duration_ms INTEGER DEFAULT 0,
                parameters TEXT DEFAULT '',
                comments TEXT DEFAULT '',
                engine_type TEXT DEFAULT 'spatialite',
                is_scenario INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (provenance_id) REFERENCES provenance(id) ON DELETE CASCADE,
                FOREIGN KEY (parent_task_id) REFERENCES task_details(id) ON DELETE SET NULL
            )
        """)

        # App settings — single-row config table (EMDS 8 adaptation)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                plugin_version TEXT DEFAULT '',
                default_project_dir TEXT DEFAULT '',
                default_base_layers_group TEXT DEFAULT 'Base Layers',
                output_group_name TEXT DEFAULT 'Output Layers',
                symbology_defaults TEXT DEFAULT '',
                misc TEXT DEFAULT ''
            )
        """)
        cursor.execute("INSERT OR IGNORE INTO app_settings (id) VALUES (1)")

        # ── Analysis tables ───────────────────────────────────────────────

        # assessment_criteria — separates layer (data) from criterion (model)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS assessment_criteria (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assessment_id INTEGER NOT NULL,
                layer_name TEXT NOT NULL,
                criterion_name TEXT NOT NULL,
                criterion_type TEXT DEFAULT 'weighted',
                normalization_method TEXT DEFAULT 'minmax',
                weight_default REAL DEFAULT 0.0,
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE CASCADE
            )
        """)

        # analyses — one row per scenario/version, replaces analysis_configurations
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS analyses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assessment_id INTEGER NOT NULL,
                name TEXT DEFAULT 'Default',
                model_type TEXT DEFAULT 'weighted_sum',
                score_column TEXT DEFAULT 'MCDA_SCORE',
                status TEXT DEFAULT 'valid',
                weights_json TEXT DEFAULT '{}',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE CASCADE
            )
        """)

        # analysis_weights — normalized weight per analysis × criterion
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS analysis_weights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_id INTEGER NOT NULL,
                criterion_id INTEGER NOT NULL,
                weight REAL DEFAULT 0.0,
                normalized_weight REAL DEFAULT 0.0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (analysis_id) REFERENCES analyses(id) ON DELETE CASCADE,
                FOREIGN KEY (criterion_id) REFERENCES assessment_criteria(id) ON DELETE CASCADE
            )
        """)

        # analysis_results — metadata about overlay outputs (geometry lives in SpatiaLite)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS analysis_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_id INTEGER NOT NULL,
                output_table TEXT NOT NULL,
                output_layer_name TEXT DEFAULT '',
                feature_count INTEGER DEFAULT 0,
                min_score REAL DEFAULT 0.0,
                max_score REAL DEFAULT 0.0,
                mean_score REAL DEFAULT 0.0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (analysis_id) REFERENCES analyses(id) ON DELETE CASCADE
            )
        """)

        # portfolios — Portfolio (LPA) configurations built on an overlay
        # result. No solver yet: rows are stored with status 'pending'.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS portfolios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assessment_id INTEGER NOT NULL,
                source_table TEXT NOT NULL,
                name TEXT NOT NULL,
                config_json TEXT DEFAULT '{}',
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (assessment_id, name),
                FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE CASCADE
            )
        """)

        self.connection.commit()
        cursor.close()

    def _migrate_schema(self):
        """Apply incremental schema migrations for existing databases (idempotent).

        Each ALTER TABLE is wrapped in try/except so it is safe to call on
        both new and previously-existing databases.
        """
        migrations = [
            # (table, column, definition)
            ("projects",      "is_deleted",           "INTEGER DEFAULT 0"),
            ("projects",      "base_layer_names",     "TEXT DEFAULT ''"),
            ("projects",      "db_type",              "TEXT DEFAULT 'spatialite'"),
            ("projects",      "qgs_project_file",     "TEXT DEFAULT ''"),
            ("projects",      "db_connection_string", "TEXT DEFAULT ''"),
            ("projects",      "workspace_paths",      "TEXT DEFAULT ''"),
            ("assessments",   "is_deleted",           "INTEGER DEFAULT 0"),
            ("task_details",  "engine_type",          "TEXT DEFAULT 'spatialite'"),
            ("task_details",  "is_scenario",          "INTEGER DEFAULT 0"),
        ]
        cursor = self.connection.cursor()
        for table, column, definition in migrations:
            try:
                cursor.execute(
                    f'ALTER TABLE {table} ADD COLUMN {column} {definition}'
                )
            except Exception:
                pass  # column already exists — skip silently
        self.connection.commit()
        cursor.close()

    def _drop_unused_tables(self):
        """Drop legacy/unused tables from existing databases (idempotent)."""
        cursor = self.connection.cursor()
        for table in ('spatial_references', 'analysis_comparisons',
                      'workflow_steps', 'analysis_configurations'):
            cursor.execute(f"DROP TABLE IF EXISTS {table}")
        self.connection.commit()
        cursor.close()

    # ------------------------------------------------------------------ #
    #  Projects CRUD
    # ------------------------------------------------------------------ #

    def create_project(self, name, description=""):
        """Insert a new project and initialize its SpatiaLite database.
        Returns the new project id.
        """
        from .project_manager import ProjectManager

        project_uuid = str(uuid.uuid4())
        sanitized = self._sanitize_name(name)
        db_path = os.path.join("projects", f"{sanitized}.sqlite")

        cursor = self.connection.cursor()
        cursor.execute(
            "INSERT INTO projects (uuid, name, description, db_path) VALUES (?, ?, ?, ?)",
            (project_uuid, name, description, db_path)
        )
        self.connection.commit()
        project_id = cursor.lastrowid
        cursor.close()

        # Initialize the project's SpatiaLite database
        abs_db_path = os.path.join(self.plugin_dir, db_path)
        pm = ProjectManager(abs_db_path)
        pm.connect()
        pm.disconnect()

        return project_id

    def get_all_projects(self):
        """Return list of dicts with all non-deleted projects."""
        cursor = self.connection.cursor()
        cursor.execute(
            """SELECT id, uuid, name, description, db_path, created_at,
                      is_deleted, base_layer_names, db_type, qgs_project_file
               FROM projects WHERE is_deleted = 0 ORDER BY name"""
        )
        rows = cursor.fetchall()
        cursor.close()
        return [self._row_to_project(r) for r in rows]

    def get_project(self, project_id):
        """Return single project dict or None."""
        cursor = self.connection.cursor()
        cursor.execute(
            """SELECT id, uuid, name, description, db_path, created_at,
                      is_deleted, base_layer_names, db_type, qgs_project_file
               FROM projects WHERE id = ?""",
            (project_id,)
        )
        row = cursor.fetchone()
        cursor.close()
        return self._row_to_project(row) if row else None

    def get_project_by_name(self, name):
        """Return single project dict or None."""
        cursor = self.connection.cursor()
        cursor.execute(
            """SELECT id, uuid, name, description, db_path, created_at,
                      is_deleted, base_layer_names, db_type, qgs_project_file
               FROM projects WHERE name = ?""",
            (name,)
        )
        row = cursor.fetchone()
        cursor.close()
        return self._row_to_project(row) if row else None

    def _row_to_project(self, r):
        """Convert a projects DB row tuple to a dict."""
        return {
            'id': r[0], 'uuid': r[1], 'name': r[2],
            'description': r[3], 'db_path': r[4], 'created_at': r[5],
            'is_deleted': bool(r[6]) if len(r) > 6 else False,
            'base_layer_names': r[7] if len(r) > 7 else '',
            'db_type': r[8] if len(r) > 8 else 'spatialite',
            'qgs_project_file': r[9] if len(r) > 9 else '',
        }

    def delete_project(self, project_id):
        """Soft-delete a project and all its assessments (is_deleted = 1).

        The project's SpatiaLite file is kept on disk to preserve data.
        Use purge_project() to permanently remove the record and file.
        """
        cursor = self.connection.cursor()
        cursor.execute(
            "UPDATE projects SET is_deleted = 1 WHERE id = ?", (project_id,)
        )
        cursor.execute(
            "UPDATE assessments SET is_deleted = 1 WHERE project_id = ?", (project_id,)
        )
        self.connection.commit()
        cursor.close()

    def purge_project(self, project_id):
        """Permanently delete a project record and its SpatiaLite file from disk."""
        project = self.get_project(project_id)
        if not project:
            # Check deleted projects too
            cursor = self.connection.cursor()
            cursor.execute(
                "SELECT id, db_path FROM projects WHERE id = ?", (project_id,)
            )
            row = cursor.fetchone()
            cursor.close()
            if row:
                project = {'id': row[0], 'db_path': row[1]}

        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        self.connection.commit()
        cursor.close()

        if project and project.get('db_path'):
            abs_path = os.path.join(self.plugin_dir, project['db_path'])
            if os.path.exists(abs_path):
                try:
                    os.remove(abs_path)
                except OSError as e:
                    print(f"Warning: Could not delete project DB {abs_path}: {e}")

    def update_project_base_layers(self, project_id, layer_names):
        """Persist base layer names (list of str) to projects.base_layer_names as JSON."""
        cursor = self.connection.cursor()
        cursor.execute(
            "UPDATE projects SET base_layer_names = ? WHERE id = ?",
            (json.dumps(layer_names), project_id)
        )
        self.connection.commit()
        cursor.close()

    # ------------------------------------------------------------------ #
    #  Assessments CRUD
    # ------------------------------------------------------------------ #

    def create_assessment(self, project_id, name, description="",
                          target_layer="", spatial_extent="",
                          assessment_layers=None, output_tables=None):
        """Insert a new assessment. Returns the new assessment id.

        assessment_layers and output_tables are optional lists that get
        recorded in the normalized assessment_layers table.
        """
        assessment_uuid = str(uuid.uuid4())

        cursor = self.connection.cursor()
        cursor.execute(
            """INSERT INTO assessments
               (uuid, project_id, name, description, target_layer, spatial_extent)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (assessment_uuid, project_id, name, description, target_layer, spatial_extent)
        )
        self.connection.commit()
        assessment_id = cursor.lastrowid
        cursor.close()

        # Record input layers
        if assessment_layers:
            for layer_name in assessment_layers:
                self.add_assessment_layer(assessment_id, layer_name, 'input')

        # Record output layers
        if output_tables:
            for layer_name in output_tables:
                self.add_assessment_layer(assessment_id, layer_name, 'output')

        return assessment_id

    def get_assessments_for_project(self, project_id):
        """Return list of assessment dicts for a given project (non-deleted only)."""
        cursor = self.connection.cursor()
        cursor.execute(
            """SELECT id, uuid, project_id, name, description,
                      target_layer, spatial_extent, created_at
               FROM assessments
               WHERE project_id = ? AND is_deleted = 0
               ORDER BY name""",
            (project_id,)
        )
        rows = cursor.fetchall()
        cursor.close()

        assessments = []
        for r in rows:
            assessment_id = r[0]
            output_layers = self.get_assessment_layers(assessment_id, layer_type='output')
            output_tables = [l['layer_name'] for l in output_layers]
            assessments.append({
                'id': r[0], 'uuid': r[1], 'project_id': r[2],
                'name': r[3], 'description': r[4],
                'target_layer': r[5], 'spatial_extent': r[6],
                'created_at': r[7],
                'output_tables': output_tables
            })
        return assessments

    def get_assessment_count(self, project_id):
        """Return total assessments ever created for a project (for sequential group numbering).

        Includes soft-deleted records so group numbers are never reused.
        """
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM assessments WHERE project_id = ?", (project_id,)
        )
        count = cursor.fetchone()[0]
        cursor.close()
        return count

    # ------------------------------------------------------------------ #
    #  Analysis Configurations CRUD (MCDA weights)
    # ------------------------------------------------------------------ #

    def create_analysis_config(self, assessment_id, model_type='MCDA',
                               score_column='MCDA_SCORE', weights=None):
        """Insert or update the Default MCDA configuration for an assessment.

        Writes to 'analyses' and syncs 'assessment_criteria' + 'analysis_weights'.

        Args:
            assessment_id: int
            model_type:    str — e.g. 'MCDA' or 'weighted_sum'
            score_column:  str — name of the score column in the overlay table
            weights:       dict {layer_name: float} — values should sum to 1.0
        Returns:
            int: analysis_id of the inserted/updated record
        """
        weights_dict = weights or {}
        weights_json = json.dumps(weights_dict)
        cursor = self.connection.cursor()

        # ── New schema: upsert into 'analyses' ───────────────────────────
        cursor.execute(
            "SELECT id FROM analyses WHERE assessment_id = ? AND name = 'Default'",
            (assessment_id,)
        )
        row = cursor.fetchone()
        if row:
            analysis_id = row[0]
            cursor.execute(
                """UPDATE analyses
                   SET model_type = ?, score_column = ?, weights_json = ?, status = 'valid'
                   WHERE id = ?""",
                (model_type, score_column, weights_json, analysis_id)
            )
        else:
            cursor.execute(
                """INSERT INTO analyses
                       (assessment_id, name, model_type, score_column, status, weights_json)
                   VALUES (?, 'Default', ?, ?, 'valid', ?)""",
                (assessment_id, model_type, score_column, weights_json)
            )
            analysis_id = cursor.lastrowid

        # ── Sync normalized weights (delete + re-insert) ─────────────────
        cursor.execute("DELETE FROM analysis_weights WHERE analysis_id = ?", (analysis_id,))
        total = sum(weights_dict.values()) or 1.0
        for layer_name, weight in weights_dict.items():
            # Find or create criterion for (assessment, layer)
            cursor.execute(
                "SELECT id FROM assessment_criteria WHERE assessment_id = ? AND layer_name = ?",
                (assessment_id, layer_name)
            )
            crit_row = cursor.fetchone()
            if crit_row:
                criterion_id = crit_row[0]
                cursor.execute(
                    "UPDATE assessment_criteria SET weight_default = ? WHERE id = ?",
                    (weight, criterion_id)
                )
            else:
                cursor.execute(
                    """INSERT INTO assessment_criteria
                           (assessment_id, layer_name, criterion_name, weight_default)
                       VALUES (?, ?, ?, ?)""",
                    (assessment_id, layer_name, layer_name, weight)
                )
                criterion_id = cursor.lastrowid

            cursor.execute(
                """INSERT INTO analysis_weights
                       (analysis_id, criterion_id, weight, normalized_weight)
                   VALUES (?, ?, ?, ?)""",
                (analysis_id, criterion_id, weight, weight / total)
            )

        self.connection.commit()
        cursor.close()
        return analysis_id

    def get_analysis_config(self, assessment_id):
        """Return MCDA config dict for the given assessment, or None.

        Returns the Default config row from 'analyses'. If only versioned
        snapshots exist, returns the most recent one.

        Returns:
            dict with keys: id, assessment_id, model_type, score_column,
                            weights_json, created_at
        """
        cursor = self.connection.cursor()
        # Prefer the mutable 'Default' row; fall back to newest snapshot
        cursor.execute(
            """SELECT id, assessment_id, model_type, score_column, weights_json, created_at
               FROM analyses WHERE assessment_id = ?
               ORDER BY CASE WHEN name = 'Default' THEN 0 ELSE 1 END,
                        created_at DESC LIMIT 1""",
            (assessment_id,)
        )
        row = cursor.fetchone()
        cursor.close()
        if not row:
            return None
        return {
            'id': row[0], 'assessment_id': row[1],
            'model_type': row[2], 'score_column': row[3],
            'weights_json': row[4], 'created_at': row[5],
        }

    def update_analysis_config(self, assessment_id, model_type=None,
                               score_column=None, weights=None):
        """Partial update of analysis config — only updates provided fields.

        Args:
            assessment_id: int
            model_type:    str or None
            score_column:  str or None
            weights:       dict or None — if provided, replaces existing weights
        """
        config = self.get_analysis_config(assessment_id) or {}
        new_model_type   = model_type   or config.get('model_type',   'MCDA')
        new_score_column = score_column or config.get('score_column', 'MCDA_SCORE')
        new_weights = (
            weights if weights is not None
            else json.loads(config.get('weights_json') or '{}')
        )
        self.create_analysis_config(
            assessment_id, new_model_type, new_score_column, new_weights
        )

    def get_assessment(self, assessment_id):
        """Return a single assessment dict by ID, or None."""
        cursor = self.connection.cursor()
        cursor.execute(
            """SELECT id, uuid, project_id, name, description,
                      target_layer, spatial_extent, created_at
               FROM assessments
               WHERE id = ? AND is_deleted = 0""",
            (assessment_id,)
        )
        row = cursor.fetchone()
        cursor.close()
        if not row:
            return None
        return {
            'id': row[0], 'uuid': row[1], 'project_id': row[2],
            'name': row[3], 'description': row[4],
            'target_layer': row[5], 'spatial_extent': row[6],
            'created_at': row[7],
        }

    def assessment_name_exists(self, project_id, assessment_name):
        """Return True if an assessment with this name exists under this project."""
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT 1 FROM assessments WHERE project_id = ? AND name = ?",
            (project_id, assessment_name)
        )
        exists = cursor.fetchone() is not None
        cursor.close()
        return exists

    def rename_assessment(self, assessment_id, new_name):
        """Rename an assessment."""
        cursor = self.connection.cursor()
        cursor.execute(
            "UPDATE assessments SET name = ? WHERE id = ?",
            (new_name, assessment_id)
        )
        self.connection.commit()
        cursor.close()

    def delete_assessment(self, assessment_id):
        """Soft-delete a single assessment (is_deleted = 1)."""
        cursor = self.connection.cursor()
        cursor.execute(
            "UPDATE assessments SET is_deleted = 1 WHERE id = ?", (assessment_id,)
        )
        self.connection.commit()
        cursor.close()

    def purge_assessment(self, assessment_id):
        """Permanently delete an assessment record (cascades to layers, visibility)."""
        cursor = self.connection.cursor()
        # analysis_weights cascade-deletes from analyses via FK
        cursor.execute("DELETE FROM analyses WHERE assessment_id = ?", (assessment_id,))
        cursor.execute("DELETE FROM portfolios WHERE assessment_id = ?", (assessment_id,))
        cursor.execute("DELETE FROM assessment_criteria WHERE assessment_id = ?", (assessment_id,))
        cursor.execute("DELETE FROM assessments WHERE id = ?", (assessment_id,))
        self.connection.commit()
        cursor.close()

    # ------------------------------------------------------------------ #
    #  Assessment Layers
    # ------------------------------------------------------------------ #

    def add_assessment_layer(self, assessment_id, layer_name, layer_type, geometry_type=""):
        """Record a layer associated with an assessment."""
        cursor = self.connection.cursor()
        cursor.execute(
            """INSERT INTO assessment_layers (assessment_id, layer_name, layer_type, geometry_type)
               VALUES (?, ?, ?, ?)""",
            (assessment_id, layer_name, layer_type, geometry_type)
        )
        self.connection.commit()
        cursor.close()

    def get_assessment_layers(self, assessment_id, layer_type=None):
        """Return list of layer dicts. Filter by layer_type if provided."""
        cursor = self.connection.cursor()
        if layer_type:
            cursor.execute(
                """SELECT id, assessment_id, layer_name, layer_type, geometry_type
                   FROM assessment_layers
                   WHERE assessment_id = ? AND layer_type = ?""",
                (assessment_id, layer_type)
            )
        else:
            cursor.execute(
                """SELECT id, assessment_id, layer_name, layer_type, geometry_type
                   FROM assessment_layers WHERE assessment_id = ?""",
                (assessment_id,)
            )
        rows = cursor.fetchall()
        cursor.close()
        return [
            {
                'id': r[0], 'assessment_id': r[1], 'layer_name': r[2],
                'layer_type': r[3], 'geometry_type': r[4]
            }
            for r in rows
        ]

    def remove_assessment_layers(self, assessment_id):
        """Remove all layers for an assessment."""
        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM assessment_layers WHERE assessment_id = ?", (assessment_id,))
        self.connection.commit()
        cursor.close()

    # ------------------------------------------------------------------ #
    #  Layer Visibility State
    # ------------------------------------------------------------------ #

    def set_layer_visibility(self, assessment_id, layer_name, visible):
        """Persist layer visibility state (INSERT OR REPLACE)."""
        cursor = self.connection.cursor()
        cursor.execute(
            """INSERT OR REPLACE INTO layer_visibility_state
               (assessment_id, layer_name, visible) VALUES (?, ?, ?)""",
            (assessment_id, layer_name, 1 if visible else 0)
        )
        self.connection.commit()
        cursor.close()

    def get_layer_visibility(self, assessment_id):
        """Return dict {layer_name: bool} for all persisted visibility states."""
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT layer_name, visible FROM layer_visibility_state WHERE assessment_id = ?",
            (assessment_id,)
        )
        rows = cursor.fetchall()
        cursor.close()
        return {r[0]: bool(r[1]) for r in rows}

    def get_visible_layers(self, assessment_id):
        """Return list of layer names that are visible."""
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT layer_name FROM layer_visibility_state WHERE assessment_id = ? AND visible = 1",
            (assessment_id,)
        )
        rows = cursor.fetchall()
        cursor.close()
        return [r[0] for r in rows]

    # ------------------------------------------------------------------ #
    #  Provenance CRUD
    # ------------------------------------------------------------------ #

    def create_provenance(self, assessment_id, name, description=""):
        """Insert a new provenance record. Returns the new provenance id."""
        prov_uuid = str(uuid.uuid4())
        cursor = self.connection.cursor()
        cursor.execute(
            """INSERT INTO provenance (uuid, assessment_id, name, description)
               VALUES (?, ?, ?, ?)""",
            (prov_uuid, assessment_id, name, description)
        )
        self.connection.commit()
        prov_id = cursor.lastrowid
        cursor.close()
        return prov_id

    def get_provenance_for_assessment(self, assessment_id):
        """Return list of provenance dicts for an assessment, ordered by creation."""
        cursor = self.connection.cursor()
        cursor.execute(
            """SELECT id, uuid, assessment_id, name, description, created_at
               FROM provenance WHERE assessment_id = ? ORDER BY created_at""",
            (assessment_id,)
        )
        rows = cursor.fetchall()
        cursor.close()
        return [
            {
                'id': r[0], 'uuid': r[1], 'assessment_id': r[2],
                'name': r[3], 'description': r[4], 'created_at': r[5]
            }
            for r in rows
        ]

    # ------------------------------------------------------------------ #
    #  Task Details CRUD
    # ------------------------------------------------------------------ #

    def add_task(self, provenance_id, step_order, operation,
                 parent_task_id=None, input_tables=None, output_tables=None,
                 category="", engine_type="spatialite", duration_ms=0,
                 parameters="", comments="", added_to_map=True, is_scenario=False):
        """Insert a task_details record. Returns the new task id.

        Args:
            provenance_id: int
            step_order: int
            operation: str  e.g. 'union+intersect', 'CDP', 'NetWeaver'
            parent_task_id: int or None (None = top-level task)
            input_tables: list of str  (serialized to JSON)
            output_tables: list of str (serialized to JSON)
            category: str
            engine_type: str  e.g. 'spatialite', 'netweaver', 'cdp', 'lpa'
            duration_ms: int
            parameters: str (JSON or free text)
            comments: str
            added_to_map: bool
            is_scenario: bool  True for what-if / alternate-scenario runs
        """
        task_uuid = str(uuid.uuid4())
        input_json = json.dumps(input_tables) if input_tables is not None else ''
        output_json = json.dumps(output_tables) if output_tables is not None else ''

        cursor = self.connection.cursor()
        cursor.execute(
            """INSERT INTO task_details
               (uuid, provenance_id, parent_task_id, step_order, operation,
                category, input_tables, output_tables, added_to_map,
                duration_ms, parameters, comments, engine_type, is_scenario)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (task_uuid, provenance_id, parent_task_id, step_order, operation,
             category, input_json, output_json, 1 if added_to_map else 0,
             duration_ms, parameters, comments,
             engine_type, 1 if is_scenario else 0)
        )
        self.connection.commit()
        task_id = cursor.lastrowid
        cursor.close()
        return task_id

    def get_tasks_for_provenance(self, provenance_id):
        """Return all task dicts for a provenance, ordered by step_order."""
        cursor = self.connection.cursor()
        cursor.execute(
            """SELECT id, uuid, provenance_id, parent_task_id, step_order, operation,
                      category, input_tables, output_tables, db_type, added_to_map,
                      scenario, duration_ms, parameters, comments, created_at,
                      engine_type, is_scenario
               FROM task_details WHERE provenance_id = ? ORDER BY step_order""",
            (provenance_id,)
        )
        rows = cursor.fetchall()
        cursor.close()
        return [self._row_to_task(r) for r in rows]

    def get_child_tasks(self, parent_task_id):
        """Return task dicts that are direct children of the given task."""
        cursor = self.connection.cursor()
        cursor.execute(
            """SELECT id, uuid, provenance_id, parent_task_id, step_order, operation,
                      category, input_tables, output_tables, db_type, added_to_map,
                      scenario, duration_ms, parameters, comments, created_at,
                      engine_type, is_scenario
               FROM task_details WHERE parent_task_id = ? ORDER BY step_order""",
            (parent_task_id,)
        )
        rows = cursor.fetchall()
        cursor.close()
        return [self._row_to_task(r) for r in rows]

    def update_task_duration(self, task_id, duration_ms):
        """Update the duration_ms field for a task."""
        cursor = self.connection.cursor()
        cursor.execute(
            "UPDATE task_details SET duration_ms = ? WHERE id = ?",
            (duration_ms, task_id)
        )
        self.connection.commit()
        cursor.close()

    def build_task_tree(self, provenance_id):
        """Return top-level tasks with nested 'children' lists.

        Returns:
            list[dict]: Each dict is a task with a 'children' key containing
                        its child tasks recursively.
        """
        all_tasks = self.get_tasks_for_provenance(provenance_id)
        task_map = {t['id']: dict(t, children=[]) for t in all_tasks}
        roots = []
        for t in task_map.values():
            pid = t.get('parent_task_id')
            if pid and pid in task_map:
                task_map[pid]['children'].append(t)
            else:
                roots.append(t)
        return roots

    def _row_to_task(self, r):
        """Convert a task_details DB row tuple to a dict."""
        return {
            'id': r[0], 'uuid': r[1], 'provenance_id': r[2],
            'parent_task_id': r[3], 'step_order': r[4], 'operation': r[5],
            'category': r[6], 'input_tables': r[7], 'output_tables': r[8],
            'db_type': r[9], 'added_to_map': bool(r[10]),
            'scenario': r[11], 'duration_ms': r[12],
            'parameters': r[13], 'comments': r[14], 'created_at': r[15],
            'engine_type': r[16] if len(r) > 16 else 'spatialite',
            'is_scenario': bool(r[17]) if len(r) > 17 else False,
        }

    # ------------------------------------------------------------------ #
    #  Portfolios (LPA configuration)
    # ------------------------------------------------------------------ #

    def create_portfolio(self, assessment_id, source_table, name, config_json):
        """Insert a portfolio configuration (status 'pending'). Returns its id."""
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                "INSERT INTO portfolios (assessment_id, source_table, name, config_json) "
                "VALUES (?, ?, ?, ?)",
                (assessment_id, source_table, name, config_json),
            )
            self.connection.commit()
            return cursor.lastrowid
        finally:
            cursor.close()

    def portfolio_name_exists(self, assessment_id, name):
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                "SELECT 1 FROM portfolios WHERE assessment_id = ? AND name = ?",
                (assessment_id, name),
            )
            return cursor.fetchone() is not None
        finally:
            cursor.close()

    def get_portfolios_for_assessment(self, assessment_id):
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                "SELECT id, assessment_id, source_table, name, config_json, status, created_at "
                "FROM portfolios WHERE assessment_id = ? ORDER BY id",
                (assessment_id,),
            )
            return [self._row_to_portfolio(r) for r in cursor.fetchall()]
        finally:
            cursor.close()

    def get_portfolio(self, portfolio_id):
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                "SELECT id, assessment_id, source_table, name, config_json, status, created_at "
                "FROM portfolios WHERE id = ?",
                (portfolio_id,),
            )
            row = cursor.fetchone()
            return self._row_to_portfolio(row) if row else None
        finally:
            cursor.close()

    def delete_portfolio(self, portfolio_id):
        cursor = self.connection.cursor()
        try:
            cursor.execute("DELETE FROM portfolios WHERE id = ?", (portfolio_id,))
            self.connection.commit()
        finally:
            cursor.close()

    @staticmethod
    def _row_to_portfolio(r):
        try:
            config = json.loads(r[4] or '{}')
        except (ValueError, TypeError):
            config = {}
        return {
            'id': r[0], 'assessment_id': r[1], 'source_table': r[2],
            'name': r[3], 'config': config, 'status': r[5], 'created_at': r[6],
        }

    # ------------------------------------------------------------------ #
    #  App Settings  (EMDS 8 adaptation)
    # ------------------------------------------------------------------ #

    def get_app_setting(self, key, default=None):
        """Return a value from the app_settings row (column = key).

        Valid keys: plugin_version, default_project_dir, default_base_layers_group,
                    output_group_name, symbology_defaults, misc
        """
        cursor = self.connection.cursor()
        try:
            cursor.execute(f'SELECT "{key}" FROM app_settings WHERE id = 1')
            row = cursor.fetchone()
            return row[0] if row else default
        except Exception:
            return default
        finally:
            cursor.close()

    def set_app_setting(self, key, value):
        """Update a single column in the app_settings row."""
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                f'UPDATE app_settings SET "{key}" = ? WHERE id = 1', (value,)
            )
            self.connection.commit()
        finally:
            cursor.close()

    # ------------------------------------------------------------------ #
    #  Assessment Criteria CRUD (new schema)
    # ------------------------------------------------------------------ #

    def create_criterion(self, assessment_id, layer_name, criterion_name,
                         criterion_type='weighted', normalization_method='minmax',
                         weight_default=0.0):
        """Insert a new assessment criterion.  Returns the new criterion id."""
        cursor = self.connection.cursor()
        cursor.execute(
            """INSERT INTO assessment_criteria
                   (assessment_id, layer_name, criterion_name,
                    criterion_type, normalization_method, weight_default)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (assessment_id, layer_name, criterion_name,
             criterion_type, normalization_method, weight_default)
        )
        self.connection.commit()
        criterion_id = cursor.lastrowid
        cursor.close()
        return criterion_id

    def get_criteria(self, assessment_id):
        """Return list of criterion dicts for the given assessment (active only)."""
        cursor = self.connection.cursor()
        cursor.execute(
            """SELECT id, assessment_id, layer_name, criterion_name,
                      criterion_type, normalization_method, weight_default,
                      is_active, created_at
               FROM assessment_criteria
               WHERE assessment_id = ? AND is_active = 1
               ORDER BY id""",
            (assessment_id,)
        )
        rows = cursor.fetchall()
        cursor.close()
        return [
            {
                'id': r[0], 'assessment_id': r[1], 'layer_name': r[2],
                'criterion_name': r[3], 'criterion_type': r[4],
                'normalization_method': r[5], 'weight_default': r[6],
                'is_active': bool(r[7]), 'created_at': r[8],
            }
            for r in rows
        ]

    # ------------------------------------------------------------------ #
    #  Analyses CRUD (new schema — replaces analysis_configurations)
    # ------------------------------------------------------------------ #

    def create_analysis(self, assessment_id, name='Default',
                        model_type='weighted_sum', score_column='MCDA_SCORE'):
        """Insert a new analysis record.  Returns the new analysis id."""
        cursor = self.connection.cursor()
        cursor.execute(
            """INSERT INTO analyses
                   (assessment_id, name, model_type, score_column, status)
               VALUES (?, ?, ?, ?, 'valid')""",
            (assessment_id, name, model_type, score_column)
        )
        self.connection.commit()
        analysis_id = cursor.lastrowid
        cursor.close()
        return analysis_id

    def get_analyses_for_assessment(self, assessment_id):
        """Return list of analysis dicts for an assessment (newest first)."""
        cursor = self.connection.cursor()
        cursor.execute(
            """SELECT id, assessment_id, name, model_type, score_column,
                      status, weights_json, created_at
               FROM analyses WHERE assessment_id = ?
               ORDER BY created_at DESC""",
            (assessment_id,)
        )
        rows = cursor.fetchall()
        cursor.close()
        return [
            {
                'id': r[0], 'assessment_id': r[1], 'name': r[2],
                'model_type': r[3], 'score_column': r[4],
                'status': r[5], 'weights_json': r[6], 'created_at': r[7],
            }
            for r in rows
        ]

    def get_analysis(self, analysis_id):
        """Return a single analysis dict by ID, or None."""
        cursor = self.connection.cursor()
        cursor.execute(
            """SELECT id, assessment_id, name, model_type, score_column,
                      status, weights_json, created_at
               FROM analyses WHERE id = ?""",
            (analysis_id,)
        )
        row = cursor.fetchone()
        cursor.close()
        if not row:
            return None
        return {
            'id': row[0], 'assessment_id': row[1], 'name': row[2],
            'model_type': row[3], 'score_column': row[4],
            'status': row[5], 'weights_json': row[6], 'created_at': row[7],
        }

    def set_analysis_weights(self, analysis_id, weights_by_layer):
        """Replace all weights for an analysis using {layer_name: weight} dict.

        Automatically creates assessment_criteria rows where missing.
        Also updates weights_json cache on the analyses row.
        """
        cursor = self.connection.cursor()

        # Resolve assessment_id for criterion lookup
        cursor.execute("SELECT assessment_id FROM analyses WHERE id = ?", (analysis_id,))
        row = cursor.fetchone()
        if not row:
            cursor.close()
            return
        assessment_id = row[0]

        cursor.execute("DELETE FROM analysis_weights WHERE analysis_id = ?", (analysis_id,))
        total = sum(weights_by_layer.values()) or 1.0
        for layer_name, weight in weights_by_layer.items():
            cursor.execute(
                "SELECT id FROM assessment_criteria WHERE assessment_id = ? AND layer_name = ?",
                (assessment_id, layer_name)
            )
            crit_row = cursor.fetchone()
            if crit_row:
                criterion_id = crit_row[0]
                cursor.execute(
                    "UPDATE assessment_criteria SET weight_default = ? WHERE id = ?",
                    (weight, criterion_id)
                )
            else:
                cursor.execute(
                    """INSERT INTO assessment_criteria
                           (assessment_id, layer_name, criterion_name, weight_default)
                       VALUES (?, ?, ?, ?)""",
                    (assessment_id, layer_name, layer_name, weight)
                )
                criterion_id = cursor.lastrowid

            cursor.execute(
                """INSERT INTO analysis_weights
                       (analysis_id, criterion_id, weight, normalized_weight)
                   VALUES (?, ?, ?, ?)""",
                (analysis_id, criterion_id, weight, weight / total)
            )

        # Update denormalized cache
        cursor.execute(
            "UPDATE analyses SET weights_json = ? WHERE id = ?",
            (json.dumps(weights_by_layer), analysis_id)
        )
        self.connection.commit()
        cursor.close()

    def get_analysis_weights_by_layer(self, analysis_id):
        """Return {layer_name: weight} dict for an analysis."""
        cursor = self.connection.cursor()
        cursor.execute(
            """SELECT ac.layer_name, aw.weight
               FROM analysis_weights aw
               JOIN assessment_criteria ac ON aw.criterion_id = ac.id
               WHERE aw.analysis_id = ?
               ORDER BY ac.layer_name""",
            (analysis_id,)
        )
        rows = cursor.fetchall()
        cursor.close()
        return {r[0]: r[1] for r in rows}

    # ------------------------------------------------------------------ #
    #  Analysis Results CRUD (new schema)
    # ------------------------------------------------------------------ #

    def create_analysis_result(self, analysis_id, output_table,
                               output_layer_name='', feature_count=0,
                               min_score=0.0, max_score=0.0, mean_score=0.0):
        """Record metadata for one overlay output table.  Returns the new result id."""
        cursor = self.connection.cursor()
        cursor.execute(
            """INSERT INTO analysis_results
                   (analysis_id, output_table, output_layer_name,
                    feature_count, min_score, max_score, mean_score)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (analysis_id, output_table, output_layer_name,
             feature_count, min_score, max_score, mean_score)
        )
        self.connection.commit()
        result_id = cursor.lastrowid
        cursor.close()
        return result_id

    def get_analysis_results(self, analysis_id):
        """Return list of result dicts for the given analysis (newest first)."""
        cursor = self.connection.cursor()
        cursor.execute(
            """SELECT id, analysis_id, output_table, output_layer_name,
                      feature_count, min_score, max_score, mean_score, created_at
               FROM analysis_results WHERE analysis_id = ?
               ORDER BY created_at DESC""",
            (analysis_id,)
        )
        rows = cursor.fetchall()
        cursor.close()
        return [
            {
                'id': r[0], 'analysis_id': r[1], 'output_table': r[2],
                'output_layer_name': r[3], 'feature_count': r[4],
                'min_score': r[5], 'max_score': r[6], 'mean_score': r[7],
                'created_at': r[8],
            }
            for r in rows
        ]

    def snapshot_analysis_for_version(self, assessment_id, output_table, version_num):
        """Create an immutable analyses snapshot for one completed run.

        Copies weights_json from the current 'Default' row into a new
        'v{version_num}' row, then records output_table in analysis_results.
        This preserves the weights used for each specific run.

        Args:
            assessment_id: int
            output_table:  str — the versioned overlay table name (e.g. '1__urban__v2')
            version_num:   int — version number extracted from the table name

        Returns:
            int: analysis_id of the new snapshot row, or None on failure.
        """
        config = self.get_analysis_config(assessment_id)
        weights_json = config.get('weights_json', '{}') if config else '{}'
        model_type   = config.get('model_type',   'weighted_sum') if config else 'weighted_sum'
        score_column = config.get('score_column', 'MCDA_SCORE')   if config else 'MCDA_SCORE'

        cursor = self.connection.cursor()
        try:
            cursor.execute(
                """INSERT INTO analyses
                       (assessment_id, name, model_type, score_column, status, weights_json)
                   VALUES (?, ?, ?, ?, 'valid', ?)""",
                (assessment_id, f"v{version_num}", model_type, score_column, weights_json)
            )
            analysis_id = cursor.lastrowid

            cursor.execute(
                """INSERT INTO analysis_results
                       (analysis_id, output_table, output_layer_name)
                   VALUES (?, ?, ?)""",
                (analysis_id, output_table, output_table)
            )
            self.connection.commit()
            return analysis_id
        except Exception as e:
            print(f"AdminManager.snapshot_analysis_for_version warning: {e}")
            return None
        finally:
            cursor.close()

    def get_analysis_for_output_table(self, output_table):
        """Return the analyses snapshot row linked to a specific output table, or None.

        Looks up analysis_results by output_table and returns the corresponding
        analyses row (the versioned snapshot, not the mutable 'Default').

        Returns:
            dict with keys: id, assessment_id, name, model_type, score_column,
                            status, weights_json, created_at — or None.
        """
        cursor = self.connection.cursor()
        cursor.execute(
            """SELECT a.id, a.assessment_id, a.name, a.model_type, a.score_column,
                      a.status, a.weights_json, a.created_at
               FROM analyses a
               JOIN analysis_results ar ON ar.analysis_id = a.id
               WHERE ar.output_table = ?
               ORDER BY a.created_at DESC LIMIT 1""",
            (output_table,)
        )
        row = cursor.fetchone()
        cursor.close()
        if not row:
            return None
        return {
            'id': row[0], 'assessment_id': row[1], 'name': row[2],
            'model_type': row[3], 'score_column': row[4],
            'status': row[5], 'weights_json': row[6], 'created_at': row[7],
        }

    # ------------------------------------------------------------------ #
    #  Utilities
    # ------------------------------------------------------------------ #

    def get_project_db_path(self, project_id):
        """Return absolute path to the project's SpatiaLite database."""
        project = self.get_project(project_id)
        if project:
            return os.path.join(self.plugin_dir, project['db_path'])
        return None

    def get_base_layers_for_project(self, project_id):
        """Return base layer names from the project's SpatiaLite DB.

        Reads base_layers_registry table using plain sqlite3 (no extension
        needed for this read-only query).

        Returns:
            list of {'layer_name': str} dicts, or []
        """
        try:
            db_path = self.get_project_db_path(project_id)
            if not db_path or not os.path.exists(db_path):
                return []
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT layer_name FROM base_layers_registry ORDER BY layer_name"
            )
            layers = [{'layer_name': row[0]} for row in cursor.fetchall()]
            cursor.close()
            conn.close()
            return layers
        except Exception:
            return []

    def _sanitize_name(self, name):
        """Convert a name to a filesystem-safe string."""
        sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', name)
        sanitized = sanitized.lower().strip('_')
        return sanitized if sanitized else 'unnamed'

    # ------------------------------------------------------------------ #
    #  Migration from metadata.db
    # ------------------------------------------------------------------ #

    def migrate_from_metadata_db(self, old_db_path):
        """Migrate data from old metadata.db to the new admin.sqlite schema.

        Args:
            old_db_path: Path to the old metadata.db file

        Returns:
            dict: Migration stats {projects_migrated, assessments_migrated}
        """
        if not os.path.exists(old_db_path):
            return {'projects_migrated': 0, 'assessments_migrated': 0}

        stats = {'projects_migrated': 0, 'assessments_migrated': 0}

        old_conn = sqlite3.connect(old_db_path)
        old_conn.execute("PRAGMA foreign_keys = ON")

        try:
            old_cursor = old_conn.cursor()

            # Migrate projects
            old_cursor.execute("SELECT id, name, description FROM projects ORDER BY id")
            old_projects = old_cursor.fetchall()

            project_id_map = {}  # old_id → new_id

            for old_id, name, description in old_projects:
                # Skip if project already exists
                if self.get_project_by_name(name):
                    existing = self.get_project_by_name(name)
                    project_id_map[old_id] = existing['id']
                    continue

                new_id = self.create_project(name, description or "")
                project_id_map[old_id] = new_id
                stats['projects_migrated'] += 1

            # Migrate assessments
            old_cursor.execute(
                """SELECT id, project_id, name, description, target_layer,
                          assessment_layers, output_tables
                   FROM assessments ORDER BY id"""
            )
            old_assessments = old_cursor.fetchall()

            for old_id, old_project_id, name, description, target_layer, \
                    assessment_layers_json, output_tables_json in old_assessments:

                new_project_id = project_id_map.get(old_project_id)
                if new_project_id is None:
                    continue

                # Skip if assessment already exists
                if self.assessment_name_exists(new_project_id, name):
                    continue

                # Parse JSON fields from old schema
                input_layers = []
                output_tables = []
                try:
                    input_layers = json.loads(assessment_layers_json) if assessment_layers_json else []
                except (json.JSONDecodeError, TypeError):
                    pass
                try:
                    output_tables = json.loads(output_tables_json) if output_tables_json else []
                except (json.JSONDecodeError, TypeError):
                    pass

                self.create_assessment(
                    project_id=new_project_id,
                    name=name,
                    description=description or "",
                    target_layer=target_layer or "",
                    assessment_layers=input_layers,
                    output_tables=output_tables
                )
                stats['assessments_migrated'] += 1

            old_cursor.close()

        finally:
            old_conn.close()

        return stats
