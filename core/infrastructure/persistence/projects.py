# -*- coding: utf-8 -*-
"""Projects: CRUD, per-project SpatiaLite database path and base layers."""

import sqlite3
import os
import uuid
from ...domain.rules.naming import sanitize_file_name


class ProjectsMixin:
    """Project records (admin.sqlite) and their SpatiaLite databases."""

    def create_project(self, name, description=""):
        """Insert a new project and initialize its SpatiaLite database.
        Returns the new project id.
        """
        from ..spatial.project_manager import ProjectManager

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
        return sanitize_file_name(name)
