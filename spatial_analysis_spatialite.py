# -*- coding: utf-8 -*-
"""
SpatialAnalyzerLite — low-level SpatiaLite SQL builder and QGIS layer factory.

Provides:
  - _build_cumulative_step_query(): SQL for iterative cumulative overlay steps
  - _create_qgis_layer():           load a SpatiaLite table as a QgsVectorLayer
"""

from qgis.core import QgsVectorLayer, QgsProject


class SpatialAnalyzerLite:
    """Low-level SpatiaLite operations called exclusively by OperationRunner."""

    def __init__(self, project_manager):
        self.pm = project_manager

    # ------------------------------------------------------------------ #
    #  Cumulative overlay query builder
    # ------------------------------------------------------------------ #

    def _build_cumulative_step_query(self, prev_table, assessment_table,
                                      output_table, is_first_step=True):
        """Build one cumulative intersection step.

        - Intersecting portion: geometry refined via Intersection()
        - Non-intersecting portion: kept as-is with split_type='no_overlap'

        Args:
            prev_table:       Source table (raw target on step 1, prev result on 2+)
            assessment_table: Assessment layer to intersect with
            output_table:     Name for the output table
            is_first_step:    True when prev_table is the raw target (has `id` column).
                              False when prev_table is a prior step result (has `input_id`).
        """
        if is_first_step:
            intersect_id = "a.id AS input_id"
            noop_id      = "a.id AS input_id, NULL AS identity_id"
        else:
            intersect_id = "a.input_id"
            noop_id      = "a.input_id, a.identity_id"

        return f"""
        CREATE TABLE {output_table} AS
        SELECT
            {intersect_id},
            b.rowid AS identity_id,
            CastToMultiPolygon(Intersection(a.geom, b.geom)) AS geom,
            'intersect' AS split_type,
            Area(Intersection(a.geom, b.geom))      AS shape_area,
            Perimeter(Intersection(a.geom, b.geom)) AS shape_length
        FROM {prev_table} a
        JOIN {assessment_table} b ON Intersects(a.geom, b.geom)
        WHERE IsValid(a.geom)
          AND IsValid(b.geom)
          AND GeometryType(Intersection(a.geom, b.geom)) IN ('POLYGON','MULTIPOLYGON')
          AND Area(Intersection(a.geom, b.geom)) > 0

        UNION ALL

        SELECT
            {noop_id},
            a.geom,
            'no_overlap' AS split_type,
            Area(a.geom)      AS shape_area,
            Perimeter(a.geom) AS shape_length
        FROM {prev_table} a
        WHERE NOT EXISTS (
            SELECT 1 FROM {assessment_table} b
            WHERE Intersects(a.geom, b.geom) AND IsValid(b.geom)
        )
        """

    # ------------------------------------------------------------------ #
    #  QGIS layer factory
    # ------------------------------------------------------------------ #

    def _create_qgis_layer(self, table_name, layer_name=None, group_name=None):
        """Create a QGIS vector layer from a SpatiaLite table.

        Args:
            table_name: Name of the SpatiaLite table.
            layer_name: Display name for the layer (defaults to table_name).
            group_name: Optional group path. Supports nested paths via '/'
                        e.g. "01_SchoolFocus" or "01_SchoolFocus/v2_result".

        Returns:
            QgsVectorLayer: The created and registered layer.
        """
        if not layer_name:
            layer_name = table_name

        uri = f"dbname='{self.pm.db_path}' table='{table_name}' (geom)"
        layer = QgsVectorLayer(uri, layer_name, "spatialite")

        if not layer.isValid():
            raise Exception(f"Failed to create QGIS layer from table '{table_name}'")

        if group_name:
            group = self._resolve_group(group_name)
            QgsProject.instance().addMapLayer(layer, False)
            group.addLayer(layer)
        else:
            QgsProject.instance().addMapLayer(layer)

        return layer

    def _find_or_create_group(self, parent, name):
        """Find or create a single-level layer tree group under parent."""
        group = parent.findGroup(name)
        if not group:
            group = parent.addGroup(name)
        return group

    def _resolve_group(self, group_path):
        """Resolve a '/'-separated group path from the layer tree root.

        Creates any missing groups along the path.
        """
        root = QgsProject.instance().layerTreeRoot()
        parent = root
        for part in group_path.split('/'):
            parent = self._find_or_create_group(parent, part)
        return parent
