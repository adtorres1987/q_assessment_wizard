# -*- coding: utf-8 -*-
"""
SpatialEngine — infrastructure facade for all SpatiaLite spatial operations.

Clean Architecture position:
    core/infrastructure/spatial/  ← this file
        ↑ implements SpatialEnginePort (application/ports/)
        ↓ uses SpatialRepository → ProjectManager
"""

from .repository import SpatialRepository
from .operations import OperationRunner
from . import result_queries
from ...domain.rules.naming import versioned_name, step_table_name


class SpatialEngine:
    """Facade for SpatiaLite-based spatial analysis with immutable version history.

    Usage (context manager — preferred):
        with SpatialEngine(db_path) as engine:
            target_table = engine.prepare_layer(target_layer)
            result = engine.cumulative_overlay(
                target_table, [assessment_table],
                "project__assessment",
                group_name="Output Layers"
            )
    """

    def __init__(self, db_path):
        self._db_path = db_path
        self._repo = None
        self._ops = None

    # ------------------------------------------------------------------ #
    #  Lifecycle
    # ------------------------------------------------------------------ #

    def open(self):
        self._repo = SpatialRepository(self._db_path)
        self._repo.open()
        self._ops = OperationRunner(self._repo)

    def close(self):
        if self._repo:
            self._repo.close()
            self._repo = None
            self._ops = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    # ------------------------------------------------------------------ #
    #  Layer preparation
    # ------------------------------------------------------------------ #

    def prepare_layer(self, qgs_layer):
        """Ensure a QGIS layer exists in SpatiaLite (migrate if needed).

        Returns:
            str: sanitized SpatiaLite table name
        """
        return self._repo.ensure_layer(qgs_layer)

    def sanitize_name(self, raw_name: str) -> str:
        """Return a SpatiaLite-safe table name from any string."""
        return self._repo.sanitize_name(raw_name)

    def drop_table(self, table_name: str):
        """Drop a table from SpatiaLite."""
        self._repo.drop_table(table_name)

    def table_exists(self, table_name: str) -> bool:
        return self._repo.table_exists(table_name)

    def migrate_layers(self, layers, progress_callback=None):
        """Migrate (overwrite) QGIS layers into SpatiaLite; stats per layer."""
        return self._repo.project_manager.migrate_layers(layers, progress_callback)

    # ------------------------------------------------------------------ #
    #  Overlay analysis — cumulative versioned
    # ------------------------------------------------------------------ #

    def cumulative_overlay(self, target_table, assessment_tables, output_name,
                           group_name=None, layer_display_name=None):
        """Run cumulative overlay: apply each assessment layer iteratively.

        Each step intersects the previous result with one assessment layer,
        keeping non-intersecting features as 'no_overlap'.

        Args:
            target_table:       str — sanitized source table in SpatiaLite
            assessment_tables:  list[str] — ordered assessment tables to apply
            output_name:        str — base name (e.g. "project__assessment")
            group_name:         str or None — QGIS layer tree group
            layer_display_name: str or None — display name in QGIS

        Returns:
            dict: {table, version_id, layer}
        """
        base_sanitized = self._repo.sanitize_name(output_name)
        existing = self._repo.get_versions(base_sanitized)
        version_num = len(existing) + 1
        final_table = versioned_name(base_sanitized, version_num)

        temp_tables = []
        prev_table = target_table
        is_first_step = True

        for i, assessment_table in enumerate(assessment_tables):
            is_last = (i == len(assessment_tables) - 1)
            step_table = final_table if is_last else step_table_name(base_sanitized, i)
            if not is_last:
                temp_tables.append(step_table)

            self._ops.cumulative_step(
                prev_table, assessment_table, step_table, is_first_step
            )
            prev_table = step_table
            is_first_step = False

        for t in temp_tables:
            self._repo.drop_table(t)

        parent_id = existing[0]['id'] if existing else None
        version_id = self._repo.create_version(
            scenario_name=base_sanitized,
            table_name=final_table,
            description=f"Version {version_num} (cumulative)",
            parent_version_id=parent_id,
        )

        display_name = layer_display_name or output_name
        layer = self._ops.create_qgis_layer(final_table, display_name, group_name)

        return {'table': final_table, 'version_id': version_id, 'layer': layer}

    # ------------------------------------------------------------------ #
    #  MCDA scoring
    # ------------------------------------------------------------------ #

    def score_table(self, table_name: str, score_column: str, weight: float):
        """Add and populate a weighted area-proportional score column.

        Executes:
          ALTER TABLE ... ADD COLUMN {score_column} REAL DEFAULT 0
          UPDATE ... SET {score_column} = weight * (ST_Area(geom) / total_area)

        Idempotent: if the column already exists, only the UPDATE runs.

        Args:
            table_name:   SpatiaLite table to score.
            score_column: Name of the score column to add/update.
            weight:       Multiplier for the area fraction (0.0–1.0).
        """
        conn = self._repo.project_manager.connection
        try:
            conn.execute(
                f'ALTER TABLE "{table_name}" '
                f'ADD COLUMN "{score_column}" REAL DEFAULT 0'
            )
        except Exception:
            pass  # column already exists

        conn.execute(f"""
            UPDATE "{table_name}"
            SET "{score_column}" = {weight} * (
                COALESCE(ST_Area(geom), 0) /
                NULLIF(
                    (SELECT SUM(COALESCE(ST_Area(geom), 0))
                     FROM "{table_name}"),
                    0
                )
            )
        """)
        conn.commit()

    # ------------------------------------------------------------------ #
    #  Read-only result queries (results grid / comparison histogram)
    # ------------------------------------------------------------------ #

    def result_columns(self, table_name: str) -> list:
        """Return the non-geometry columns of a result table."""
        return result_queries.table_columns(
            self._repo.project_manager.connection, table_name
        )

    def results_summary(self, table_name: str):
        """Aggregate an overlay table per target feature.

        Returns:
            tuple: (columns: list[str], rows: list[tuple])
        """
        return result_queries.coverage_summary(
            self._repo.project_manager.connection, table_name
        )

    def results_values(self, table_name: str, field: str) -> list:
        """Return one aggregated value of *field* per target feature."""
        return result_queries.coverage_values(
            self._repo.project_manager.connection, table_name, field
        )

    # ------------------------------------------------------------------ #
    #  Version history
    # ------------------------------------------------------------------ #

    def get_versions(self, scenario_name):
        """Return all versions for a scenario, newest first."""
        base_sanitized = self._repo.sanitize_name(scenario_name)
        return self._repo.get_versions(base_sanitized)

    def get_version_by_id(self, version_id):
        """Return a single version dict by id, or None."""
        return self._repo.get_version_by_id(version_id)

    def load_version(self, version_id, display_name, group_name=None):
        """Load an existing versioned table as a QGIS layer (no HEAD move)."""
        version = self._repo.get_version_by_id(version_id)
        if version is None:
            raise ValueError(f"Version {version_id} not found in spatial_versions.")
        return self._ops.create_qgis_layer(version['table_name'], display_name, group_name)

    def rollback_to_version(self, scenario_name, version_id, group_name=None):
        """Restore HEAD to a previous version — O(1), no spatial recalculation."""
        version = self._repo.get_version_by_id(version_id)
        if version is None:
            raise ValueError(f"Version {version_id} not found in spatial_versions.")

        base_sanitized = self._repo.sanitize_name(scenario_name)
        self._repo.set_current_version(base_sanitized, version_id)

        layer = self._ops.create_qgis_layer(
            version['table_name'], scenario_name, group_name
        )

        return {
            'table': version['table_name'],
            'version_id': version_id,
            'layer': layer,
        }
