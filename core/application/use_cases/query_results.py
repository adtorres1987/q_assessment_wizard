# -*- coding: utf-8 -*-
"""
Read-only use cases over overlay result tables.

  - GetResultsGrid      — per-target-feature summary for the results grid.
  - GetResultColumns    — column names of a result table (portfolio mapping).
  - GetComparisonSeries — one value list per result, for the paired histogram.

Raises:
  - RuntimeError: project DB path not found.
  - LookupError:  a table is not stored in the project SpatiaLite DB
                  (e.g. a simple/memory assessment).
  - ValueError:   a table is not an overlay output, or bad input.
"""

from ..ports import MetadataRepositoryPort
from .commands import GetResultsGridCommand, GetComparisonSeriesCommand


class _ResultQuery:

    def __init__(self, metadata_repo: MetadataRepositoryPort,
                 spatial_engine_class):
        if metadata_repo is None:
            raise RuntimeError(
                f"{type(self).__name__} requires a metadata_repo instance."
            )
        self._meta = metadata_repo
        self._engine_cls = spatial_engine_class

    def _db_path(self, project_db_id):
        path = self._meta.get_project_db_path(project_db_id)
        if not path:
            raise RuntimeError(
                f"Project database path not found for project_db_id={project_db_id}."
            )
        return path


class GetResultsGrid(_ResultQuery):
    """Use case: aggregate an overlay table for the results grid."""

    def execute(self, cmd: GetResultsGridCommand) -> dict:
        """Returns: {'table': str, 'columns': list[str], 'rows': list[tuple]}"""
        with self._engine_cls(self._db_path(cmd.project_db_id)) as engine:
            columns, rows = engine.results_summary(cmd.table_name)
        return {'table': cmd.table_name, 'columns': columns, 'rows': rows}


class GetResultColumns(_ResultQuery):
    """Use case: list the (non-geometry) columns of a result table."""

    def execute(self, cmd: GetResultsGridCommand) -> list:
        with self._engine_cls(self._db_path(cmd.project_db_id)) as engine:
            return engine.result_columns(cmd.table_name)


class GetComparisonSeries(_ResultQuery):
    """Use case: load one aggregated series per result for comparison."""

    MIN_SERIES = 2

    def execute(self, cmd: GetComparisonSeriesCommand) -> dict:
        """Returns: {label: list[float]} in the order of cmd.tables.

        Raises:
            ValueError: fewer than 2 tables, or a table has no data.
        """
        if len(cmd.tables) < self.MIN_SERIES:
            raise ValueError("At least 2 results are needed to compare.")

        series = {}
        with self._engine_cls(self._db_path(cmd.project_db_id)) as engine:
            for label, table in cmd.tables.items():
                values = engine.results_values(table, cmd.field_name)
                if not values:
                    raise ValueError(f"No data found in '{label}'.")
                series[label] = values
        return series
