# -*- coding: utf-8 -*-
"""
ApplyOverlay — use case for versioned spatial overlay analysis.

Business rules:
  - Assessment name must be unique within the project.
  - At least one assessment layer must be provided.
  - The project must have a valid SpatiaLite database path.

Steps:
  1. Validate inputs.
  2. Build a Scenario domain object (no QGIS imports in domain).
  3. Open SpatialEngine → migrate all layers.
  4. Run overlay per assessment layer → versioned tables ({name}__v{n}).
  5. Record version IDs.
  6. Return wizard_results dict.

Raises:
  - ValueError: name is duplicate or no assessment layers provided.
  - RuntimeError: project DB path not found.
"""

from .commands import ApplyOverlayCommand


class ApplyOverlay:
    """Use case: run a versioned spatial overlay for one assessment.

    Args:
        admin_manager: AdminManager instance — required (used to locate
                       the project SpatiaLite database and validate names).
    """

    OUTPUT_GROUP_NAME = "Output Layers"

    def __init__(self, admin_manager):
        if admin_manager is None:
            raise RuntimeError(
                "ApplyOverlay requires an admin_manager instance."
            )
        self._admin_manager = admin_manager

    def execute(self, cmd: ApplyOverlayCommand) -> dict:
        """Execute the spatial overlay use case.

        Args:
            cmd: ApplyOverlayCommand with all inputs.

        Returns:
            dict: wizard_results compatible dict with keys:
                  assessment_name, target_layer, assessment_layers,
                  output_tables, description, version_ids.

        Raises:
            ValueError:   name duplicate or no assessment layers given.
            RuntimeError: project DB path not found.
        """
        self._validate(cmd)

        project_db_path = self._admin_manager.get_project_db_path(cmd.project_db_id)
        if not project_db_path:
            raise RuntimeError(
                f"Project database path not found for project_db_id={cmd.project_db_id}."
            )

        scenario = self._build_scenario(cmd)
        qgs_layer_map = self._build_layer_map(cmd)

        output_tables = []
        version_ids   = []

        from ...spatial_engine import SpatialEngine
        with SpatialEngine(project_db_path) as engine:
            # Migrate all layers → populate table_name in domain objects
            for layer_ref in scenario['all_layers']:
                qgs_layer = qgs_layer_map[layer_ref['name']]
                layer_ref['table_name'] = engine.prepare_layer(qgs_layer)

            # Run versioned overlay per assessment layer
            for a_ref in scenario['assessment_layers']:
                base_name = self._make_base_name(
                    cmd.project_id, cmd.assessment_name,
                    a_ref['name'], len(scenario['assessment_layers'])
                )
                result = engine.overlay(
                    scenario['target_layer']['table_name'],
                    a_ref['table_name'],
                    base_name,
                    group_name=self.OUTPUT_GROUP_NAME,
                )
                output_tables.append(result['table'])
                version_ids.append(result['version_id'])

        return {
            'assessment_name':    cmd.assessment_name,
            'target_layer':       cmd.target_layer.name(),
            'assessment_layers':  [al.name() for al in cmd.assessment_layers],
            'output_tables':      output_tables,
            'description':        cmd.description,
            'version_ids':        version_ids,
        }

    # ------------------------------------------------------------------ #
    #  Private helpers
    # ------------------------------------------------------------------ #

    def _validate(self, cmd: ApplyOverlayCommand):
        if not cmd.assessment_layers:
            raise ValueError(
                "ApplyOverlay requires at least one assessment layer."
            )
        if self._admin_manager.assessment_name_exists(
                cmd.project_db_id, cmd.assessment_name):
            raise ValueError(
                f"Assessment name '{cmd.assessment_name}' already exists "
                f"in this project."
            )

    def _build_scenario(self, cmd: ApplyOverlayCommand) -> dict:
        """Build a lightweight scenario dict (avoids circular imports with domain)."""
        target = {'name': cmd.target_layer.name(), 'table_name': ''}
        assessments = [
            {'name': al.name(), 'table_name': ''}
            for al in cmd.assessment_layers
        ]
        all_layers = [target] + assessments
        return {
            'target_layer':     target,
            'assessment_layers': assessments,
            'all_layers':       all_layers,
        }

    def _build_layer_map(self, cmd: ApplyOverlayCommand) -> dict:
        """Map layer name → QgsVectorLayer for fast lookup during migration."""
        layer_map = {cmd.target_layer.name(): cmd.target_layer}
        layer_map.update({al.name(): al for al in cmd.assessment_layers})
        return layer_map

    @staticmethod
    def _make_base_name(project_id, assessment_name, assessment_layer_name,
                        total_count) -> str:
        """Compute the base table name for one overlay run."""
        if total_count == 1:
            return f"{project_id}__{assessment_name}"
        safe = assessment_layer_name.replace(' ', '_')
        return f"{project_id}__{assessment_name}_{safe}"
