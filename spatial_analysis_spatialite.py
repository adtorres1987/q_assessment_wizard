# -*- coding: utf-8 -*-
"""
Spatial Analysis Module (SpatiaLite)
Handles spatial operations between target and assessment layers
using SpatiaLite instead of PostGIS.
Replaces spatial_analysis.py.
"""

from enum import Enum
from qgis.core import QgsVectorLayer, QgsProject


class OperationType(Enum):
    """Types of spatial operations"""
    INTERSECT = "intersect"
    UNION = "union"
    BOTH = "both"


class SpatialAnalyzerLite:
    """
    Performs spatial analysis operations on SpatiaLite tables
    and creates resulting layers in QGIS.
    """

    def __init__(self, project_manager):
        """
        Initialize spatial analyzer with project manager.

        Args:
            project_manager: ProjectManager instance with active connection
        """
        self.pm = project_manager

    def analyze_and_create_layer(self, target_table, assessment_table, output_table,
                                 layer_name=None, operation_type=OperationType.BOTH):
        """
        Perform spatial analysis between target and assessment layers and create QGIS layer.

        Args:
            target_table: Name of target layer table in SpatiaLite
            assessment_table: Name of assessment layer table in SpatiaLite
            output_table: Name of output table to create
            layer_name: Name for the new QGIS layer (defaults to output_table)
            operation_type: Type of operation (INTERSECT, UNION, or BOTH)

        Returns:
            dict: Results including total_count, output_table, layer, success
        """
        if not self.pm.connection:
            raise Exception("Database not connected. Call project_manager.connect() first.")

        if not self.pm.table_exists(target_table):
            raise Exception(f"Target table '{target_table}' does not exist")

        if not self.pm.table_exists(assessment_table):
            raise Exception(f"Assessment table '{assessment_table}' does not exist")

        # Validate geometry compatibility
        validation = self.validate_geometry_compatibility(target_table, assessment_table)
        if not validation['compatible']:
            raise Exception(f"Geometry incompatibility: {validation['message']}")

        # Drop output table if it exists
        if self.pm.table_exists(output_table):
            self.pm.drop_table(output_table)

        # Get SRID from target table for geometry registration
        target_srid = self._get_srid(target_table)

        # Build and execute the spatial analysis query
        if operation_type == OperationType.INTERSECT:
            query = self._build_intersect_query(target_table, assessment_table, output_table)
        elif operation_type == OperationType.UNION:
            query = self._build_union_query(target_table, assessment_table, output_table)
        else:
            query = self._build_both_query(target_table, assessment_table, output_table)

        cursor = self.pm.connection.cursor()

        try:
            cursor.execute(query)
            self.pm.connection.commit()

            # Get total count
            cursor.execute(f"SELECT COUNT(*) FROM {output_table}")
            total_count = cursor.fetchone()[0]

            # Detect actual geometry type and dimension from output data
            geom_type, dimension = self._detect_geometry_info(output_table)

            # Register geometry column in SpatiaLite metadata
            registered = False
            for try_type in [geom_type, 'MULTIPOLYGON', 'POLYGON', 'GEOMETRY']:
                try:
                    cursor.execute(
                        f"SELECT RecoverGeometryColumn('{output_table}', 'geom', "
                        f"{target_srid}, '{try_type}', '{dimension}')"
                    )
                    result = cursor.fetchone()
                    self.pm.connection.commit()
                    if result and result[0] == 1:
                        registered = True
                        print(f"Geometry registered for {output_table}: type={try_type}, dim={dimension}, srid={target_srid}")
                        break
                except Exception as e:
                    print(f"RecoverGeometryColumn attempt with {try_type}: {e}")
                    continue

            if not registered:
                raise Exception(
                    f"Could not register geometry column for '{output_table}'. "
                    f"Detected type={geom_type}, dim={dimension}, srid={target_srid}"
                )

            # Create spatial index
            try:
                cursor.execute(
                    f"SELECT CreateSpatialIndex('{output_table}', 'geom')"
                )
                self.pm.connection.commit()
            except Exception as e:
                print(f"Note: Could not create spatial index for {output_table}: {e}")

            cursor.close()

            # Create QGIS layer from SpatiaLite table
            layer = self._create_qgis_layer(output_table, layer_name)

            return {
                'total_count': total_count,
                'output_table': output_table,
                'layer': layer,
                'layer_name': layer.name() if layer else None,
                'success': layer is not None
            }

        except Exception as e:
            cursor.close()
            raise Exception(f"Spatial analysis failed: {str(e)}")

    def _create_qgis_layer(self, table_name, layer_name=None):
        """
        Create a QGIS vector layer from a SpatiaLite table.

        Args:
            table_name: Name of the SpatiaLite table
            layer_name: Display name for the layer (defaults to table_name)

        Returns:
            QgsVectorLayer: The created layer
        """
        if not layer_name:
            layer_name = table_name

        uri = f"dbname='{self.pm.db_path}' table='{table_name}' (geom)"
        layer = QgsVectorLayer(uri, layer_name, "spatialite")

        if not layer.isValid():
            raise Exception(f"Failed to create QGIS layer from table '{table_name}'")

        QgsProject.instance().addMapLayer(layer)
        return layer

    # ------------------------------------------------------------------ #
    #  Query builders (PostGIS → SpatiaLite equivalences)
    # ------------------------------------------------------------------ #

    def _build_intersect_query(self, target_table, assessment_table, output_table):
        """Build intersection query using SpatiaLite functions."""
        return f"""
        CREATE TABLE {output_table} AS
        SELECT
            NULL AS gid,
            a.id AS input_id,
            b.id AS identity_id,
            CastToMultiPolygon(Intersection(a.geom, b.geom)) AS geom,
            'intersect' AS split_type,
            Area(Intersection(a.geom, b.geom)) AS shape_area,
            Perimeter(Intersection(a.geom, b.geom)) AS shape_length
        FROM {target_table} a
        JOIN {assessment_table} b
          ON Intersects(a.geom, b.geom)
        WHERE IsValid(a.geom)
          AND IsValid(b.geom)
          AND GeometryType(Intersection(a.geom, b.geom)) IN ('POLYGON', 'MULTIPOLYGON')
          AND IsValid(Intersection(a.geom, b.geom))
        """

    def _build_union_query(self, target_table, assessment_table, output_table):
        """Build union query using SpatiaLite functions."""
        return f"""
        CREATE TABLE {output_table} AS
        SELECT
            1 AS gid,
            NULL AS input_id,
            NULL AS identity_id,
            CastToMultiPolygon(GUnion(geom)) AS geom,
            'union' AS split_type,
            Area(GUnion(geom)) AS shape_area,
            Perimeter(GUnion(geom)) AS shape_length
        FROM (
            SELECT geom FROM {target_table} WHERE IsValid(geom)
            UNION ALL
            SELECT geom FROM {assessment_table} WHERE IsValid(geom)
        ) combined
        WHERE GeometryType(geom) IN ('POLYGON', 'MULTIPOLYGON')
        """

    def _build_both_query(self, target_table, assessment_table, output_table):
        """Build query for both intersection and non-intersection."""
        return f"""
        CREATE TABLE {output_table} AS
        SELECT * FROM (
            SELECT
                a.id AS input_id,
                b.id AS identity_id,
                CastToMultiPolygon(Intersection(a.geom, b.geom)) AS geom,
                'intersect' AS split_type,
                Area(Intersection(a.geom, b.geom)) AS shape_area,
                Perimeter(Intersection(a.geom, b.geom)) AS shape_length
            FROM {target_table} a
            JOIN {assessment_table} b
              ON Intersects(a.geom, b.geom)
            WHERE IsValid(a.geom)
              AND IsValid(b.geom)
              AND GeometryType(Intersection(a.geom, b.geom)) IN ('POLYGON', 'MULTIPOLYGON')
              AND IsValid(Intersection(a.geom, b.geom))

            UNION ALL

            SELECT
                a.id AS input_id,
                NULL AS identity_id,
                CastToMultiPolygon(a.geom) AS geom,
                'no_overlap' AS split_type,
                Area(a.geom) AS shape_area,
                Perimeter(a.geom) AS shape_length
            FROM {target_table} a
            LEFT JOIN {assessment_table} b
              ON Intersects(a.geom, b.geom)
            WHERE b.id IS NULL
              AND IsValid(a.geom)
        )
        """

    # ------------------------------------------------------------------ #
    #  Validation & utilities
    # ------------------------------------------------------------------ #

    def validate_geometry_compatibility(self, target_table, assessment_table):
        """
        Validate that both tables have compatible geometry types.

        Returns:
            dict: Validation results with compatibility status
        """
        cursor = self.pm.connection.cursor()

        try:
            # Get geometry info for target table
            cursor.execute(
                "SELECT geometry_type, srid FROM geometry_columns "
                "WHERE f_table_name = ? AND f_geometry_column = 'geom'",
                (target_table,)
            )
            target_result = cursor.fetchone()
            if not target_result:
                raise Exception(f"No geometry column found for table '{target_table}'")

            target_type_int, target_srid = target_result
            target_type = self.pm._geometry_type_int_to_str(target_type_int)

            # Get geometry info for assessment table
            cursor.execute(
                "SELECT geometry_type, srid FROM geometry_columns "
                "WHERE f_table_name = ? AND f_geometry_column = 'geom'",
                (assessment_table,)
            )
            assessment_result = cursor.fetchone()
            if not assessment_result:
                raise Exception(f"No geometry column found for table '{assessment_table}'")

            assessment_type_int, assessment_srid = assessment_result
            assessment_type = self.pm._geometry_type_int_to_str(assessment_type_int)

            cursor.close()

            srid_compatible = (target_srid == assessment_srid)

            polygon_types = ['POLYGON', 'MULTIPOLYGON', 'POLYGONZ', 'MULTIPOLYGONZ']
            type_compatible = (
                target_type.upper() in polygon_types and
                assessment_type.upper() in polygon_types
            )

            return {
                'compatible': srid_compatible and type_compatible,
                'srid_compatible': srid_compatible,
                'type_compatible': type_compatible,
                'target_type': target_type,
                'target_srid': target_srid,
                'assessment_type': assessment_type,
                'assessment_srid': assessment_srid,
                'message': self._get_compatibility_message(
                    srid_compatible, type_compatible,
                    target_type, assessment_type,
                    target_srid, assessment_srid
                )
            }

        except Exception as e:
            cursor.close()
            raise Exception(f"Geometry validation failed: {str(e)}")

    def get_analysis_summary(self, output_table):
        """Get detailed summary of analysis results."""
        if not self.pm.table_exists(output_table):
            raise Exception(f"Output table '{output_table}' does not exist")

        cursor = self.pm.connection.cursor()

        try:
            cursor.execute(f"""
                SELECT
                    COUNT(*) AS total_features,
                    SUM(shape_area) AS total_area,
                    AVG(shape_area) AS avg_area,
                    MAX(shape_area) AS max_area,
                    MIN(shape_area) AS min_area
                FROM {output_table}
            """)
            overall_stats = cursor.fetchone()

            cursor.execute(f"""
                SELECT
                    split_type,
                    COUNT(*) AS count,
                    SUM(shape_area) AS total_area,
                    AVG(shape_area) AS avg_area
                FROM {output_table}
                GROUP BY split_type
            """)
            type_stats = {}
            for row in cursor.fetchall():
                type_stats[row[0]] = {
                    'count': row[1],
                    'total_area': row[2],
                    'avg_area': row[3]
                }

            cursor.close()

            return {
                'total_features': overall_stats[0],
                'total_area': overall_stats[1],
                'avg_area': overall_stats[2],
                'max_area': overall_stats[3],
                'min_area': overall_stats[4],
                'by_type': type_stats
            }

        except Exception as e:
            cursor.close()
            raise Exception(f"Failed to get analysis summary: {str(e)}")

    def _detect_geometry_info(self, table_name):
        """
        Detect actual geometry type and dimension from table data.

        Returns:
            tuple: (geometry_type, dimension) e.g. ('MULTIPOLYGON', 'XY')
        """
        cursor = self.pm.connection.cursor()
        try:
            cursor.execute(
                f"SELECT DISTINCT GeometryType(geom) FROM {table_name} WHERE geom IS NOT NULL LIMIT 20"
            )
            types = [row[0] for row in cursor.fetchall() if row[0]]
            cursor.close()
        except Exception:
            cursor.close()
            return ('MULTIPOLYGON', 'XY')

        if not types:
            return ('MULTIPOLYGON', 'XY')

        # Determine dimension
        has_z = any('Z' in t for t in types)
        dimension = 'XYZ' if has_z else 'XY'

        # Determine base type - if mixed POLYGON/MULTIPOLYGON, use MULTIPOLYGON
        upper_types = [t.upper().replace(' ', '') for t in types]
        if any('MULTI' in t for t in upper_types) or len(upper_types) > 1:
            base_type = 'MULTIPOLYGON'
        elif 'POLYGON' in upper_types or 'POLYGONZ' in upper_types:
            base_type = 'POLYGON'
        else:
            base_type = 'GEOMETRY'

        if has_z and base_type != 'GEOMETRY':
            base_type += 'Z'

        return (base_type, dimension)

    def _get_srid(self, table_name):
        """Get the SRID of a table's geometry column."""
        cursor = self.pm.connection.cursor()
        cursor.execute(
            "SELECT srid FROM geometry_columns "
            "WHERE f_table_name = ? AND f_geometry_column = 'geom'",
            (table_name,)
        )
        row = cursor.fetchone()
        cursor.close()
        return row[0] if row else 4326

    def _get_compatibility_message(self, srid_compatible, type_compatible,
                                   target_type, assessment_type,
                                   target_srid, assessment_srid):
        """Generate user-friendly compatibility message."""
        if srid_compatible and type_compatible:
            return "Layers are compatible for spatial analysis"

        messages = []
        if not srid_compatible:
            messages.append(
                f"SRID mismatch: Target ({target_srid}) vs Assessment ({assessment_srid}). "
                "Layers must have the same coordinate reference system."
            )
        if not type_compatible:
            messages.append(
                f"Geometry type incompatibility: Target ({target_type}) and/or "
                f"Assessment ({assessment_type}) are not polygon-based. "
                "Both layers must be POLYGON or MULTIPOLYGON for intersection analysis."
            )
        return " ".join(messages)
