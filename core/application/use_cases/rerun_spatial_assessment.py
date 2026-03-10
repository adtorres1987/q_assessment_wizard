# -*- coding: utf-8 -*-
"""
RerunSpatialAssessment — use case for creating a new overlay version.

Business rules:
  - The assessment must exist and be spatial (have input layers).
  - The project must have a valid SpatiaLite database path.
  - Output table name follows: {project_id}__{assessment_name}__v{n+1}

Steps:
  1. Load assessment metadata + input layers from MetadataRepositoryPort.
  2. Compute assessment group name ({seq:02d}_{name}).
  3. Open SpatialEngine via factory.
  4. Merge input layers if more than one.
  5. Run overlay → new versioned table.
  6. Record output layers, provenance, weight snapshot in metadata.

Raises:
  - ValueError:   no input layers (simple assessment) or assessment not found.
  - RuntimeError: project DB path not found.
"""

import re

from .commands import RerunSpatialAssessmentCommand
from ..ports import MetadataRepositoryPort, SpatialEnginePort


class RerunSpatialAssessment:
    """Use case: re-run spatial overlay for an existing assessment (new version).

    Args:
        metadata_repo:        MetadataRepositoryPort implementation.
        spatial_engine_class: The SpatialEngine class (used as context manager
                              factory via ``spatial_engine_class(db_path)``).
    """

    def __init__(self, metadata_repo: MetadataRepositoryPort,
                 spatial_engine_class):
        self._meta = metadata_repo
        self._engine_cls = spatial_engine_class

    def execute(self, cmd: RerunSpatialAssessmentCommand) -> dict:
        """Execute the re-run.

        Returns:
            dict: {assessment_name, output_tables, version_ids}

        Raises:
            ValueError:   assessment not found or no input layers.
            RuntimeError: project DB path not found.
        """
        assessment = self._meta.get_assessment(cmd.assessment_id)
        if not assessment:
            raise ValueError(
                f"Assessment {cmd.assessment_id} not found in metadata."
            )

        input_layers = self._meta.get_assessment_layers(
            cmd.assessment_id, layer_type='input'
        )
        if not input_layers:
            raise ValueError(
                "Only spatial assessments (with assessment layers) "
                "support versioning."
            )

        project_db_path = self._meta.get_project_db_path(cmd.project_db_id)
        if not project_db_path:
            raise RuntimeError(
                f"Project database path not found for "
                f"project_db_id={cmd.project_db_id}."
            )

        assessment_name = assessment['name']

        # Determine group: "{seq:02d}_{assessment_name}"
        all_assessments = self._meta.get_assessments_for_project(cmd.project_db_id)
        seq = next(
            (i + 1 for i, a in enumerate(all_assessments)
             if a['id'] == cmd.assessment_id),
            1
        )
        assessment_group = f"{seq:02d}_{assessment_name}"

        output_tables = []
        version_ids = []

        with self._engine_cls(project_db_path) as engine:
            assessment_tables = [
                engine.sanitize_name(al['layer_name'])
                for al in input_layers
            ]

            base_name = f"{cmd.project_id}__{assessment_name}"
            existing = engine.get_versions(engine.sanitize_name(base_name))
            next_v = len(existing) + 1

            result = engine.cumulative_overlay(
                engine.sanitize_name(assessment['target_layer']),
                assessment_tables,
                base_name,
                group_name=assessment_group,
                layer_display_name=f"Result_v{next_v}",
            )
            output_tables.append(result['table'])
            version_ids.append(result['version_id'])

        # Record metadata
        for table_name in output_tables:
            self._meta.add_assessment_layer(cmd.assessment_id, table_name, 'output')
            self._meta.set_layer_visibility(cmd.assessment_id, table_name, True)

        self._record_provenance(
            assessment_id=cmd.assessment_id,
            output_tables=output_tables,
            target_layer_name=assessment['target_layer'],
            assessment_layer_names=[al['layer_name'] for al in input_layers],
            run_name=f"Run v{next_v}",
        )

        for table_name in output_tables:
            v_match = re.search(r'__v(\d+)$', table_name)
            v_num = int(v_match.group(1)) if v_match else next_v
            self._meta.snapshot_analysis_for_version(
                cmd.assessment_id, table_name, v_num
            )

        return {
            'assessment_name': assessment_name,
            'output_tables': output_tables,
            'version_ids': version_ids,
        }

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
