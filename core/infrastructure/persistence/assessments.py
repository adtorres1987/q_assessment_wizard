# -*- coding: utf-8 -*-
"""Assessments: CRUD, their input/output layers and persisted layer visibility."""

import uuid


class AssessmentsMixin:
    """Assessment records, assessment layers and layer visibility."""

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

    def delete_assessment(self, assessment_id):
        """Soft-delete a single assessment (is_deleted = 1)."""
        cursor = self.connection.cursor()
        cursor.execute(
            "UPDATE assessments SET is_deleted = 1 WHERE id = ?", (assessment_id,)
        )
        self.connection.commit()
        cursor.close()

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
