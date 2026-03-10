# -*- coding: utf-8 -*-
"""
SpatialEngine — main facade for all spatial operations in the plugin.

Versioning model:
  - Each overlay run creates a NEW table: {base_name}__v{n}  (n = 1, 2, 3, ...)
  - The active result is tracked by `spatial_versions.is_current = 1` in the
    project's SpatiaLite database.
  - Rolling back to a previous version just moves the HEAD pointer — no
    spatial data is recalculated.

Clean Architecture position:
    UI → AssessmentExecutor → SpatialEngine → Repository → ProjectManager / SpatialAnalyzerLite
                                                ↑ Infrastructure boundary
"""

from .repository import SpatialRepository
from .operations import OperationRunner


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
            engine.rollback_to_version("project__assessment", version_id=1)

    Usage (manual lifecycle):
        engine = SpatialEngine(db_path)
        engine.open()
        try:
            ...
        finally:
            engine.close()
    """

    def __init__(self, db_path):
        """
        Args:
            db_path: str — absolute path to the project's SpatiaLite .sqlite file
        """
        self._db_path = db_path
        self._repo = None
        self._ops = None

    # ------------------------------------------------------------------ #
    #  Lifecycle
    # ------------------------------------------------------------------ #

    def open(self):
        """Open the SpatiaLite connection and initialise internal components."""
        self._repo = SpatialRepository(self._db_path)
        self._repo.open()
        self._ops = OperationRunner(self._repo)

    def close(self):
        """Close the SpatiaLite connection."""
        if self._repo:
            self._repo.close()
            self._repo = None
            self._ops = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False  # never suppress exceptions

    # ------------------------------------------------------------------ #
    #  Layer preparation
    # ------------------------------------------------------------------ #

    def prepare_layer(self, qgs_layer):
        """Ensure a QGIS layer exists in SpatiaLite (migrate if needed).

        Idempotent — safe to call multiple times for the same layer.

        Args:
            qgs_layer: QgsVectorLayer

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

    # ------------------------------------------------------------------ #
    #  Overlay analysis — cumulative versioned
    # ------------------------------------------------------------------ #

    def cumulative_overlay(self, target_table, assessment_tables, output_name,
                           group_name=None, layer_display_name=None):
        """Run cumulative overlay: apply each assessment layer iteratively.

        Each step intersects the previous result with one assessment layer,
        keeping non-intersecting features as 'no_overlap'.

        Step 1: target ∩ assessment[0]          → _step_0_tmp
        Step 2: _step_0_tmp ∩ assessment[1]     → _step_1_tmp
        ...
        Last:   _step_{n-2} ∩ assessment[n-1]   → {base}__v{m}

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
        final_table = f"{base_sanitized}__v{version_num}"

        temp_tables = []
        prev_table = target_table
        is_first_step = True

        for i, assessment_table in enumerate(assessment_tables):
            is_last = (i == len(assessment_tables) - 1)
            step_table = final_table if is_last else \
                f"{base_sanitized}__step_{i}_tmp"
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
    #  Version history
    # ------------------------------------------------------------------ #

    def get_versions(self, scenario_name):
        """Return all versions for a scenario, newest first.

        Args:
            scenario_name: str — base scenario name (without version suffix)

        Returns:
            list[dict]: each dict has id, scenario_name, table_name,
                        description, parent_version_id, is_current, created_at
        """
        base_sanitized = self._repo.sanitize_name(scenario_name)
        return self._repo.get_versions(base_sanitized)

    def get_version_by_id(self, version_id):
        """Return a single version dict by id, or None.

        Args:
            version_id: int — spatial_versions.id

        Returns:
            dict or None: version row as dict, or None if not found
        """
        return self._repo.get_version_by_id(version_id)

    def load_version(self, version_id, display_name, group_name=None):
        """Load an existing versioned table as a QGIS layer (no HEAD move).

        Useful for side-by-side comparison — loads the table without
        changing is_current.

        Args:
            version_id:   int — spatial_versions.id
            display_name: str — QGIS layer display name
            group_name:   str or None — QGIS layer tree group

        Returns:
            QgsVectorLayer — the loaded layer

        Raises:
            ValueError: if version_id not found in spatial_versions.
        """
        version = self._repo.get_version_by_id(version_id)
        if version is None:
            raise ValueError(f"Version {version_id} not found in spatial_versions.")
        return self._ops.create_qgis_layer(version['table_name'], display_name, group_name)

    def rollback_to_version(self, scenario_name, version_id, group_name=None):
        """Restore HEAD to a previous version — O(1), no spatial recalculation.

        Moves the `is_current` pointer in `spatial_versions` to `version_id`
        and loads the corresponding SpatiaLite table as a QGIS layer.

        Args:
            scenario_name: str — base scenario name (without version suffix)
            version_id:    int — id in spatial_versions to restore
            group_name:    str or None — QGIS layer tree group for the layer

        Returns:
            dict: {table, version_id, layer}

        Raises:
            ValueError: if version_id does not exist in spatial_versions.
        """
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
