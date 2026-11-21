# -*- coding: utf-8 -*-
"""
Layer migration use cases — copy QGIS layers into the project SpatiaLite DB.

  - FindExistingLayers — which of the given layers already have a table
                         (the UI asks whether to overwrite them).
  - MigrateLayers      — migrate (overwrite) the given layers.

Raises:
  - RuntimeError:       project DB path not found.
  - OperationCancelled: raised by the progress callback, propagated as is.
"""

from ..ports import MetadataRepositoryPort
from .commands import MigrateLayersCommand


class _MigrationUseCase:

    def __init__(self, metadata_repo: MetadataRepositoryPort, spatial_engine_class):
        if metadata_repo is None:
            raise RuntimeError(f"{type(self).__name__} requires a metadata_repo instance.")
        self._meta = metadata_repo
        self._engine_cls = spatial_engine_class

    def _db_path(self, project_db_id):
        path = self._meta.get_project_db_path(project_db_id)
        if not path:
            raise RuntimeError(
                f"Project database path not found for project_db_id={project_db_id}."
            )
        return path


class FindExistingLayers(_MigrationUseCase):
    """Use case: names of the layers in cmd.layers already stored in SpatiaLite."""

    def execute(self, cmd: MigrateLayersCommand) -> list:
        with self._engine_cls(self._db_path(cmd.project_db_id)) as engine:
            return [name for name in cmd.layers
                    if engine.table_exists(engine.sanitize_name(name))]


class MigrateLayers(_MigrationUseCase):
    """Use case: migrate (and overwrite) every layer in cmd.layers."""

    def execute(self, cmd: MigrateLayersCommand) -> dict:
        """Returns:
            dict: {'migrated': [table names], 'failed': ['table: error', ...],
                   'inserted': int, 'errors': int}
        """
        if not cmd.layers:
            return {'migrated': [], 'failed': [], 'inserted': 0, 'errors': 0}

        with self._engine_cls(self._db_path(cmd.project_db_id)) as engine:
            all_stats = engine.migrate_layers(cmd.layers, cmd.progress_callback)

        summary = {'migrated': [], 'failed': [], 'inserted': 0, 'errors': 0}
        for stats in all_stats:
            if 'error' in stats:
                summary['failed'].append(f"{stats['table_name']}: {stats['error']}")
            else:
                summary['migrated'].append(stats.get('table_name', ''))
                summary['inserted'] += stats.get('inserted', 0)
                summary['errors'] += stats.get('errors', 0)
        return summary
