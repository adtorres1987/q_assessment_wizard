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

from ..ports import MetadataRepositoryPort
from .commands import CompareVersionsCommand


class CompareVersions:
    """Use case: load two spatial versions for side-by-side comparison.

    No spatial recalculation. Both layers are added to a dedicated QGIS
    group so the user can visually compare them.

    Args:
        metadata_repo:        MetadataRepositoryPort implementation.
        spatial_engine_class: The SpatialEngine class (context manager factory).
    """

    def __init__(self, metadata_repo: MetadataRepositoryPort,
                 spatial_engine_class):
        if metadata_repo is None:
            raise RuntimeError(
                "CompareVersions requires a metadata_repo instance."
            )
        self._meta = metadata_repo
        self._engine_cls = spatial_engine_class

    def execute(self, cmd: CompareVersionsCommand) -> dict:
        """Execute the comparison.

        Returns:
            dict with layer_a, layer_b, version_id_a, version_id_b.

        Raises:
            RuntimeError: project DB path not found.
            ValueError:   either version not found in spatial_versions.
        """
        project_db_path = self._meta.get_project_db_path(cmd.project_db_id)
        if not project_db_path:
            raise RuntimeError(
                f"Project database path not found for "
                f"project_db_id={cmd.project_db_id}."
            )

        with self._engine_cls(project_db_path) as engine:
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
