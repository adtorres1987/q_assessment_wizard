# -*- coding: utf-8 -*-
"""
SpatialRepository — infrastructure layer for SpatiaLite access.

Encapsulates the connection lifecycle, table inspection, and layer migration.
Higher layers (engine, use-cases) never import ProjectManager directly.
"""


class SpatialRepository:
    """Thin wrapper around ProjectManager that hides SpatiaLite details."""

    def __init__(self, db_path):
        self.db_path = db_path
        self._pm = None

    # ------------------------------------------------------------------ #
    #  Lifecycle
    # ------------------------------------------------------------------ #

    def open(self):
        from ....project_manager import ProjectManager
        self._pm = ProjectManager(self.db_path)
        self._pm.connect()

    def close(self):
        if self._pm:
            self._pm.disconnect()
            self._pm = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    # ------------------------------------------------------------------ #
    #  Layer migration
    # ------------------------------------------------------------------ #

    def ensure_layer(self, qgs_layer):
        table_name = self._pm.sanitize_table_name(qgs_layer.name())
        if not self._pm.table_exists(table_name):
            self._pm.migrate_layer(qgs_layer, table_name)
        return table_name

    # ------------------------------------------------------------------ #
    #  Table operations
    # ------------------------------------------------------------------ #

    def table_exists(self, name):
        return self._pm.table_exists(name)

    def drop_table(self, name):
        self._pm.drop_table(name)

    def rename_table(self, old_name, new_name):
        self._pm.rename_table(old_name, new_name)

    def sanitize_name(self, raw_name):
        return self._pm.sanitize_table_name(raw_name)

    # ------------------------------------------------------------------ #
    #  Spatial versions
    # ------------------------------------------------------------------ #

    def get_versions(self, scenario_name):
        return self._pm.get_versions(scenario_name)

    def get_version_by_id(self, version_id):
        return self._pm.get_version_by_id(version_id)

    def create_version(self, scenario_name, table_name, description='',
                       parent_version_id=None):
        return self._pm.create_version(scenario_name, table_name, description,
                                       parent_version_id)

    def set_current_version(self, scenario_name, version_id):
        self._pm.set_current_version(scenario_name, version_id)

    # ------------------------------------------------------------------ #
    #  Internal access (for OperationRunner only)
    # ------------------------------------------------------------------ #

    @property
    def project_manager(self):
        return self._pm
