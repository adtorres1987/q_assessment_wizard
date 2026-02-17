# -*- coding: utf-8 -*-
"""
CreateScenario — use case for memory-layer assessments (no spatial analysis).

Business rule:
  - Assessment name must be unique within the project.
  - At least one feature must be selected in the target layer.

Output:
  - QGIS memory layer added to the project's output group.
  - Returns a wizard_results dict (same contract as AssessmentExecutor).

Raises:
  - ValueError: if name is a duplicate or no features are selected.
"""

from qgis.core import QgsProject, QgsVectorLayer, QgsWkbTypes

from .commands import CreateScenarioCommand

OUTPUT_GROUP_NAME = "Output Layers"


class CreateScenario:
    """Use case: create a simple assessment as a QGIS memory layer.

    No SpatialEngine involved — the output is ephemeral (memory) and lives
    only in the current QGIS session.

    Args:
        admin_manager: AdminManager instance (optional — if None, name
                       uniqueness validation is skipped).
    """

    def __init__(self, admin_manager=None):
        self._admin_manager = admin_manager

    def execute(self, cmd: CreateScenarioCommand,
                group_name: str = OUTPUT_GROUP_NAME) -> dict:
        """Execute the use case.

        Args:
            cmd:        CreateScenarioCommand with all inputs.
            group_name: QGIS layer tree group for the output layer.

        Returns:
            dict: wizard_results compatible dict with keys:
                  assessment_name, target_layer, assessment_layers,
                  output_tables, description, version_ids.

        Raises:
            ValueError: assessment name already exists, or no features selected.
        """
        self._validate_unique_name(cmd.assessment_name, cmd.project_db_id)
        self._validate_selection(cmd.target_layer)

        layer_name = f"{cmd.project_id}__{cmd.assessment_name}"
        memory_layer = self._build_memory_layer(cmd.target_layer, layer_name)
        self._add_to_qgis(memory_layer, group_name)

        return {
            'assessment_name': cmd.assessment_name,
            'target_layer':    cmd.target_layer.name(),
            'assessment_layers': [],
            'output_tables':   [layer_name],
            'description':     cmd.description,
            'version_ids':     [],
        }

    # ------------------------------------------------------------------ #
    #  Private helpers
    # ------------------------------------------------------------------ #

    def _validate_unique_name(self, assessment_name, project_db_id):
        if self._admin_manager and project_db_id is not None:
            if self._admin_manager.assessment_name_exists(project_db_id, assessment_name):
                raise ValueError(
                    f"Assessment name '{assessment_name}' already exists "
                    f"in this project."
                )

    def _validate_selection(self, target_layer):
        selected = list(target_layer.selectedFeatures())
        if not selected:
            raise ValueError(
                "No features are selected in the target layer. "
                "Please select features before creating the assessment."
            )

    def _build_memory_layer(self, target_layer, layer_name):
        selected = list(target_layer.selectedFeatures())
        geom_type = QgsWkbTypes.displayString(target_layer.wkbType())
        crs = target_layer.crs().authid()

        memory_layer = QgsVectorLayer(
            f"{geom_type}?crs={crs}", layer_name, "memory"
        )
        dp = memory_layer.dataProvider()
        dp.addAttributes(target_layer.fields().toList())
        memory_layer.updateFields()
        dp.addFeatures(selected)
        memory_layer.updateExtents()
        return memory_layer

    def _add_to_qgis(self, layer, group_name):
        root = QgsProject.instance().layerTreeRoot()
        group = root.findGroup(group_name) or root.addGroup(group_name)
        QgsProject.instance().addMapLayer(layer, False)
        group.addLayer(layer)
