# -*- coding: utf-8 -*-
"""Provenance records and their task trees (one task per processing step)."""

import json
import uuid


class ProvenanceMixin:
    """Provenance and task details of each run."""

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
