# -*- coding: utf-8 -*-
"""
Admin Manager Module
Manages project and assessment metadata in a central admin.sqlite database.
Replaces metadata_manager.py with normalized schema, UUIDs, and project DB paths.

Schema v2: adapted from EMDS 8 (emdsInfo.Sqlite) — adds engine_type, is_scenario,
soft-delete (is_deleted), base_layer_names, spatial_references, and app_settings.
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
            CREATE TABLE IF NOT EXISTS workflow_steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assessment_id INTEGER NOT NULL,
                step_order INTEGER NOT NULL,
                operation TEXT NOT NULL,
                parameters TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
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

        # Spatial references — overlay layer info per assessment (EMDS 8 adaptation)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS spatial_references (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid TEXT UNIQUE NOT NULL,
                assessment_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                overlay_layer_name TEXT DEFAULT '',
                source_tables TEXT DEFAULT '',
                source_db_type TEXT DEFAULT 'spatialite',
                source_db_path TEXT DEFAULT '',
                srid INTEGER DEFAULT 4326,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE CASCADE
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

    def delete_assessment(self, assessment_id):
        """Soft-delete a single assessment (is_deleted = 1)."""
        cursor = self.connection.cursor()
        cursor.execute(
            "UPDATE assessments SET is_deleted = 1 WHERE id = ?", (assessment_id,)
        )
        self.connection.commit()
        cursor.close()

    def purge_assessment(self, assessment_id):
        """Permanently delete an assessment record (cascades to layers, visibility, steps)."""
        cursor = self.connection.cursor()
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
    #  Workflow Steps
    # ------------------------------------------------------------------ #

    def add_workflow_step(self, assessment_id, step_order, operation, parameters=""):
        """Record a workflow step for an assessment."""
        cursor = self.connection.cursor()
        cursor.execute(
            """INSERT INTO workflow_steps (assessment_id, step_order, operation, parameters)
               VALUES (?, ?, ?, ?)""",
            (assessment_id, step_order, operation, parameters)
        )
        self.connection.commit()
        cursor.close()

    def get_workflow_steps(self, assessment_id):
        """Return list of workflow step dicts ordered by step_order."""
        cursor = self.connection.cursor()
        cursor.execute(
            """SELECT id, assessment_id, step_order, operation, parameters, created_at
               FROM workflow_steps WHERE assessment_id = ? ORDER BY step_order""",
            (assessment_id,)
        )
        rows = cursor.fetchall()
        cursor.close()
        return [
            {
                'id': r[0], 'assessment_id': r[1], 'step_order': r[2],
                'operation': r[3], 'parameters': r[4], 'created_at': r[5]
            }
            for r in rows
        ]

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

    def delete_provenance(self, provenance_id):
        """Delete a provenance record (cascades to task_details)."""
        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM provenance WHERE id = ?", (provenance_id,))
        self.connection.commit()
        cursor.close()

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
    #  Spatial References CRUD  (EMDS 8 adaptation)
    # ------------------------------------------------------------------ #

    def create_spatial_reference(self, assessment_id, name,
                                  overlay_layer_name="", source_tables=None,
                                  source_db_type="spatialite", source_db_path="",
                                  srid=4326):
        """Insert a spatial_references record. Returns the new id.

        Args:
            assessment_id: int
            name: str — e.g. "{project}__Overlay"
            overlay_layer_name: str — SpatiaLite table used as overlay
            source_tables: list[str] — original input table names
            source_db_type: str — 'spatialite', 'postgresql', 'geodatabase'
            source_db_path: str — path or connection string
            srid: int — EPSG code
        """
        sr_uuid = str(uuid.uuid4())
        source_json = json.dumps(source_tables) if source_tables is not None else ''

        cursor = self.connection.cursor()
        cursor.execute(
            """INSERT INTO spatial_references
               (uuid, assessment_id, name, overlay_layer_name,
                source_tables, source_db_type, source_db_path, srid)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (sr_uuid, assessment_id, name, overlay_layer_name,
             source_json, source_db_type, source_db_path, srid)
        )
        self.connection.commit()
        sr_id = cursor.lastrowid
        cursor.close()
        return sr_id

    def get_spatial_references_for_assessment(self, assessment_id):
        """Return list of spatial_reference dicts for an assessment."""
        cursor = self.connection.cursor()
        cursor.execute(
            """SELECT id, uuid, assessment_id, name, overlay_layer_name,
                      source_tables, source_db_type, source_db_path, srid, created_at
               FROM spatial_references WHERE assessment_id = ? ORDER BY created_at""",
            (assessment_id,)
        )
        rows = cursor.fetchall()
        cursor.close()
        return [
            {
                'id': r[0], 'uuid': r[1], 'assessment_id': r[2],
                'name': r[3], 'overlay_layer_name': r[4],
                'source_tables': r[5], 'source_db_type': r[6],
                'source_db_path': r[7], 'srid': r[8], 'created_at': r[9]
            }
            for r in rows
        ]

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
    #  Utilities
    # ------------------------------------------------------------------ #

    def get_project_db_path(self, project_id):
        """Return absolute path to the project's SpatiaLite database."""
        project = self.get_project(project_id)
        if project:
            return os.path.join(self.plugin_dir, project['db_path'])
        return None

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
