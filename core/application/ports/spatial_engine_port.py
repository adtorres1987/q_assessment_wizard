# -*- coding: utf-8 -*-
"""
SpatialEnginePort — abstraction over SpatialEngine.

Use cases receive a factory callable that returns a context manager implementing
this Protocol, so they never import SpatialEngine directly.

Usage in use cases:
    with self._engine_factory(db_path) as engine:
        engine.prepare_layer(...)
        engine.cumulative_overlay(...)
"""

from typing import Protocol, runtime_checkable, Optional, List


@runtime_checkable
class SpatialEnginePort(Protocol):
    """Port: spatial analysis operations over a SpatiaLite database."""

    def prepare_layer(self, qgs_layer) -> str:
        """Migrate a QGIS layer into SpatiaLite. Returns sanitized table name."""
        ...

    def cumulative_overlay(self, target_table: str, assessment_tables: List[str],
                           output_name: str,
                           group_name: Optional[str] = None,
                           layer_display_name: Optional[str] = None) -> dict:
        """Run cumulative overlay (each assessment layer applied iteratively).

        Returns: {'table': str, 'version_id': int, 'layer': QgsVectorLayer}
        """
        ...

    def get_versions(self, scenario_name: str) -> List[dict]: ...

    def get_version_by_id(self, version_id: int) -> Optional[dict]: ...

    def load_version(self, version_id: int, display_name: str,
                     group_name: Optional[str] = None): ...

    def rollback_to_version(self, scenario_name: str, version_id: int,
                            group_name: Optional[str] = None) -> dict: ...

    def score_table(self, table_name: str, score_column: str,
                    weight: float) -> None:
        """Add/update a weighted area-proportional score column in a table."""
        ...

    def drop_table(self, table_name: str): ...

    # Read-only result queries (results grid / comparison histogram).
    # Raise LookupError if the table is missing, ValueError if it is not an
    # overlay output.

    def result_columns(self, table_name: str) -> List[str]: ...

    def results_summary(self, table_name: str) -> tuple:
        """Per-target-feature aggregates: (columns, rows)."""
        ...

    def results_values(self, table_name: str, field: str) -> List[float]: ...

    def sanitize_name(self, raw_name: str) -> str: ...
