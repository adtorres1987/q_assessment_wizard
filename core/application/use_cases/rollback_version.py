# -*- coding: utf-8 -*-
"""
RollbackVersion — use case to restore a previous overlay snapshot as HEAD.

Business rule:
  - The requested version_id must exist in spatial_versions.
  - No spatial recalculation — O(1): just moves the is_current pointer.

Returns:
  - dict: { 'table': str, 'version_id': int, 'layer': QgsVectorLayer }

Raises:
  - RuntimeError: project DB path not found.
  - ValueError:   version_id not found (propagated from SpatialEngine).
"""

from .commands import RollbackVersionCommand


class RollbackVersion:
    """Use case: roll back a scenario to a previous immutable version.

    Args:
        admin_manager: AdminManager instance — used to locate the SpatiaLite DB.
    """

    def __init__(self, admin_manager):
        if admin_manager is None:
            raise RuntimeError(
                "RollbackVersion requires an admin_manager instance."
            )
        self._admin_manager = admin_manager

    def execute(self, cmd: RollbackVersionCommand) -> dict:
        """Execute the rollback.

        Args:
            cmd: RollbackVersionCommand.

        Returns:
            dict: { 'table': str, 'version_id': int, 'layer': QgsVectorLayer }

        Raises:
            RuntimeError: project DB path not found.
            ValueError:   version_id not in spatial_versions.
        """
        project_db_path = self._admin_manager.get_project_db_path(cmd.project_db_id)
        if not project_db_path:
            raise RuntimeError(
                f"Project database path not found for project_db_id={cmd.project_db_id}."
            )

        from ...spatial_engine import SpatialEngine
        with SpatialEngine(project_db_path) as engine:
            result = engine.rollback_to_version(
                cmd.scenario_name,
                cmd.version_id,
                cmd.group_name,
            )

        return result  # { 'table', 'version_id', 'layer' }
