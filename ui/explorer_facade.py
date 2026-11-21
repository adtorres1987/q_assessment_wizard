# -*- coding: utf-8 -*-
"""
ExplorerFacade — the EMDS Project Explorer's single entry point to the
application layer.

The panel, the tree, the detail panels and the weights editor call this
facade instead of the metadata repository. Methods raise ValueError /
RuntimeError (no QMessageBox): the widgets decide how to show errors.
Per-project analysis operations (overlay, versions, MCDA, results,
portfolios, migration) go through the AssessmentExecutor returned by
:meth:`executor_for`.
"""

from ..core.application import (
    CreateProject, CreateProjectCommand,
    DeleteProject, DeleteProjectCommand,
    DeleteAssessment, DeleteAssessmentCommand,
    DeletePortfolio, DeletePortfolioCommand,
    SetLayerVisibility, SetLayerVisibilityCommand,
    UpdateWeights, UpdateWeightsCommand,
    GetProjectTree, GetProjectSummary, GetAssessmentDetails, GetAnalysisWeights,
    GetWeightsConfig, GetPortfolio,
)
from .assessment_executor import AssessmentExecutor


class ExplorerFacade:
    """Wires the explorer use cases to one metadata repository.

    Args:
        metadata_repo: MetadataRepositoryPort implementation (AdminManager).
    """

    def __init__(self, metadata_repo):
        self._meta = metadata_repo
        self._create_project = CreateProject(metadata_repo)
        self._delete_project = DeleteProject(metadata_repo)
        self._delete_assessment = DeleteAssessment(metadata_repo)
        self._delete_portfolio = DeletePortfolio(metadata_repo)
        self._set_visibility = SetLayerVisibility(metadata_repo)
        self._update_weights = UpdateWeights(metadata_repo)
        self._tree = GetProjectTree(metadata_repo)
        self._summary = GetProjectSummary(metadata_repo)
        self._assessment_details = GetAssessmentDetails(metadata_repo)
        self._analysis_weights = GetAnalysisWeights(metadata_repo)
        self._weights_config = GetWeightsConfig(metadata_repo)
        self._portfolio = GetPortfolio(metadata_repo)

    # ── per-project operations ────────────────────────────────────────────

    def executor_for(self, project_id, project_name):
        """AssessmentExecutor for one project (analysis operations)."""
        return AssessmentExecutor(project_name, self._meta, project_id)

    # ── reads ─────────────────────────────────────────────────────────────

    def project_tree(self):
        return self._tree.execute()

    def project_summary(self, project_id):
        return self._summary.execute(project_id)

    def assessment_details(self, assessment_id):
        return self._assessment_details.execute(assessment_id)

    def analysis_weights(self, assessment_id, table_name=''):
        return self._analysis_weights.execute(assessment_id, table_name)

    def weights_config(self, assessment_id):
        return self._weights_config.execute(assessment_id)

    def portfolio(self, portfolio_id):
        return self._portfolio.execute(portfolio_id)

    # ── writes ────────────────────────────────────────────────────────────

    def create_project(self, name, description=""):
        return self._create_project.execute(CreateProjectCommand(name, description))

    def delete_project(self, project_id):
        self._delete_project.execute(DeleteProjectCommand(project_id))

    def delete_assessment(self, assessment_id):
        self._delete_assessment.execute(DeleteAssessmentCommand(assessment_id))

    def delete_portfolio(self, portfolio_id):
        self._delete_portfolio.execute(DeletePortfolioCommand(portfolio_id))

    def set_layer_visibility(self, assessment_id, table_name, visible):
        self._set_visibility.execute(
            SetLayerVisibilityCommand(assessment_id, table_name, visible)
        )

    def update_weights(self, assessment_id, weights):
        return self._update_weights.execute(UpdateWeightsCommand(assessment_id, weights))
