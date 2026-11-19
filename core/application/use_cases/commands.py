# -*- coding: utf-8 -*-
"""
Command dataclasses — input DTOs for each use case.

Commands are plain data objects. They carry all information a use case needs
to execute one business operation. QGIS objects (QgsVectorLayer) are allowed
here because this is the application boundary where QGIS types are translated.

No validation lives in commands — validation is the use case's responsibility.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class CreateScenarioCommand:
    """Command for the CreateScenario use case.

    Creates a simple memory-layer assessment from features selected in QGIS.
    No spatial analysis is performed.

    Attributes:
        assessment_name: Unique name for this assessment within the project.
        description:     Human-readable description.
        project_id:      Project name prefix used for output layer naming.
        project_db_id:   Project's primary key in admin.sqlite.
        target_layer:    QgsVectorLayer — features must already be selected.
    """
    assessment_name: str
    description: str
    project_id: str
    project_db_id: int
    target_layer: object  # QgsVectorLayer — QGIS stays at this boundary


@dataclass
class ApplyOverlayCommand:
    """Command for the ApplyOverlay use case.

    Runs a versioned spatial overlay (intersection + union) on target vs.
    one or more assessment layers, storing results in SpatiaLite.

    Attributes:
        assessment_name:    Unique name for this assessment.
        description:        Human-readable description.
        project_id:         Project name prefix for output layer naming.
        project_db_id:      Project primary key in admin.sqlite.
        target_layer:       QgsVectorLayer — base spatial layer.
        assessment_layers:  list[QgsVectorLayer] — overlay inputs.
    """
    assessment_name: str
    description: str
    project_id: str
    project_db_id: int
    target_layer: object        # QgsVectorLayer
    assessment_layers: List     # list[QgsVectorLayer]
    allow_rerun: bool = False   # bypass name uniqueness check for v2+


@dataclass
class RollbackVersionCommand:
    """Command for the RollbackVersion use case.

    Moves the HEAD pointer for a scenario to a previous immutable version.
    No spatial recalculation is performed — O(1).

    Attributes:
        scenario_name:  Base scenario name (without version suffix).
        version_id:     Target spatial_versions.id to restore.
        project_db_id:  Project primary key (used to locate the SpatiaLite DB).
        group_name:     QGIS layer tree group for the restored layer.
    """
    scenario_name: str
    version_id: int
    project_db_id: int
    group_name: str = "Output Layers"


@dataclass
class CompareVersionsCommand:
    """Command for the CompareVersions use case.

    Loads two version snapshots as separate QGIS layers so the user can
    compare them visually side-by-side.

    Attributes:
        scenario_name:  Base scenario name (without version suffix).
        version_id_a:   First version to compare.
        version_id_b:   Second version to compare.
        project_db_id:  Project primary key.
        group_name:     QGIS layer tree group for the comparison layers.
    """
    scenario_name: str
    version_id_a: int
    version_id_b: int
    project_db_id: int
    group_name: str = "Comparison"


@dataclass
class RerunSpatialAssessmentCommand:
    """Command for the RerunSpatialAssessment use case.

    Re-executes the spatial overlay for an existing assessment using the
    original input layers stored in admin.sqlite, producing version n+1.

    Attributes:
        assessment_id:  PK of the assessment in admin.sqlite.
        project_id:     Project name prefix used for output layer naming.
        project_db_id:  Project primary key in admin.sqlite.
    """
    assessment_id: int
    project_id: str
    project_db_id: int


@dataclass
class ApplyMcdaScoreCommand:
    """Command for the ApplyMcdaScore use case.

    Computes and persists a weighted area-proportional MCDA score column
    in an existing SpatiaLite overlay table.

    Attributes:
        assessment_id:  PK of the assessment (source of weight config).
        table_name:     SpatiaLite table to score (e.g. proj__assess__v2).
        project_db_id:  Project primary key (used to locate the SpatiaLite DB).
    """
    assessment_id: int
    table_name: str
    project_db_id: int


@dataclass
class RecordAssessmentCommand:
    """Command for the RecordAssessment use case.

    Persists assessment metadata (output layers, provenance, MCDA config,
    weight snapshot) in admin.sqlite after a spatial run completes.

    Attributes:
        wizard_results:         dict returned by ApplyOverlay or CreateScenario.
        project_db_id:          Project primary key.
        existing_assessment_id: If set, records a new version under an existing
                                assessment instead of creating a new one.
    """
    wizard_results: dict
    project_db_id: int
    existing_assessment_id: Optional[int] = None


@dataclass
class GetResultsGridCommand:
    """Command for GetResultsGrid / GetResultColumns (read-only).

    Attributes:
        project_db_id:  Project primary key (locates the SpatiaLite DB).
        table_name:     Overlay output table (e.g. proj__assess__v2).
    """
    project_db_id: int
    table_name: str


@dataclass
class GetComparisonSeriesCommand:
    """Command for the GetComparisonSeries use case (read-only).

    Attributes:
        project_db_id:  Project primary key.
        tables:         Ordered mapping display label -> overlay table name.
        field_name:     Aggregated field to compare (see result_queries).
    """
    project_db_id: int
    tables: Dict[str, str]
    field_name: str


@dataclass
class CreatePortfolioCommand:
    """Command for the CreatePortfolio use case.

    Stores a Portfolio (LPA) configuration built on one overlay result.
    No optimisation is run — the portfolio is saved with status 'pending'.

    Attributes:
        assessment_id:  Assessment that owns the source result.
        source_table:   Overlay output table the columns come from.
        name:           Portfolio name (unique per assessment).
        col_benefits:   Column holding the benefit of each unit.
        col_cost:       Column holding the cost of each unit.
        col_priority:   Column used for prioritisation.
        budget:         Total budget (>= 0).
        buckets:        Optional budget split: [{'name': str, 'amount': float}].
    """
    assessment_id: int
    source_table: str
    name: str
    col_benefits: str
    col_cost: str
    col_priority: str
    budget: float
    buckets: List[dict] = field(default_factory=list)
