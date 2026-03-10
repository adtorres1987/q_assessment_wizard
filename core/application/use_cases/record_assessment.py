# -*- coding: utf-8 -*-
"""
RecordAssessment — use case for persisting assessment metadata after a spatial run.

Unifies the logic previously split across:
  - AssessmentExecutor.record_assessment()    (first run)
  - AssessmentExecutor.record_new_version()   (re-runs)

Business rules:
  - If existing_assessment_id is None → create a new assessment record.
  - If existing_assessment_id is set  → add output layers under the existing record.
  - Always: record output layer visibility, provenance, task_details,
            MCDA config (equal weights on first run), and weight snapshot.

Returns:
    int: the assessment_id (new or existing).
"""

import re

from .commands import RecordAssessmentCommand
from ..ports import MetadataRepositoryPort


class RecordAssessment:
    """Use case: persist assessment metadata in admin.sqlite.

    Args:
        metadata_repo: MetadataRepositoryPort implementation.
    """

    def __init__(self, metadata_repo: MetadataRepositoryPort):
        self._meta = metadata_repo

    def execute(self, cmd: RecordAssessmentCommand) -> int:
        """Execute metadata recording.

        Returns:
            int: assessment_id.
        """
        results = cmd.wizard_results

        if cmd.existing_assessment_id is None:
            assessment_id = self._meta.create_assessment(
                project_id=cmd.project_db_id,
                name=results.get('assessment_name', ''),
                description=results.get('description', ''),
                target_layer=results.get('target_layer', ''),
                assessment_layers=results.get('assessment_layers', []),
                output_tables=results.get('output_tables', []),
            )
        else:
            assessment_id = cmd.existing_assessment_id

        for table_name in results.get('output_tables', []):
            if cmd.existing_assessment_id is not None:
                self._meta.add_assessment_layer(assessment_id, table_name, 'output')
            self._meta.set_layer_visibility(assessment_id, table_name, True)

        assessment_layers = results.get('assessment_layers', [])
        output_tables = results.get('output_tables', [])

        if assessment_layers:
            v = self._parse_version(output_tables)
            self._record_provenance(
                assessment_id=assessment_id,
                output_tables=output_tables,
                target_layer_name=results.get('target_layer', ''),
                assessment_layer_names=assessment_layers,
                run_name=f"Run v{v}",
            )

        if assessment_layers and cmd.existing_assessment_id is None:
            # Auto-create MCDA config with equal weights on first spatial run
            n = len(assessment_layers)
            weights = (
                {name: round(1.0 / n, 4) for name in assessment_layers}
                if n else {}
            )
            self._meta.create_analysis_config(assessment_id, weights=weights)
        elif assessment_layers and cmd.existing_assessment_id is not None:
            # Ensure config exists (may have been created on first run)
            if not self._meta.get_analysis_config(assessment_id):
                input_layers = self._meta.get_assessment_layers(assessment_id, 'input')
                n = len(input_layers)
                weights = (
                    {il['layer_name']: round(1.0 / n, 4) for il in input_layers}
                    if n else {}
                )
                self._meta.create_analysis_config(assessment_id, weights=weights)

        for table_name in output_tables:
            v_match = re.search(r'__v(\d+)$', table_name)
            v_num = int(v_match.group(1)) if v_match else 1
            self._meta.snapshot_analysis_for_version(assessment_id, table_name, v_num)

        return assessment_id

    # ------------------------------------------------------------------ #
    #  Private helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_version(output_tables: list) -> int:
        if output_tables:
            m = re.search(r'__v(\d+)$', output_tables[0])
            if m:
                return int(m.group(1))
        return 1

    def _record_provenance(self, assessment_id, output_tables,
                           target_layer_name, assessment_layer_names,
                           run_name):
        try:
            provenance_id = self._meta.create_provenance(
                assessment_id=assessment_id,
                name=run_name,
                description="Base spatial analysis: union + intersection",
            )
            self._meta.add_task(
                provenance_id=provenance_id,
                step_order=1,
                operation="union+intersect",
                category="spatial_analysis",
                engine_type="spatialite",
                input_tables=[target_layer_name] + assessment_layer_names,
                output_tables=output_tables,
                added_to_map=True,
            )
        except Exception as e:
            print(f"Warning: Could not record provenance: {e}")
