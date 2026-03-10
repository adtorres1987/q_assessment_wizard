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

from ..ports import MetadataRepositoryPort
from .commands import RollbackVersionCommand


class RollbackVersion:
    """Use case: roll back a scenario to a previous immutable version.

    Args:
        metadata_repo:        MetadataRepositoryPort implementation.
        spatial_engine_class: The SpatialEngine class (context manager factory).
    """

    def __init__(self, metadata_repo: MetadataRepositoryPort,
                 spatial_engine_class):
        if metadata_repo is None:
            raise RuntimeError(
                "RollbackVersion requires a metadata_repo instance."
            )
        self._meta = metadata_repo
        self._engine_cls = spatial_engine_class

    def execute(self, cmd: RollbackVersionCommand) -> dict:
        """Execute the rollback.

        Returns:
            dict: { 'table': str, 'version_id': int, 'layer': QgsVectorLayer }

        Raises:
            RuntimeError: project DB path not found.
            ValueError:   version_id not in spatial_versions.
        """
        project_db_path = self._meta.get_project_db_path(cmd.project_db_id)
        if not project_db_path:
            raise RuntimeError(
                f"Project database path not found for "
                f"project_db_id={cmd.project_db_id}."
            )

        with self._engine_cls(project_db_path) as engine:
            result = engine.rollback_to_version(
                cmd.scenario_name,
                cmd.version_id,
                cmd.group_name,
            )

        return result  # { 'table', 'version_id', 'layer' }
