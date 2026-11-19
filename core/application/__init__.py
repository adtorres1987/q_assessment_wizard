# -*- coding: utf-8 -*-
"""
Application layer — use cases and ports for the Assessment Wizard plugin.

Each use case:
  - Receives a Command dataclass (input DTO)
  - Validates business rules via MetadataRepositoryPort
  - Orchestrates domain objects and infrastructure via SpatialEnginePort
  - Returns a plain dict result
  - Raises ValueError / RuntimeError on failure (NO QMessageBox)

Layer position:
    UI (dialog)
      ↓ QgsVectorLayer + primitive types
    AssessmentExecutor (thin facade — handles QMessageBox, creates commands)
      ↓ Command dataclasses
    Use Cases (this package)
      ↓ Ports (MetadataRepositoryPort, SpatialEnginePort)
    Infrastructure (AdminManager, SpatialEngine)
"""

from .use_cases import (
    CreateScenarioCommand,
    ApplyOverlayCommand,
    RollbackVersionCommand,
    CompareVersionsCommand,
    RerunSpatialAssessmentCommand,
    ApplyMcdaScoreCommand,
    RecordAssessmentCommand,
    GetResultsGridCommand,
    GetComparisonSeriesCommand,
    CreatePortfolioCommand,
    CreateScenario,
    ApplyOverlay,
    RollbackVersion,
    CompareVersions,
    RerunSpatialAssessment,
    ApplyMcdaScore,
    RecordAssessment,
    GetResultsGrid,
    GetResultColumns,
    GetComparisonSeries,
    CreatePortfolio,
)

__all__ = [
    'CreateScenarioCommand',
    'ApplyOverlayCommand',
    'RollbackVersionCommand',
    'CompareVersionsCommand',
    'RerunSpatialAssessmentCommand',
    'ApplyMcdaScoreCommand',
    'RecordAssessmentCommand',
    'GetResultsGridCommand',
    'GetComparisonSeriesCommand',
    'CreatePortfolioCommand',
    'CreateScenario',
    'ApplyOverlay',
    'RollbackVersion',
    'CompareVersions',
    'RerunSpatialAssessment',
    'ApplyMcdaScore',
    'RecordAssessment',
    'GetResultsGrid',
    'GetResultColumns',
    'GetComparisonSeries',
    'CreatePortfolio',
]
