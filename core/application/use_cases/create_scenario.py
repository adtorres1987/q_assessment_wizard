# -*- coding: utf-8 -*-
"""
CreateScenario — use case for memory-layer assessments (no spatial analysis).

Business rule:
  - Assessment name must be unique within the project.
  - At least one feature must be selected in the target layer.

Output:
  - Memory layer (via MapLayersPort) added to the project's output group.
  - Returns a wizard_results dict (same contract as AssessmentExecutor).

Raises:
  - ValueError: if name is a duplicate or no features are selected.
"""

from ..ports import MetadataRepositoryPort, MapLayersPort
from .commands import CreateScenarioCommand

OUTPUT_GROUP_NAME = "Output Layers"


class CreateScenario:
    """Use case: create a simple assessment as a QGIS memory layer.

    No SpatialEngine involved — the output is ephemeral (memory) and lives
    only in the current QGIS session.

    Args:
        metadata_repo: MetadataRepositoryPort implementation (optional — if
                       None, name uniqueness validation is skipped).
        map_layers:    MapLayersPort implementation (QGIS map access).
    """

    def __init__(self, metadata_repo: MetadataRepositoryPort = None,
                 map_layers: MapLayersPort = None):
        if map_layers is None:
            raise RuntimeError("CreateScenario requires a map_layers instance.")
        self._meta = metadata_repo
        self._map = map_layers

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
        self._map.add_selection_as_memory_layer(cmd.target_layer, layer_name, group_name)

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
        if self._meta and project_db_id is not None:
            if self._meta.assessment_name_exists(project_db_id, assessment_name):
                raise ValueError(
                    f"Assessment name '{assessment_name}' already exists "
                    f"in this project."
                )

    def _validate_selection(self, target_layer):
        if self._map.selected_feature_count(target_layer) == 0:
            raise ValueError(
                "No features are selected in the target layer. "
                "Please select features before creating the assessment."
            )
