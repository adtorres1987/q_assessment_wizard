# -*- coding: utf-8 -*-
"""
SpatialEngine — main facade for all spatial operations in the plugin.

Phase 1: encapsulates ProjectManager + SpatialAnalyzerLite behind a clean API.
Phase 3: overlay() creates immutable versioned tables. Rollback = HEAD pointer move.
Phase 4: added get_version_by_id() and load_version() for CompareVersions use case.

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
from .operations import OperationRunner, OverlayOperation


class SpatialEngine:
    """Facade for SpatiaLite-based spatial analysis with immutable version history.

    Usage (context manager — preferred):
        with SpatialEngine(db_path) as engine:
            target_table      = engine.prepare_layer(target_layer)
            assessment_table  = engine.prepare_layer(assessment_layer)

            result = engine.overlay(target_table, assessment_table,
                                    "project__assessment",
                                    group_name="Output Layers")
            # result == {
            #   'table': 'project__assessment__v1',  ← versioned table
            #   'version_id': 1,
            #   'layer': QgsVectorLayer,
            # }

            # On re-run (same scenario):
            result2 = engine.overlay(...)
            # result2['table'] == 'project__assessment__v2'

            # Rollback to v1:
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

    # ------------------------------------------------------------------ #
    #  Overlay analysis (Phase 3 — versioned)
    # ------------------------------------------------------------------ #

    def overlay(self, target_table, assessment_table, output_name,
                group_name=None):
        """Run the full overlay pipeline and create an immutable versioned table.

        Each call creates a NEW table `{output_name}__v{n}` — previous versions
        are never overwritten. The new version becomes HEAD.

        Steps:
          1. Count existing versions → determine n
          2. Compute versioned table name: {sanitized_output_name}__v{n}
          3. Run intersection → tmp_intersect (SpatiaLite only, no QGIS)
          4. Run union        → tmp_union     (SpatiaLite only, no QGIS)
          5. Rename tmp_union → final versioned table
          6. Drop tmp_intersect
          7. Record version in spatial_versions (HEAD = new version)
          8. Load final table as a QGIS layer

        Args:
            target_table:     str — sanitized source table name in SpatiaLite
            assessment_table: str — sanitized overlay table name in SpatiaLite
            output_name:      str — base name (e.g. "project__assessment")
                                    Version suffix is appended automatically.
            group_name:       str or None — QGIS layer tree group for the result

        Returns:
            dict: {
                'table':      str            — versioned SpatiaLite table name,
                'version_id': int            — id in spatial_versions,
                'layer':      QgsVectorLayer — loaded QGIS layer,
            }
        """
        base_sanitized = self._repo.sanitize_name(output_name)

        # Determine version number from existing history
        existing_versions = self._repo.get_versions(base_sanitized)
        version_num = len(existing_versions) + 1
        versioned_name = f"{base_sanitized}__v{version_num}"

        tmp_intersect = f"{versioned_name}_tmp_intersect"
        tmp_union     = f"{versioned_name}_tmp_union"
        final_table   = versioned_name  # already sanitized via base_sanitized

        # Step 1 — Intersection (intermediate only)
        self._ops.execute(
            target_table, assessment_table, tmp_intersect,
            operation=OverlayOperation.INTERSECT
        )

        # Step 2 — Union (intermediate only)
        self._ops.execute(
            target_table, assessment_table, tmp_union,
            operation=OverlayOperation.UNION
        )

        # Step 3 — Promote union as the final versioned table
        self._repo.rename_table(tmp_union, final_table)

        # Step 4 — Remove intermediate intersection
        self._repo.drop_table(tmp_intersect)

        # Step 5 — Record in spatial_versions (new HEAD)
        parent_id = existing_versions[0]['id'] if existing_versions else None
        version_id = self._repo.create_version(
            scenario_name=base_sanitized,
            table_name=final_table,
            description=f"Version {version_num}",
            parent_version_id=parent_id,
        )

        # Step 6 — Load as QGIS layer (display name = base name, no version suffix)
        layer = self._ops.create_qgis_layer(final_table, output_name, group_name)

        return {
            'table': final_table,
            'version_id': version_id,
            'layer': layer,
        }

    # ------------------------------------------------------------------ #
    #  Version history (Phase 3)
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

    def get_current_version(self, scenario_name):
        """Return the HEAD version dict for a scenario, or None.

        Args:
            scenario_name: str — base scenario name (without version suffix)
        """
        base_sanitized = self._repo.sanitize_name(scenario_name)
        return self._repo.get_current_version(base_sanitized)

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
            dict: {
                'table':      str            — restored table name,
                'version_id': int            — same as input version_id,
                'layer':      QgsVectorLayer — loaded QGIS layer,
            }

        Raises:
            ValueError: if version_id does not exist in spatial_versions.
        """
        version = self._repo.get_version_by_id(version_id)
        if version is None:
            raise ValueError(f"Version {version_id} not found in spatial_versions.")

        base_sanitized = self._repo.sanitize_name(scenario_name)

        # Move HEAD pointer (no spatial recalculation)
        self._repo.set_current_version(base_sanitized, version_id)

        # Load the historical table as a QGIS layer
        layer = self._ops.create_qgis_layer(
            version['table_name'], scenario_name, group_name
        )

        return {
            'table': version['table_name'],
            'version_id': version_id,
            'layer': layer,
        }
