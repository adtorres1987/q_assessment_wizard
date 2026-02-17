# -*- coding: utf-8 -*-
"""
AssessmentExecutor — thin UI facade over the Application Layer use cases.

Phase 4 (Clean Architecture): this class is no longer an orchestrator.
All business logic lives in core/application/use_cases/.

Responsibilities:
  - Build Command dataclasses from raw QGIS inputs.
  - Call the appropriate use case.
  - Catch ValueError / RuntimeError and show QMessageBox to the user.
  - Return wizard_results dicts upward to the dialog.

UI layer → AssessmentExecutor (this file)
              ↓ Command dataclasses
           Use Cases (core/application/use_cases/)
              ↓ SpatialEngine / AdminManager
           Infrastructure
"""

from qgis.PyQt.QtWidgets import QMessageBox

from .core.application import (
    CreateScenarioCommand, CreateScenario,
    ApplyOverlayCommand,   ApplyOverlay,
    RollbackVersionCommand, RollbackVersion,
    CompareVersionsCommand, CompareVersions,
)


class AssessmentExecutor:
    """Thin facade: translates UI events into use-case commands."""

    OUTPUT_GROUP_NAME = "Output Layers"

    def __init__(self, project_id, admin_manager, project_db_id):
        """
        Args:
            project_id:     str — project name prefix for output layer naming
            admin_manager:  AdminManager instance
            project_db_id:  int — project database ID in admin.sqlite
        """
        self.project_id    = project_id
        self.admin_manager = admin_manager
        self.project_db_id = project_db_id

    # ------------------------------------------------------------------ #
    #  Validation helper (used by the dialog before execution)
    # ------------------------------------------------------------------ #

    def validate_assessment_name(self, assessment_name):
        """Return True if the name is available (not a duplicate)."""
        if self.admin_manager and self.project_db_id is not None:
            return not self.admin_manager.assessment_name_exists(
                self.project_db_id, assessment_name
            )
        return True

    # ------------------------------------------------------------------ #
    #  Case 1: simple (memory) assessment
    # ------------------------------------------------------------------ #

    def execute_simple_assessment(self, assessment_name, target_layer,
                                   description, parent_widget=None):
        """Create a memory layer from selected features (no spatial analysis).

        Delegates to: CreateScenario use case.

        Returns:
            dict or None: wizard_results, or None on failure.
        """
        cmd = CreateScenarioCommand(
            assessment_name=assessment_name,
            description=description,
            project_id=self.project_id,
            project_db_id=self.project_db_id,
            target_layer=target_layer,
        )
        try:
            result = CreateScenario(self.admin_manager).execute(cmd)
        except ValueError as e:
            QMessageBox.warning(parent_widget, "Cannot Create Assessment", str(e))
            return None

        layer_name = result['output_tables'][0] if result['output_tables'] else assessment_name
        QMessageBox.information(
            parent_widget,
            "Layer Created",
            f"Layer '{layer_name}' created successfully!\n\n"
            f"Features: {len(list(target_layer.selectedFeatures()))}"
        )
        return result

    # ------------------------------------------------------------------ #
    #  Case 2: spatial assessment (with overlay analysis)
    # ------------------------------------------------------------------ #

    def execute_spatial_assessment(self, assessment_name, target_layer,
                                    assessment_layers, description,
                                    parent_widget=None):
        """Run spatial overlay analysis and produce SpatiaLite base tables.

        Delegates to: ApplyOverlay use case.

        Returns:
            dict or None: wizard_results, or None on failure.
        """
        cmd = ApplyOverlayCommand(
            assessment_name=assessment_name,
            description=description,
            project_id=self.project_id,
            project_db_id=self.project_db_id,
            target_layer=target_layer,
            assessment_layers=assessment_layers,
        )
        try:
            result = ApplyOverlay(self.admin_manager).execute(cmd)
        except (ValueError, RuntimeError) as e:
            QMessageBox.critical(parent_widget, "Assessment Failed", str(e))
            return None

        layer_names = "\n• ".join(result['output_tables'])
        QMessageBox.information(
            parent_widget,
            "Assessment Complete",
            f"Assessment created successfully!\n\n"
            f"Base layer(s):\n• {layer_names}"
        )
        return result

    # ------------------------------------------------------------------ #
    #  Case 3: rollback to a previous version
    # ------------------------------------------------------------------ #

    def rollback_to_version(self, scenario_name, version_id,
                            parent_widget=None):
        """Restore HEAD to a previous version — O(1).

        Delegates to: RollbackVersion use case.

        Returns:
            dict or None: { table, version_id, layer }, or None on failure.
        """
        cmd = RollbackVersionCommand(
            scenario_name=scenario_name,
            version_id=version_id,
            project_db_id=self.project_db_id,
        )
        try:
            result = RollbackVersion(self.admin_manager).execute(cmd)
        except (ValueError, RuntimeError) as e:
            QMessageBox.critical(parent_widget, "Rollback Failed", str(e))
            return None

        QMessageBox.information(
            parent_widget,
            "Rollback Complete",
            f"Restored to version {version_id}.\n"
            f"Table: {result['table']}"
        )
        return result

    # ------------------------------------------------------------------ #
    #  Case 4: compare two versions side-by-side
    # ------------------------------------------------------------------ #

    def compare_versions(self, scenario_name, version_id_a, version_id_b,
                         parent_widget=None):
        """Load two version snapshots as QGIS layers for visual comparison.

        Delegates to: CompareVersions use case.

        Returns:
            dict or None: { layer_a, layer_b, version_id_a, version_id_b },
                          or None on failure.
        """
        cmd = CompareVersionsCommand(
            scenario_name=scenario_name,
            version_id_a=version_id_a,
            version_id_b=version_id_b,
            project_db_id=self.project_db_id,
        )
        try:
            result = CompareVersions(self.admin_manager).execute(cmd)
        except (ValueError, RuntimeError) as e:
            QMessageBox.critical(parent_widget, "Compare Failed", str(e))
            return None

        return result

    # ------------------------------------------------------------------ #
    #  Metadata recording (delegates to AdminManager directly)
    # ------------------------------------------------------------------ #

    def record_assessment(self, wizard_results):
        """Persist assessment metadata to admin.sqlite.

        Creates the assessment record, sets initial layer visibility, and —
        for spatial assessments — records provenance + task_details.

        Args:
            wizard_results: dict with assessment_name, target_layer, etc.

        Returns:
            int or None: new assessment_id, or None on failure.
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

            for table_name in wizard_results.get('output_tables', []):
                self.admin_manager.set_layer_visibility(assessment_id, table_name, True)

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
        """Create provenance + task_details entries in admin.sqlite."""
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
