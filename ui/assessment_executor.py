# -*- coding: utf-8 -*-
"""
AssessmentExecutor — thin UI facade over the Application Layer use cases.

Responsibilities:
  - Instantiate use cases with their dependencies (ports).
  - Build Command dataclasses from raw QGIS inputs.
  - Call the appropriate use case.
  - Catch ValueError / RuntimeError and show QMessageBox to the user.
  - Return wizard_results dicts upward to the dialog.

UI layer → AssessmentExecutor (this file)
              ↓ Command dataclasses
           Use Cases (core/application/use_cases/)
              ↓ Ports (MetadataRepositoryPort, SpatialEnginePort)
           Infrastructure (AdminManager, SpatialEngine)
"""

from qgis.PyQt.QtWidgets import QMessageBox

from .translator import tr
from .core.application import (
    CreateScenarioCommand,  CreateScenario,
    ApplyOverlayCommand,    ApplyOverlay,
    RollbackVersionCommand, RollbackVersion,
    CompareVersionsCommand, CompareVersions,
    GetResultsGridCommand,  GetResultsGrid, GetResultColumns,
    GetComparisonSeriesCommand, GetComparisonSeries,
    CreatePortfolioCommand, CreatePortfolio,
)
from .core.application.use_cases.rerun_spatial_assessment import (
    RerunSpatialAssessment, RerunSpatialAssessmentCommand,
)
from .core.application.use_cases.apply_mcda_score import (
    ApplyMcdaScore, ApplyMcdaScoreCommand,
)
from .core.application.use_cases.record_assessment import (
    RecordAssessment, RecordAssessmentCommand,
)


