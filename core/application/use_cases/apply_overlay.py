# -*- coding: utf-8 -*-
"""
ApplyOverlay — use case for versioned spatial overlay analysis.

Business rules:
  - Assessment name must be unique within the project (unless allow_rerun=True).
  - At least one assessment layer must be provided.
  - The project must have a valid SpatiaLite database path.

Steps:
  1. Validate inputs via MetadataRepositoryPort.
  2. Build a Scenario domain object.
  3. Open SpatialEngine via factory → migrate all layers.
  4. Run cumulative overlay (each assessment layer applied iteratively).
  5. Return wizard_results dict.

Raises:
  - ValueError: name is duplicate or no assessment layers provided.
  - RuntimeError: project DB path not found.
"""

from ..ports import MetadataRepositoryPort
from .commands import ApplyOverlayCommand
from ...domain import Scenario, LayerRef, LayerRole


class ApplyOverlay:
    """Use case: run a versioned spatial overlay for one assessment.

    Args:
        metadata_repo:        MetadataRepositoryPort implementation.
        spatial_engine_class: The SpatialEngine class — used as a context
                              manager factory: ``spatial_engine_class(db_path)``.
    """

    def __init__(self, metadata_repo: MetadataRepositoryPort,
                 spatial_engine_class):
        if metadata_repo is None:
            raise RuntimeError("ApplyOverlay requires a metadata_repo instance.")
        self._meta = metadata_repo
        self._engine_cls = spatial_engine_class

    def execute(self, cmd: ApplyOverlayCommand) -> dict:
        """Execute the spatial overlay use case.

        Returns:
            dict: {assessment_name, target_layer, assessment_layers,
                   output_tables, description, version_ids}

        Raises:
            ValueError:   name duplicate or no assessment layers given.
            RuntimeError: project DB path not found.
        """
        self._validate(cmd)

        project_db_path = self._meta.get_project_db_path(cmd.project_db_id)
        if not project_db_path:
            raise RuntimeError(
                f"Project database path not found for "
                f"project_db_id={cmd.project_db_id}."
            )

        seq = self._meta.get_assessment_count(cmd.project_db_id)
        assessment_group = f"{seq:02d}_{cmd.assessment_name}"

        scenario = Scenario(
            project_id=cmd.project_db_id,
            name=cmd.assessment_name,
            description=cmd.description,
            target_layer=LayerRef(
                name=cmd.target_layer.name(), role=LayerRole.TARGET
            ),
            assessment_layers=[
                LayerRef(name=al.name(), role=LayerRole.ASSESSMENT)
                for al in cmd.assessment_layers
            ],
        )

        qgs_layer_map = {cmd.target_layer.name(): cmd.target_layer}
        qgs_layer_map.update({al.name(): al for al in cmd.assessment_layers})

        output_tables = []
        version_ids   = []

        with self._engine_cls(project_db_path) as engine:

            # Migrate all layers → populate table_name on each LayerRef
            for layer_ref in scenario.all_layers:
                qgs_layer = qgs_layer_map[layer_ref.name]
                layer_ref.table_name = engine.prepare_layer(qgs_layer)

            # Cumulative overlay — apply each assessment layer iteratively
            assessment_tables = [lr.table_name for lr in scenario.assessment_layers]
            base_name = f"{cmd.project_id}__{cmd.assessment_name}"
            existing = engine.get_versions(engine.sanitize_name(base_name))
            display_name = (
                f"Result_v{len(existing) + 1}" if existing
                else f"OUTPUT_{cmd.assessment_name}"
            )

            result = engine.cumulative_overlay(
                scenario.target_layer.table_name,
                assessment_tables,
                base_name,
                group_name=assessment_group,
                layer_display_name=display_name,
            )
            output_tables.append(result['table'])
            version_ids.append(result['version_id'])
            scenario.add_output_table(result['table'])

        return {
            'assessment_name':   cmd.assessment_name,
            'target_layer':      cmd.target_layer.name(),
            'assessment_layers': [al.name() for al in cmd.assessment_layers],
            'output_tables':     output_tables,
            'description':       cmd.description,
            'version_ids':       version_ids,
        }

    # ------------------------------------------------------------------ #
    #  Private helpers
    # ------------------------------------------------------------------ #

    def _validate(self, cmd: ApplyOverlayCommand):
        if not cmd.assessment_layers:
            raise ValueError(
                "ApplyOverlay requires at least one assessment layer."
            )
        if not cmd.allow_rerun and self._meta.assessment_name_exists(
                cmd.project_db_id, cmd.assessment_name):
            raise ValueError(
                f"Assessment name '{cmd.assessment_name}' already exists "
                f"in this project."
            )
