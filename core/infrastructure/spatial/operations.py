# -*- coding: utf-8 -*-
"""
OperationRunner — executes spatial SQL operations against a SpatialRepository.
"""

from qgis.core import QgsVectorLayer, QgsProject


class OperationRunner:
    """Executes spatial operations against a SpatialRepository."""

    def __init__(self, repository):
        self._repo = repository

    def cumulative_step(self, prev_table, assessment_table, output_table,
                        is_first_step=True):
        """Execute one cumulative overlay step.

        Returns:
            int: row count written to output_table
        """
        query = self._build_cumulative_step_query(
            prev_table, assessment_table, output_table, is_first_step
        )
        conn = self._repo.project_manager.connection

        if self._repo.table_exists(output_table):
            self._repo.drop_table(output_table)

        conn.execute(query)
        conn.commit()

        cursor = conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM {output_table}")
        count = cursor.fetchone()[0]

        cursor.execute(
            "SELECT srid FROM geometry_columns "
            "WHERE f_table_name=? AND f_geometry_column='geom'",
            (prev_table,)
        )
        row = cursor.fetchone()
        srid = row[0] if row else 4326
        cursor.close()

        registered = False
        for try_type in ['MULTIPOLYGON', 'POLYGON', 'GEOMETRY']:
            try:
                conn.execute(
                    f"SELECT RecoverGeometryColumn("
                    f"'{output_table}', 'geom', {srid}, '{try_type}', 'XY')"
                )
                conn.commit()
                registered = True
                break
            except Exception:
                continue
        if not registered:
            raise RuntimeError(
                f"Could not register geometry for cumulative step '{output_table}'"
            )
        return count

    def create_qgis_layer(self, table_name, layer_name, group_name=None):
        """Load a SpatiaLite table as a QGIS vector layer and add it to the map."""
        if not layer_name:
            layer_name = table_name

        uri = (f"dbname='{self._repo.project_manager.db_path}' "
               f"table='{table_name}' (geom)")
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

    def _resolve_group(self, group_path):
        root = QgsProject.instance().layerTreeRoot()
        parent = root
        for part in group_path.split('/'):
            parent = self._find_or_create_group(parent, part)
        return parent

    @staticmethod
    def _find_or_create_group(parent, name):
        group = parent.findGroup(name)
        if not group:
            group = parent.addGroup(name)
        return group

    @staticmethod
    def _build_cumulative_step_query(prev_table, assessment_table, output_table,
                                      is_first_step=True):
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
