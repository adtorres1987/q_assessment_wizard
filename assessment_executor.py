# -*- coding: utf-8 -*-
"""
Assessment Executor Module
Executes assessment workflows: memory-only or spatial analysis via SpatiaLite.
"""

from qgis.PyQt.QtWidgets import QMessageBox, QProgressDialog
from qgis.PyQt.QtCore import Qt, QCoreApplication
from qgis.core import QgsProject, QgsVectorLayer, QgsWkbTypes

from .project_manager import ProjectManager
from .spatial_analysis_spatialite import SpatialAnalyzerLite, OperationType


class AssessmentExecutor:
    """Executes assessment workflows: memory-only or spatial analysis."""

    #  Group name for created layers in the layer tree
    OUTPUT_GROUP_NAME = "Output Layers" 

    def __init__(self, project_id, admin_manager, project_db_id):
        """
        Args:
            project_id: str - project name/prefix for naming output layers
            admin_manager: AdminManager instance
            project_db_id: int - project database ID
        """
        self.project_id = project_id
        self.admin_manager = admin_manager
        self.project_db_id = project_db_id

    def _get_or_create_output_group(self):
        """Get or create the output layers group in the layer tree.

        Returns:
            QgsLayerTreeGroup
        """
        root = QgsProject.instance().layerTreeRoot()
        group = root.findGroup(self.OUTPUT_GROUP_NAME)
        if not group:
            group = root.addGroup(self.OUTPUT_GROUP_NAME)
        return group

    def validate_assessment_name(self, assessment_name):
        """Check if assessment name already exists.

        Returns:
            bool: True if name is available, False if duplicate
        """
        if self.admin_manager and self.project_db_id is not None:
            return not self.admin_manager.assessment_name_exists(
                self.project_db_id, assessment_name
            )
        return True

    def execute_simple_assessment(self, assessment_name, target_layer,
                                   description, parent_widget=None):
        """Case 1: Only target layer -- create memory layer from selected features.

        Args:
            assessment_name: str
            target_layer: QgsVectorLayer with features selected
            description: str
            parent_widget: QWidget for dialog parenting

        Returns:
            dict or None: wizard_results dict, or None on failure
        """
        selected_features = list(target_layer.selectedFeatures())

        if not selected_features:
            QMessageBox.warning(
                parent_widget,
                "No Features Selected",
                "No features are selected in the target layer. "
                "Please select features in Page 2."
            )
            return None

        # Create memory layer with selected features
        geom_type = QgsWkbTypes.displayString(target_layer.wkbType())
        crs = target_layer.crs().authid()
        layer_name = f"{self.project_id}__{assessment_name}"

        memory_layer = QgsVectorLayer(
            f"{geom_type}?crs={crs}",
            layer_name,
            "memory"
        )

        memory_layer.dataProvider().addAttributes(target_layer.fields().toList())
        memory_layer.updateFields()
        memory_layer.dataProvider().addFeatures(selected_features)
        memory_layer.updateExtents()

        group = self._get_or_create_output_group()
        QgsProject.instance().addMapLayer(memory_layer, False)
        group.addLayer(memory_layer)

        QMessageBox.information(
            parent_widget,
            "Layer Created",
            f"Layer '{layer_name}' created successfully!\n\n"
            f"Features: {len(selected_features)}"
        )

        return {
            'assessment_name': assessment_name,
            'target_layer': target_layer.name(),
            'assessment_layers': [],
            'output_tables': [layer_name],
            'description': description
        }

    def execute_spatial_assessment(self, assessment_name, target_layer,
                                     assessment_layers, description,
                                     parent_widget=None):
        """Case 2: Target + assessment layers -- spatial analysis via SpatiaLite.

        Args:
            assessment_name: str
            target_layer: QgsVectorLayer
            assessment_layers: list[QgsVectorLayer]
            description: str
            parent_widget: QWidget for dialog parenting

        Returns:
            dict or None: wizard_results dict, or None on failure
        """
        project_db_path = self.admin_manager.get_project_db_path(self.project_db_id)
        if not project_db_path:
            raise Exception("Project database path not found.")

        pm = ProjectManager(project_db_path)
        pm.connect()

        # Migrate target and assessment layers if not already in SpatiaLite
        target_table = pm.sanitize_table_name(target_layer.name())
        if not pm.table_exists(target_table):
            pm.migrate_layer(target_layer, target_table)

        for al in assessment_layers:
            at = pm.sanitize_table_name(al.name())
            if not pm.table_exists(at):
                pm.migrate_layer(al, at)

        analyzer = SpatialAnalyzerLite(pm)
        results = []

        for assessment_layer in assessment_layers:
            assessment_table = pm.sanitize_table_name(assessment_layer.name())

            # Create base output name
            if len(assessment_layers) == 1:
                base_name = f"{self.project_id}__{assessment_name}"
            else:
                base_name = f"{self.project_id}__{assessment_name}_{assessment_layer.name().replace(' ', '_')}"

            # Perform Intersection
            output_table_intersect = pm.sanitize_table_name(f"{base_name}_intersection")
            result_intersect = analyzer.analyze_and_create_layer(
                target_table,
                assessment_table,
                output_table_intersect,
                layer_name=f"{base_name}_intersection",
                operation_type=OperationType.INTERSECT,
                group_name=self.OUTPUT_GROUP_NAME
            )
            results.append(result_intersect)

            # Perform Union
            output_table_union = pm.sanitize_table_name(f"{base_name}_union")
            result_union = analyzer.analyze_and_create_layer(
                target_table,
                assessment_table,
                output_table_union,
                layer_name=f"{base_name}_union",
                operation_type=OperationType.UNION,
                group_name=self.OUTPUT_GROUP_NAME
            )
            results.append(result_union)

        pm.disconnect()

        # Show success message
        if results:
            total_features = sum(r['total_count'] for r in results)
            layer_names = "\n• ".join(r['layer'].name() for r in results)

            QMessageBox.information(
                parent_widget,
                "Analysis Complete",
                f"Spatial analysis completed successfully!\n\n"
                f"Created layer(s):\n• {layer_names}\n\n"
                f"Total features: {total_features}"
            )

        return {
            'assessment_name': assessment_name,
            'target_layer': target_layer.name(),
            'assessment_layers': [l.name() for l in assessment_layers],
            'output_tables': [r['layer'].name() for r in results] if results else [],
            'description': description
        }

    def record_assessment(self, wizard_results):
        """Record assessment in the admin metadata database.

        Args:
            wizard_results: dict with assessment_name, target_layer, etc.
        """
        if self.admin_manager and self.project_db_id is not None:
            try:
                self.admin_manager.create_assessment(
                    project_id=self.project_db_id,
                    name=wizard_results.get('assessment_name', ''),
                    description=wizard_results.get('description', ''),
                    target_layer=wizard_results.get('target_layer', ''),
                    assessment_layers=wizard_results.get('assessment_layers', []),
                    output_tables=wizard_results.get('output_tables', [])
                )
            except Exception as e:
                print(f"Warning: Could not record assessment in metadata: {e}")
