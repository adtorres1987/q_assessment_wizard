# -*- coding: utf-8 -*-
"""
SpatialRepository — infrastructure layer for SpatiaLite access.

Encapsulates the connection lifecycle, table inspection, and layer migration.
Higher layers (engine, use-cases) never import ProjectManager directly.
"""


class SpatialRepository:
    """Thin wrapper around ProjectManager that hides SpatiaLite details.

    Usage (as context manager):
        with SpatialRepository(db_path) as repo:
            table = repo.ensure_layer(qgs_layer)
            repo.rename_table(old, new)
    """

    def __init__(self, db_path):
        self.db_path = db_path
        self._pm = None

    # ------------------------------------------------------------------ #
    #  Lifecycle
    # ------------------------------------------------------------------ #

    def open(self):
        """Open the SpatiaLite connection."""
        from ...project_manager import ProjectManager
        self._pm = ProjectManager(self.db_path)
        self._pm.connect()

    def close(self):
        """Close the SpatiaLite connection."""
        if self._pm:
            self._pm.disconnect()
            self._pm = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False  # never suppress exceptions

    # ------------------------------------------------------------------ #
    #  Layer migration
    # ------------------------------------------------------------------ #

    def ensure_layer(self, qgs_layer):
        """Migrate a QGIS layer to SpatiaLite if not already present.

        Args:
            qgs_layer: QgsVectorLayer

        Returns:
            str: sanitized table name in SpatiaLite
        """
        table_name = self._pm.sanitize_table_name(qgs_layer.name())
        if not self._pm.table_exists(table_name):
            self._pm.migrate_layer(qgs_layer, table_name)
        return table_name

    # ------------------------------------------------------------------ #
    #  Table operations
    # ------------------------------------------------------------------ #

    def table_exists(self, name):
        """Return True if a table with this name exists in SpatiaLite."""
        return self._pm.table_exists(name)

    def drop_table(self, name):
        """Drop a table from SpatiaLite (including geometry metadata)."""
        self._pm.drop_table(name)

    def rename_table(self, old_name, new_name):
        """Rename a SpatiaLite table, re-registering geometry and spatial index."""
        self._pm.rename_table(old_name, new_name)

    def sanitize_name(self, raw_name):
        """Return a SpatiaLite-safe table name from any string."""
        return self._pm.sanitize_table_name(raw_name)

    # ------------------------------------------------------------------ #
    #  Spatial Versions  (Phase 3 — delegates to ProjectManager)
    # ------------------------------------------------------------------ #

    def get_versions(self, scenario_name):
        """Return all versions for a scenario, newest first (list of dicts)."""
        return self._pm.get_versions(scenario_name)

    def get_current_version(self, scenario_name):
        """Return the HEAD version dict for a scenario, or None."""
        return self._pm.get_current_version(scenario_name)

    def get_version_by_id(self, version_id):
        """Return a single version dict by id, or None."""
        return self._pm.get_version_by_id(version_id)

    def create_version(self, scenario_name, table_name, description='',
                       parent_version_id=None):
        """Record a new version as HEAD. Returns the new version id."""
        return self._pm.create_version(scenario_name, table_name, description,
                                       parent_version_id)

    def set_current_version(self, scenario_name, version_id):
        """Move HEAD pointer to an existing version (rollback — O(1))."""
        self._pm.set_current_version(scenario_name, version_id)

    # ------------------------------------------------------------------ #
    #  Internal access (for OperationRunner only)
    # ------------------------------------------------------------------ #

    @property
    def project_manager(self):
        """Expose ProjectManager to OperationRunner (same layer — infrastructure)."""
        return self._pm
