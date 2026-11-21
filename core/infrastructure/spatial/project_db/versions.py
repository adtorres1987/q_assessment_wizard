# -*- coding: utf-8 -*-
"""Immutable spatial version chain (spatial_versions table, HEAD pointer)."""


class VersionsMixin:
    """Create / list / move HEAD of scenario versions."""

    def create_version(self, scenario_name, table_name, description='',
                       parent_version_id=None):
        """Record a new spatial version and mark it as HEAD.

        Previous HEAD for this scenario is de-activated (is_current = 0).

        Args:
            scenario_name:    Base name of the scenario (without version suffix).
            table_name:       Actual SpatiaLite table that holds the geometry.
            description:      Optional description for this version.
            parent_version_id: id of the previous HEAD, or None if first version.

        Returns:
            int: id of the newly created version.
        """
        cursor = self.connection.cursor()

        # Deactivate previous HEAD for this scenario
        cursor.execute(
            "UPDATE spatial_versions SET is_current = 0 WHERE scenario_name = ?",
            (scenario_name,)
        )

        cursor.execute(
            """INSERT INTO spatial_versions
               (scenario_name, table_name, description, parent_version_id, is_current)
               VALUES (?, ?, ?, ?, 1)""",
            (scenario_name, table_name, description, parent_version_id)
        )
        self.connection.commit()
        version_id = cursor.lastrowid
        cursor.close()
        return version_id

    def get_versions(self, scenario_name):
        """Return all versions for a scenario, ordered newest first.

        Returns:
            list[dict]: each dict has id, scenario_name, table_name, description,
                        parent_version_id, is_current, created_at.
        """
        cursor = self.connection.cursor()
        cursor.execute(
            """SELECT id, scenario_name, table_name, description,
                      parent_version_id, is_current, created_at
               FROM spatial_versions
               WHERE scenario_name = ?
               ORDER BY created_at DESC""",
            (scenario_name,)
        )
        rows = cursor.fetchall()
        cursor.close()
        return [self._row_to_version(r) for r in rows]

    def get_version_by_id(self, version_id):
        """Return a single version dict by id, or None."""
        cursor = self.connection.cursor()
        cursor.execute(
            """SELECT id, scenario_name, table_name, description,
                      parent_version_id, is_current, created_at
               FROM spatial_versions WHERE id = ?""",
            (version_id,)
        )
        row = cursor.fetchone()
        cursor.close()
        return self._row_to_version(row) if row else None

    def set_current_version(self, scenario_name, version_id):
        """Move HEAD pointer: deactivate all versions, activate the target one.

        This is the rollback operation — O(1), no spatial recalculation.

        Args:
            scenario_name: scenario whose HEAD should change.
            version_id:    id of the version to make HEAD.
        """
        cursor = self.connection.cursor()
        cursor.execute(
            "UPDATE spatial_versions SET is_current = 0 WHERE scenario_name = ?",
            (scenario_name,)
        )
        cursor.execute(
            "UPDATE spatial_versions SET is_current = 1 WHERE id = ?",
            (version_id,)
        )
        self.connection.commit()
        cursor.close()

    def _row_to_version(self, r):
        """Convert a spatial_versions DB row tuple to a dict."""
        return {
            'id': r[0], 'scenario_name': r[1], 'table_name': r[2],
            'description': r[3], 'parent_version_id': r[4],
            'is_current': bool(r[5]), 'created_at': r[6],
        }
