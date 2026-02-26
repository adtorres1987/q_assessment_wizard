# -*- coding: utf-8 -*-
"""
ApplyOverlay — use case for versioned spatial overlay analysis.

Business rules:
  - Assessment name must be unique within the project.
  - At least one assessment layer must be provided.
  - The project must have a valid SpatiaLite database path.

Steps:
  1. Validate inputs.
  2. Build a Scenario domain object (no QGIS imports in domain).
  3. Open SpatialEngine → migrate all layers.
  4. Run overlay per assessment layer → versioned tables ({name}__v{n}).
  5. Record version IDs.
  6. Return wizard_results dict.

Raises:
  - ValueError: name is duplicate or no assessment layers provided.
  - RuntimeError: project DB path not found.
"""

from .commands import ApplyOverlayCommand


class ApplyOverlay:
    """Use case: run a versioned spatial overlay for one assessment.

    Args:
        admin_manager: AdminManager instance — required (used to locate
                       the project SpatiaLite database and validate names).
    """

    def __init__(self, admin_manager):
        if admin_manager is None:
            raise RuntimeError(
                "ApplyOverlay requires an admin_manager instance."
            )
        self._admin_manager = admin_manager

    def execute(self, cmd: ApplyOverlayCommand) -> dict:
        """Execute the spatial overlay use case.

        Args:
            cmd: ApplyOverlayCommand with all inputs.

        Returns:
            dict: wizard_results compatible dict with keys:
                  assessment_name, target_layer, assessment_layers,
                  output_tables, description, version_ids.

        Raises:
            ValueError:   name duplicate or no assessment layers given.
            RuntimeError: project DB path not found.
        """
        self._validate(cmd)

        project_db_path = self._admin_manager.get_project_db_path(cmd.project_db_id)
        if not project_db_path:
            raise RuntimeError(
                f"Project database path not found for project_db_id={cmd.project_db_id}."
            )

        # Build assessment group: "{seq:02d}_{assessment_name}"
        # For reruns (v2+) the group already exists — new version goes in sub-group.
        seq = self._admin_manager.get_assessment_count(cmd.project_db_id)
        assessment_group = f"{seq:02d}_{cmd.assessment_name}"

        scenario = self._build_scenario(cmd)
        qgs_layer_map = self._build_layer_map(cmd)

        output_tables = []
        version_ids   = []

        from ...spatial_engine import SpatialEngine

        with SpatialEngine(project_db_path) as engine:

            # Migrate all layers → populate table_name (no INPUT_ copies in QGIS panel)
            for layer_ref in scenario['all_layers']:
                qgs_layer = qgs_layer_map[layer_ref['name']]
                layer_ref['table_name'] = engine.prepare_layer(qgs_layer)

            # Merge all assessment layers into one temporary table so the
            # overlay runs once and produces a single output.
            assessment_tables = [
                a['table_name'] for a in scenario['assessment_layers']
            ]
            if len(assessment_tables) == 1:
                overlay_assessment_table = assessment_tables[0]
                merged_temp = None
            else:
                merged_temp = engine._repo.sanitize_name(
                    f"_merged_{cmd.assessment_name}"
                )
                union_sql = " UNION ALL ".join(
                    f"SELECT geom FROM {t}" for t in assessment_tables
                )
                conn = engine._repo.project_manager.connection
                cursor = conn.cursor()

                # Get SRID from first assessment table
                cursor.execute(
                    "SELECT srid FROM geometry_columns "
                    "WHERE f_table_name = ? AND f_geometry_column = 'geom'",
                    (assessment_tables[0],)
                )
                row = cursor.fetchone()
                srid = row[0] if row else 4326

                conn.execute(f"DROP TABLE IF EXISTS {merged_temp}")
                conn.execute(
                    f"CREATE TABLE {merged_temp} AS {union_sql}"
                )
                # Register geometry so validate_geometry_compatibility finds it
                cursor.execute(
                    f"SELECT RecoverGeometryColumn("
                    f"'{merged_temp}', 'geom', {srid}, 'MULTIPOLYGON', 'XY')"
                )
                cursor.close()
                conn.commit()
                overlay_assessment_table = merged_temp

            # Single overlay → single output
            base_name = f"{cmd.project_id}__{cmd.assessment_name}"
            existing = engine._repo.get_versions(
                engine._repo.sanitize_name(base_name)
            )
            group_name = assessment_group
            if existing:
                next_v = len(existing) + 1
                display_name = f"Result_v{next_v}"
            else:
                display_name = f"OUTPUT_{cmd.assessment_name}"

            result = engine.overlay(
                scenario['target_layer']['table_name'],
                overlay_assessment_table,
                base_name,
                group_name=group_name,
                layer_display_name=display_name,
            )
            output_tables.append(result['table'])
            version_ids.append(result['version_id'])

            # Drop temporary merged table
            if merged_temp:
                conn = engine._repo.project_manager.connection
                conn.execute(f"DROP TABLE IF EXISTS {merged_temp}")
                conn.commit()

        return {
            'assessment_name':    cmd.assessment_name,
            'target_layer':       cmd.target_layer.name(),
            'assessment_layers':  [al.name() for al in cmd.assessment_layers],
            'output_tables':      output_tables,
            'description':        cmd.description,
            'version_ids':        version_ids,
        }

    # ------------------------------------------------------------------ #
    #  Private helpers
    # ------------------------------------------------------------------ #

    def _validate(self, cmd: ApplyOverlayCommand):
        if not cmd.assessment_layers:
            raise ValueError(
                "ApplyOverlay requires at least one assessment layer."
            )
        if not cmd.allow_rerun and self._admin_manager.assessment_name_exists(
                cmd.project_db_id, cmd.assessment_name):
            raise ValueError(
                f"Assessment name '{cmd.assessment_name}' already exists "
                f"in this project."
            )

    def _build_scenario(self, cmd: ApplyOverlayCommand) -> dict:
        """Build a lightweight scenario dict (avoids circular imports with domain)."""
        target = {'name': cmd.target_layer.name(), 'table_name': ''}
        assessments = [
            {'name': al.name(), 'table_name': ''}
            for al in cmd.assessment_layers
        ]
        all_layers = [target] + assessments
        return {
            'target_layer':     target,
            'assessment_layers': assessments,
            'all_layers':       all_layers,
        }

    def _build_layer_map(self, cmd: ApplyOverlayCommand) -> dict:
        """Map layer name → QgsVectorLayer for fast lookup during migration."""
        layer_map = {cmd.target_layer.name(): cmd.target_layer}
        layer_map.update({al.name(): al for al in cmd.assessment_layers})
        return layer_map

    @staticmethod
    def _make_base_name(project_id, assessment_name, assessment_layer_name,
                        total_count) -> str:
        """Compute the base table name for one overlay run."""
        if total_count == 1:
            return f"{project_id}__{assessment_name}"
        safe = assessment_layer_name.replace(' ', '_')
        return f"{project_id}__{assessment_name}_{safe}"
