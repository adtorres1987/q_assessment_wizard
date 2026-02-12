# -*- coding: utf-8 -*-
"""
Admin Manager Module
Manages project and assessment metadata in a central admin.sqlite database.
Replaces metadata_manager.py with normalized schema, UUIDs, and project DB paths.
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
        os.makedirs(self.projects_dir, exist_ok=True)

    def disconnect(self):
        """Close the SQLite connection."""
        if self.connection:
            self.connection.close()
            self.connection = None

    def _create_tables(self):
        """Create all admin tables if they do not exist."""
        cursor = self.connection.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL UNIQUE,
                description TEXT DEFAULT '',
                db_path TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
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
        """Return list of dicts with all projects."""
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT id, uuid, name, description, db_path, created_at FROM projects ORDER BY name"
        )
        rows = cursor.fetchall()
        cursor.close()
        return [
            {
                'id': r[0], 'uuid': r[1], 'name': r[2],
                'description': r[3], 'db_path': r[4], 'created_at': r[5]
            }
            for r in rows
        ]

    def get_project(self, project_id):
        """Return single project dict or None."""
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT id, uuid, name, description, db_path, created_at FROM projects WHERE id = ?",
            (project_id,)
        )
        row = cursor.fetchone()
        cursor.close()
        if row:
            return {
                'id': row[0], 'uuid': row[1], 'name': row[2],
                'description': row[3], 'db_path': row[4], 'created_at': row[5]
            }
        return None

    def get_project_by_name(self, name):
        """Return single project dict or None."""
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT id, uuid, name, description, db_path, created_at FROM projects WHERE name = ?",
            (name,)
        )
        row = cursor.fetchone()
        cursor.close()
        if row:
            return {
                'id': row[0], 'uuid': row[1], 'name': row[2],
                'description': row[3], 'db_path': row[4], 'created_at': row[5]
            }
        return None

    def delete_project(self, project_id):
        """Delete project, cascade-delete its assessments, and remove project DB file."""
        project = self.get_project(project_id)

        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        self.connection.commit()
        cursor.close()

        # Remove project DB file from disk
        if project and project['db_path']:
            abs_path = os.path.join(self.plugin_dir, project['db_path'])
            if os.path.exists(abs_path):
                try:
                    os.remove(abs_path)
                except OSError as e:
                    print(f"Warning: Could not delete project DB {abs_path}: {e}")

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
        """Return list of assessment dicts for a given project."""
        cursor = self.connection.cursor()
        cursor.execute(
            """SELECT id, uuid, project_id, name, description,
                      target_layer, spatial_extent, created_at
               FROM assessments WHERE project_id = ? ORDER BY name""",
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
        """Delete a single assessment by id (cascades to layers, visibility, steps)."""
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
