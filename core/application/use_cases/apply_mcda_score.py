# -*- coding: utf-8 -*-
"""
ApplyMcdaScore — use case for computing weighted area-proportional MCDA scores.

Business rules:
  - An analysis config (weights) must exist for the assessment.
  - The table must exist in the project SpatiaLite database.
  - MCDA_SCORE = layer_weight * (area_i / total_area_in_table)

Raises:
  - ValueError: no MCDA config found, or project DB path not found.
  - RuntimeError: SQL error during scoring.
"""

import json
import re

from .commands import ApplyMcdaScoreCommand
from ..ports import MetadataRepositoryPort


class ApplyMcdaScore:
    """Use case: compute and persist a weighted MCDA score column.

    Args:
        metadata_repo:        MetadataRepositoryPort implementation.
        spatial_engine_class: The SpatialEngine class (context manager factory).
    """

    def __init__(self, metadata_repo: MetadataRepositoryPort,
                 spatial_engine_class):
        self._meta = metadata_repo
        self._engine_cls = spatial_engine_class

    def execute(self, cmd: ApplyMcdaScoreCommand) -> bool:
        """Execute MCDA scoring.

        Returns:
            bool: True on success.

        Raises:
            ValueError:   no MCDA config or project DB not found.
            RuntimeError: SQL error.
        """
        config = self._meta.get_analysis_config(cmd.assessment_id)
        if not config:
            raise ValueError(
                "No MCDA configuration found for this assessment.\n"
                "Run the assessment at least once to auto-create a default config."
            )

        weights = json.loads(config.get('weights_json') or '{}')
        score_column = config.get('score_column', 'MCDA_SCORE')
        matched_weight = self._resolve_weight(cmd.table_name, weights)

        project_db_path = self._meta.get_project_db_path(cmd.project_db_id)
        if not project_db_path:
            raise ValueError("Project database path not found.")

        with self._engine_cls(project_db_path) as engine:
            engine.score_table(cmd.table_name, score_column, matched_weight)

        # Refresh any QGIS layer currently displaying this table
        try:
            from qgis.core import QgsProject
            for layer in QgsProject.instance().mapLayers().values():
                if cmd.table_name in (layer.name() or ''):
                    layer.reload()
        except Exception:
            pass

        return True

    @staticmethod
    def _resolve_weight(table_name: str, weights: dict) -> float:
        """Return the weight that applies to this table.

        Tries to match the table name suffix against layer names; falls back
        to the first (and only) weight for single-layer assessments.
        """
        base_no_ver = re.sub(r'__v\d+$', '', table_name)
        for layer_name, w in weights.items():
            safe = layer_name.replace(' ', '_')
            if base_no_ver.endswith(f'_{safe}'):
                return w
        return next(iter(weights.values()), 1.0)