class AssessmentExecutor:
    """Thin facade: translates UI events into use-case commands."""

    def __init__(self, project_id, admin_manager, project_db_id):
        """
        Args:
            project_id:    str  — project name prefix for output layer naming
            admin_manager: AdminManager — satisfies MetadataRepositoryPort
            project_db_id: int  — project PK in admin.sqlite
        """
        from .core.infrastructure.spatial import SpatialEngine

        self.project_id    = project_id
        self.project_db_id = project_db_id

        # Use case instances — each receives only the ports it needs
        self._create_scenario = CreateScenario(admin_manager)
        self._apply_overlay   = ApplyOverlay(admin_manager, SpatialEngine)
        self._rollback        = RollbackVersion(admin_manager, SpatialEngine)
        self._compare         = CompareVersions(admin_manager, SpatialEngine)
        self._rerun           = RerunSpatialAssessment(admin_manager, SpatialEngine)
        self._mcda            = ApplyMcdaScore(admin_manager, SpatialEngine)
        self._record          = RecordAssessment(admin_manager)
        self._grid            = GetResultsGrid(admin_manager, SpatialEngine)
        self._columns         = GetResultColumns(admin_manager, SpatialEngine)
        self._series          = GetComparisonSeries(admin_manager, SpatialEngine)
        self._portfolio       = CreatePortfolio(admin_manager)

        # Keep reference for validate_assessment_name (thin query)
        self._meta = admin_manager

    # ------------------------------------------------------------------ #
    #  Validation helper
    # ------------------------------------------------------------------ #

    def validate_assessment_name(self, assessment_name):
        """Return True if the name is available (not a duplicate)."""
        if self._meta and self.project_db_id is not None:
            return not self._meta.assessment_name_exists(
                self.project_db_id, assessment_name
            )
        return True

    # ------------------------------------------------------------------ #
    #  Case 1: simple (memory) assessment
    # ------------------------------------------------------------------ #

    def execute_simple_assessment(self, assessment_name, target_layer,
                                   description, parent_widget=None):
        """Create a memory layer from selected features (no spatial analysis)."""
        cmd = CreateScenarioCommand(
            assessment_name=assessment_name,
            description=description,
            project_id=self.project_id,
            project_db_id=self.project_db_id,
            target_layer=target_layer,
        )
        try:
            result = self._create_scenario.execute(cmd)
        except ValueError as e:
            QMessageBox.warning(parent_widget, tr('executor.cannot_create_title'), str(e))
            return None

        layer_name = result['output_tables'][0] if result['output_tables'] else assessment_name
        QMessageBox.information(
            parent_widget,
            tr('executor.layer_created_title'),
            tr('executor.layer_created_body', name=layer_name,
               count=len(list(target_layer.selectedFeatures())))
        )
        return result

    # ------------------------------------------------------------------ #
    #  Case 2: spatial assessment (with overlay analysis)
    # ------------------------------------------------------------------ #

    def execute_spatial_assessment(self, assessment_name, target_layer,
                                    assessment_layers, description,
                                    allow_rerun=False, parent_widget=None):
        """Run spatial overlay analysis and produce SpatiaLite base tables."""
        cmd = ApplyOverlayCommand(
            assessment_name=assessment_name,
            description=description,
            project_id=self.project_id,
            project_db_id=self.project_db_id,
            target_layer=target_layer,
            assessment_layers=assessment_layers,
            allow_rerun=allow_rerun,
        )
        try:
            result = self._apply_overlay.execute(cmd)
        except (ValueError, RuntimeError) as e:
            QMessageBox.critical(parent_widget, tr('executor.failed_title'), str(e))
            return None

        layer_names = "\n• ".join(result['output_tables'])
        QMessageBox.information(
            parent_widget,
            tr('executor.complete_title'),
            tr('executor.complete_body', tables=layer_names)
        )
        return result

    # ------------------------------------------------------------------ #
    #  Case 2b: re-run spatial assessment (new version)
    # ------------------------------------------------------------------ #

    def rerun_spatial_assessment(self, assessment_id, parent_widget=None):
        """Re-run overlay for an existing assessment, creating version n+1."""
        cmd = RerunSpatialAssessmentCommand(
            assessment_id=assessment_id,
            project_id=self.project_id,
            project_db_id=self.project_db_id,
        )
        try:
            result = self._rerun.execute(cmd)
        except (ValueError, RuntimeError) as e:
            QMessageBox.critical(parent_widget, tr('executor.version_failed_title'), str(e))
            return None

        layer_names = "\n• ".join(result['output_tables'])
        QMessageBox.information(
            parent_widget,
            tr('executor.version_title'),
            tr('executor.version_body', tables=layer_names)
        )
        return result

    # ------------------------------------------------------------------ #
    #  Case 3: rollback to a previous version
    # ------------------------------------------------------------------ #

    def rollback_to_version(self, scenario_name, version_id,
                            parent_widget=None):
        """Restore HEAD to a previous version — O(1)."""
        cmd = RollbackVersionCommand(
            scenario_name=scenario_name,
            version_id=version_id,
            project_db_id=self.project_db_id,
        )
        try:
            result = self._rollback.execute(cmd)
        except (ValueError, RuntimeError) as e:
            QMessageBox.critical(parent_widget, tr('executor.rollback_failed_title'), str(e))
            return None

        QMessageBox.information(
            parent_widget,
            tr('executor.rollback_title'),
            tr('executor.rollback_body', version=version_id, table=result['table'])
        )
        return result

    # ------------------------------------------------------------------ #
    #  Case 4: compare two versions side-by-side
    # ------------------------------------------------------------------ #

    def compare_versions(self, scenario_name, version_id_a, version_id_b,
                         parent_widget=None):
        """Load two version snapshots as QGIS layers for visual comparison."""
        cmd = CompareVersionsCommand(
            scenario_name=scenario_name,
            version_id_a=version_id_a,
            version_id_b=version_id_b,
            project_db_id=self.project_db_id,
        )
        try:
            result = self._compare.execute(cmd)
        except (ValueError, RuntimeError) as e:
            QMessageBox.critical(parent_widget, tr('executor.compare_failed_title'), str(e))
            return None

        return result

    # ------------------------------------------------------------------ #
    #  MCDA Scoring
    # ------------------------------------------------------------------ #

    def apply_mcda_score(self, assessment_id, table_name, parent_widget=None):
        """Apply weighted area-proportional MCDA score to a SpatiaLite overlay table."""
        cmd = ApplyMcdaScoreCommand(
            assessment_id=assessment_id,
            table_name=table_name,
            project_db_id=self.project_db_id,
        )
        try:
            self._mcda.execute(cmd)
        except ValueError as e:
            QMessageBox.warning(parent_widget, tr('executor.mcda_no_config_title'), str(e))
            return False
        except (RuntimeError, Exception) as e:
            QMessageBox.critical(parent_widget, tr('executor.mcda_error_title'), str(e))
            return False

        QMessageBox.information(
            parent_widget, tr('executor.mcda_title'),
            tr('executor.mcda_body', table=table_name)
        )
        return True

    # ------------------------------------------------------------------ #
    #  Metadata recording
    # ------------------------------------------------------------------ #

    def record_assessment(self, wizard_results):
        """Persist assessment metadata to admin.sqlite (first run)."""
        cmd = RecordAssessmentCommand(
            wizard_results=wizard_results,
            project_db_id=self.project_db_id,
        )
        try:
            return self._record.execute(cmd)
        except Exception as e:
            print(f"Warning: Could not record assessment in metadata: {e}")
            return None

    def record_new_version(self, existing_assessment_id, wizard_results):
        """Record new output layers + provenance for an existing assessment (v2+)."""
        if not existing_assessment_id:
            return
        cmd = RecordAssessmentCommand(
            wizard_results=wizard_results,
            project_db_id=self.project_db_id,
            existing_assessment_id=existing_assessment_id,
        )
        try:
            self._record.execute(cmd)
        except Exception as e:
            print(f"Warning: Could not record new version metadata: {e}")

    # ------------------------------------------------------------------ #
    #  Results grid / comparison / portfolio
    # ------------------------------------------------------------------ #

    def get_results_grid(self, table_name):
        """Per-target-feature summary of an overlay table.

        Returns:
            dict: {'table', 'columns', 'rows'}

        Raises:
            LookupError: the table is not in SpatiaLite (caller may fall back
                         to the QGIS layer, e.g. for simple assessments).
            ValueError / RuntimeError: not an overlay table / DB not found.
        """
        return self._grid.execute(
            GetResultsGridCommand(project_db_id=self.project_db_id,
                                  table_name=table_name)
        )

    def get_result_columns(self, table_name):
        """Non-geometry columns of a result table (raises LookupError if missing)."""
        return self._columns.execute(
            GetResultsGridCommand(project_db_id=self.project_db_id,
                                  table_name=table_name)
        )

    def get_comparison_series(self, tables, field_name):
        """Return {label: [values]} for the paired histogram.

        Raises:
            LookupError / ValueError / RuntimeError — shown by the dialog.
        """
        return self._series.execute(
            GetComparisonSeriesCommand(project_db_id=self.project_db_id,
                                       tables=tables, field_name=field_name)
        )

    def create_portfolio(self, assessment_id, source_table, config,
                         parent_widget=None):
        """Validate and store a portfolio configuration (status 'pending').

        Args:
            config: dict from PortfolioWizard.get_config().

        Returns:
            dict {'portfolio_id', 'name', 'config'} or None on validation error.
        """
        cmd = CreatePortfolioCommand(
            assessment_id=assessment_id,
            source_table=source_table,
            name=config.get('portfolio_name', ''),
            col_benefits=config.get('col_benefits', ''),
            col_cost=config.get('col_cost', ''),
            col_priority=config.get('col_priority', ''),
            budget=config.get('budget', 0.0),
            buckets=config.get('buckets', []),
        )
        try:
            return self._portfolio.execute(cmd)
        except ValueError as e:
            QMessageBox.warning(parent_widget, tr('main.portfolio_title'), str(e))
            return None
