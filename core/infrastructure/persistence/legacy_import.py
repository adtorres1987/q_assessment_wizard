# -*- coding: utf-8 -*-
"""One-off import from the pre-admin.sqlite ``metadata.db`` format."""

import sqlite3
import os
import json


class LegacyImportMixin:
    """Imports projects/assessments from a legacy metadata.db."""

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
