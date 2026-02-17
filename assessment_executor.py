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

        Produces ONE final base table per assessment layer pair. Intersection and
        union are computed as temporary tables; the union is renamed as the final
        base table and the intersection temporary is dropped.

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
        output_entries = []  # list of {'table': str, 'layer': QgsVectorLayer}

        for assessment_layer in assessment_layers:
            assessment_table = pm.sanitize_table_name(assessment_layer.name())

            # Base name for the final output table
            if len(assessment_layers) == 1:
                base_name = f"{self.project_id}__{assessment_name}"
            else:
                safe = assessment_layer.name().replace(' ', '_')
                base_name = f"{self.project_id}__{assessment_name}_{safe}"

            tmp_intersect = pm.sanitize_table_name(f"{base_name}_tmp_intersect")
            tmp_union     = pm.sanitize_table_name(f"{base_name}_tmp_union")
            final_table   = pm.sanitize_table_name(base_name)

            # Drop final table if it already exists (re-run scenario)
            if pm.table_exists(final_table):
                pm.drop_table(final_table)

            # Step 1: Intersection → temporary SpatiaLite table only
            analyzer.analyze_and_create_layer(
                target_table, assessment_table, tmp_intersect,
                operation_type=OperationType.INTERSECT,
                add_to_qgis=False
            )

            # Step 2: Union → temporary SpatiaLite table only
            analyzer.analyze_and_create_layer(
                target_table, assessment_table, tmp_union,
                operation_type=OperationType.UNION,
                add_to_qgis=False
            )

            # Step 3: Promote union table as the final base table
            pm.rename_table(tmp_union, final_table)

            # Step 4: Drop intersection temporary
            pm.drop_table(tmp_intersect)

            # Step 5: Load the final table as a single QGIS layer
            layer = analyzer._create_qgis_layer(
                final_table, base_name, group_name=self.OUTPUT_GROUP_NAME
            )
            output_entries.append({'table': final_table, 'layer': layer})

        pm.disconnect()

        if output_entries:
            layer_names = "\n• ".join(e['layer'].name() for e in output_entries)
            QMessageBox.information(
                parent_widget,
                "Assessment Complete",
                f"Assessment created successfully!\n\n"
                f"Base layer(s):\n• {layer_names}"
            )

        return {
            'assessment_name': assessment_name,
            'target_layer': target_layer.name(),
            'assessment_layers': [l.name() for l in assessment_layers],
            'output_tables': [e['table'] for e in output_entries],
            'description': description
        }

    def record_assessment(self, wizard_results):
        """Record assessment in the admin metadata database.

        Creates the assessment, sets initial layer visibility, and — for
        spatial assessments — adds a provenance + task_details record so the
        TreeView can show the full EMDS 3 hierarchy.

        Args:
            wizard_results: dict with assessment_name, target_layer, etc.

        Returns:
            int or None: the new assessment_id, or None on failure / no admin_manager
        """
        if not (self.admin_manager and self.project_db_id is not None):
            return None

        try:
            assessment_id = self.admin_manager.create_assessment(
                project_id=self.project_db_id,
                name=wizard_results.get('assessment_name', ''),
                description=wizard_results.get('description', ''),
                target_layer=wizard_results.get('target_layer', ''),
                assessment_layers=wizard_results.get('assessment_layers', []),
                output_tables=wizard_results.get('output_tables', [])
            )

            # Persist default visibility (visible=1) for each output table
            for table_name in wizard_results.get('output_tables', []):
                self.admin_manager.set_layer_visibility(assessment_id, table_name, True)

            # For spatial assessments record provenance + initial task
            if wizard_results.get('assessment_layers'):
                self._record_provenance(
                    assessment_id=assessment_id,
                    output_tables=wizard_results.get('output_tables', []),
                    target_layer_name=wizard_results.get('target_layer', ''),
                    assessment_layer_names=wizard_results.get('assessment_layers', [])
                )

            return assessment_id

        except Exception as e:
            print(f"Warning: Could not record assessment in metadata: {e}")
            return None

    def _record_provenance(self, assessment_id, output_tables,
                           target_layer_name, assessment_layer_names):
        """Create a provenance + task_details entry for a completed spatial analysis.

        Args:
            assessment_id: int
            output_tables: list[str] — final output table name(s)
            target_layer_name: str
            assessment_layer_names: list[str]
        """
        if not self.admin_manager:
            return
        try:
            provenance_id = self.admin_manager.create_provenance(
                assessment_id=assessment_id,
                name="Initial Assessment",
                description="Base spatial analysis: union + intersection"
            )
            self.admin_manager.add_task(
                provenance_id=provenance_id,
                step_order=1,
                operation="union+intersect",
                category="spatial_analysis",
                engine_type="spatialite",
                input_tables=[target_layer_name] + assessment_layer_names,
                output_tables=output_tables,
                added_to_map=True
            )
        except Exception as e:
            print(f"Warning: Could not record provenance: {e}")
