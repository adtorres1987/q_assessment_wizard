# -*- coding: utf-8 -*-
"""
OperationRunner — executes spatial SQL operations against a SpatialRepository.

Wraps SpatialAnalyzerLite so that higher layers never import it directly.
"""

from enum import Enum


class OverlayOperation(Enum):
    """Supported overlay operation types.

    Values match the logical names used in task_details.operation field.
    """
    INTERSECT = "intersect"
    UNION     = "union"
    BOTH      = "both"


class OperationRunner:
    """Executes a single spatial operation against a SpatialRepository.

    The runner is always bound to an open repository — it should not be
    instantiated outside of SpatialEngine.
    """

    # Mapping from OverlayOperation to SpatialAnalyzerLite OperationType
    _OP_MAP = None  # lazily populated to avoid import at module load

    def __init__(self, repository):
        self._repo = repository

    def execute(self, target_table, assessment_table, output_table,
                operation=OverlayOperation.UNION):
        """Run a spatial operation and write results to a SpatiaLite table.

        Args:
            target_table: str — source table name
            assessment_table: str — overlay table name
            output_table: str — name for the result table
            operation: OverlayOperation

        Returns:
            int: number of rows written to output_table
        """
        from ...spatial_analysis_spatialite import SpatialAnalyzerLite, OperationType

        op_map = {
            OverlayOperation.INTERSECT: OperationType.INTERSECT,
            OverlayOperation.UNION:     OperationType.UNION,
            OverlayOperation.BOTH:      OperationType.BOTH,
        }
        analyzer = SpatialAnalyzerLite(self._repo.project_manager)
        result = analyzer.analyze_and_create_layer(
            target_table, assessment_table, output_table,
            operation_type=op_map[operation],
            add_to_qgis=False
        )
        return result.get('total_count', 0)

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
