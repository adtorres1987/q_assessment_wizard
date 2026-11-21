# -*- coding: utf-8 -*-
"""
Project catalog use cases (writes): projects, assessments, portfolios,
layer visibility and MCDA weights.

Business rules:
  - A project name is required.
  - MCDA weights are non-negative fractions whose sum is 1.0 (±0.005,
    the same tolerance the weights dialog accepts: 100 % ± 0.5).

Raises:
  - ValueError: a business rule is violated.
"""

from ..ports import MetadataRepositoryPort
from .commands import (
    CreateProjectCommand, DeleteProjectCommand, DeleteAssessmentCommand,
    DeletePortfolioCommand, SetLayerVisibilityCommand, UpdateWeightsCommand,
)

WEIGHTS_SUM_TOLERANCE = 0.005


class _CatalogUseCase:

    def __init__(self, metadata_repo: MetadataRepositoryPort):
        if metadata_repo is None:
            raise RuntimeError(f"{type(self).__name__} requires a metadata_repo instance.")
        self._meta = metadata_repo


class CreateProject(_CatalogUseCase):
    """Use case: create a project. Returns its id."""

    def execute(self, cmd: CreateProjectCommand) -> int:
        name = (cmd.name or '').strip()
        if not name:
            raise ValueError("Project name is required.")
        return self._meta.create_project(name, cmd.description or "")


class DeleteProject(_CatalogUseCase):
    """Use case: soft-delete a project (its SpatiaLite file is kept)."""

    def execute(self, cmd: DeleteProjectCommand) -> None:
        self._meta.delete_project(cmd.project_id)


class DeleteAssessment(_CatalogUseCase):
    """Use case: soft-delete an assessment."""

    def execute(self, cmd: DeleteAssessmentCommand) -> None:
        self._meta.delete_assessment(cmd.assessment_id)


class DeletePortfolio(_CatalogUseCase):
    """Use case: delete a portfolio configuration."""

    def execute(self, cmd: DeletePortfolioCommand) -> None:
        self._meta.delete_portfolio(cmd.portfolio_id)


class SetLayerVisibility(_CatalogUseCase):
    """Use case: remember whether an output layer is shown on the map."""

    def execute(self, cmd: SetLayerVisibilityCommand) -> None:
        self._meta.set_layer_visibility(cmd.assessment_id, cmd.table_name, cmd.visible)


class UpdateWeights(_CatalogUseCase):
    """Use case: validate and store the MCDA weights of an assessment."""

    def execute(self, cmd: UpdateWeightsCommand) -> dict:
        weights = {name: float(w) for name, w in (cmd.weights or {}).items()}
        if any(w < 0 for w in weights.values()):
            raise ValueError("Weights cannot be negative.")
        total = sum(weights.values())
        if abs(total - 1.0) > WEIGHTS_SUM_TOLERANCE:
            raise ValueError(
                f"Weights must sum to 100%. Currently: {total * 100:.1f}%"
            )
        self._meta.update_analysis_config(cmd.assessment_id, weights=weights)
        return weights
