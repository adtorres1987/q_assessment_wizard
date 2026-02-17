# -*- coding: utf-8 -*-
"""
CompareVersions — use case to load two version snapshots for visual comparison.

Business rules:
  - Both version_id_a and version_id_b must exist in spatial_versions.
  - Layers are loaded read-only into a dedicated QGIS group.
  - HEAD pointer is NOT moved — this is a read-only operation.

Returns:
  - dict: {
        'layer_a':      QgsVectorLayer,  # snapshot of version_id_a
        'layer_b':      QgsVectorLayer,  # snapshot of version_id_b
        'version_id_a': int,
        'version_id_b': int,
    }

Raises:
  - RuntimeError: project DB path not found.
  - ValueError:   version_id_a or version_id_b not found.
"""

from .commands import CompareVersionsCommand


class CompareVersions:
    """Use case: load two spatial versions for side-by-side comparison.

    No spatial recalculation. Both layers are added to a dedicated QGIS
    group so the user can visually compare them.

    Args:
        admin_manager: AdminManager instance — used to locate the SpatiaLite DB.
    """

    def __init__(self, admin_manager):
        if admin_manager is None:
            raise RuntimeError(
                "CompareVersions requires an admin_manager instance."
            )
        self._admin_manager = admin_manager

    def execute(self, cmd: CompareVersionsCommand) -> dict:
        """Execute the comparison.

        Args:
            cmd: CompareVersionsCommand.

        Returns:
            dict with layer_a, layer_b, version_id_a, version_id_b.

        Raises:
            RuntimeError: project DB path not found.
            ValueError:   either version not found in spatial_versions.
        """
        project_db_path = self._admin_manager.get_project_db_path(cmd.project_db_id)
        if not project_db_path:
            raise RuntimeError(
                f"Project database path not found for project_db_id={cmd.project_db_id}."
            )

        from ...spatial_engine import SpatialEngine
        with SpatialEngine(project_db_path) as engine:
            layer_a = engine.load_version(
                cmd.version_id_a,
                display_name=f"{cmd.scenario_name} [v{cmd.version_id_a}]",
                group_name=cmd.group_name,
            )
            layer_b = engine.load_version(
                cmd.version_id_b,
                display_name=f"{cmd.scenario_name} [v{cmd.version_id_b}]",
                group_name=cmd.group_name,
            )

        return {
            'layer_a':      layer_a,
            'layer_b':      layer_b,
            'version_id_a': cmd.version_id_a,
            'version_id_b': cmd.version_id_b,
        }
