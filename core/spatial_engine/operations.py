# -*- coding: utf-8 -*-
"""
OperationRunner — executes spatial SQL operations against a SpatialRepository.

Wraps SpatialAnalyzerLite so that higher layers never import it directly.
"""


class OperationRunner:
    """Executes spatial operations against a SpatialRepository.

    The runner is always bound to an open repository — it should not be
    instantiated outside of SpatialEngine.
    """

    def __init__(self, repository):
        self._repo = repository

    def cumulative_step(self, prev_table, assessment_table, output_table,
                        is_first_step=True):
        """Execute one cumulative overlay step.

        Calls _build_cumulative_step_query, executes SQL, registers geometry.

        Returns:
            int: row count written to output_table
        """
        from ...spatial_analysis_spatialite import SpatialAnalyzerLite
        analyzer = SpatialAnalyzerLite(self._repo.project_manager)
        query = analyzer._build_cumulative_step_query(
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
        """Load a SpatiaLite table as a QGIS vector layer and add it to the map.

        Args:
            table_name: str — SpatiaLite table name
            layer_name: str — display name in QGIS
            group_name: str or None — layer tree group

        Returns:
            QgsVectorLayer
        """
        from ...spatial_analysis_spatialite import SpatialAnalyzerLite
        analyzer = SpatialAnalyzerLite(self._repo.project_manager)
        return analyzer._create_qgis_layer(table_name, layer_name, group_name)
