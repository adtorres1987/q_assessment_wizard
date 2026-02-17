# -*- coding: utf-8 -*-
"""
Application layer — use cases for the Assessment Wizard plugin.

Phase 4 of Clean Architecture refactoring.

Each use case in this layer:
  - Receives a Command dataclass (input DTO)
  - Validates business rules
  - Orchestrates domain objects and infrastructure (SpatialEngine, admin_manager)
  - Returns a plain dict result
  - Raises ValueError / RuntimeError on failure (NO QMessageBox)

The UI / AssessmentExecutor catches exceptions and shows QMessageBox.

Layer position:
    UI (dialog)
      ↓ QgsVectorLayer + primitive types
    AssessmentExecutor (thin facade — handles QMessageBox, creates commands)
      ↓ Command dataclasses
    Use Cases (this package)
      ↓ domain objects + SpatialEngine
    Infrastructure (SpatialEngine, ProjectManager, AdminManager)
"""

from .use_cases import (
    CreateScenarioCommand,
    ApplyOverlayCommand,
    RollbackVersionCommand,
    CompareVersionsCommand,
    CreateScenario,
    ApplyOverlay,
    RollbackVersion,
    CompareVersions,
)

__all__ = [
    'CreateScenarioCommand',
    'ApplyOverlayCommand',
    'RollbackVersionCommand',
    'CompareVersionsCommand',
    'CreateScenario',
    'ApplyOverlay',
    'RollbackVersion',
    'CompareVersions',
]
