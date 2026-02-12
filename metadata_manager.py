# -*- coding: utf-8 -*-
"""
Metadata Manager Module
Manages project and assessment metadata in a local SQLite database.
"""

import sqlite3
import os
import json


class MetadataManager:
    """Manages project and assessment metadata in a local SQLite database."""

    def __init__(self, plugin_dir):
        self.db_path = os.path.join(plugin_dir, "metadata.db")
        self.connection = None

    def connect(self):
        """Open SQLite connection and ensure schema exists."""
        self.connection = sqlite3.connect(self.db_path)
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._create_tables()

    def disconnect(self):
        """Close the SQLite connection."""
        if self.connection:
            self.connection.close()
            self.connection = None

    def _create_tables(self):
        """Create projects and assessments tables if they do not exist."""
        cursor = self.connection.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS assessments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                target_layer TEXT DEFAULT '',
                assessment_layers TEXT DEFAULT '[]',
                output_tables TEXT DEFAULT '[]',
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                UNIQUE(project_id, name)
            )
        """)
        self.connection.commit()
        cursor.close()

    # -- Project CRUD --

    def create_project(self, name, description=""):
        """Insert a new project. Returns the new project id."""
        cursor = self.connection.cursor()
        cursor.execute(
            "INSERT INTO projects (name, description) VALUES (?, ?)",
            (name, description)
        )
        self.connection.commit()
        project_id = cursor.lastrowid
        cursor.close()
        return project_id

    def get_all_projects(self):
        """Return list of dicts with all projects."""
        cursor = self.connection.cursor()
        cursor.execute("SELECT id, name, description, created_at FROM projects ORDER BY name")
        rows = cursor.fetchall()
        cursor.close()
        return [
            {'id': r[0], 'name': r[1], 'description': r[2], 'created_at': r[3]}
            for r in rows
        ]

    def get_project_by_name(self, name):
        """Return single project dict or None."""
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT id, name, description, created_at FROM projects WHERE name = ?",
            (name,)
        )
        row = cursor.fetchone()
        cursor.close()
        if row:
            return {'id': row[0], 'name': row[1], 'description': row[2], 'created_at': row[3]}
        return None

    def delete_project(self, project_id):
        """Delete project and cascade-delete its assessments."""
        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        self.connection.commit()
        cursor.close()

    # -- Assessment CRUD --

    def create_assessment(self, project_id, name, description="",
                          target_layer="", assessment_layers=None, output_tables=None):
        """Insert a new assessment record. Returns the new assessment id."""
        cursor = self.connection.cursor()
        cursor.execute(
            """INSERT INTO assessments
               (project_id, name, description, target_layer, assessment_layers, output_tables)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                project_id,
                name,
                description,
                target_layer,
                json.dumps(assessment_layers or []),
                json.dumps(output_tables or [])
            )
        )
        self.connection.commit()
        assessment_id = cursor.lastrowid
        cursor.close()
        return assessment_id

    def get_assessments_for_project(self, project_id):
        """Return list of assessment dicts for a given project."""
        cursor = self.connection.cursor()
        cursor.execute(
            """SELECT id, project_id, name, description, target_layer,
                      assessment_layers, output_tables, created_at
               FROM assessments WHERE project_id = ? ORDER BY name""",
            (project_id,)
        )
        rows = cursor.fetchall()
        cursor.close()
        return [
            {
                'id': r[0], 'project_id': r[1], 'name': r[2],
                'description': r[3], 'target_layer': r[4],
                'assessment_layers': json.loads(r[5]),
                'output_tables': json.loads(r[6]),
                'created_at': r[7]
            }
            for r in rows
        ]

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
        """Delete a single assessment by id."""
        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM assessments WHERE id = ?", (assessment_id,))
        self.connection.commit()
        cursor.close()
