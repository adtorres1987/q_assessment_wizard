# -*- coding: utf-8 -*-
"""
AssessmentExecutor — thin UI facade over the Application Layer use cases.

Phase 4 (Clean Architecture): this class is no longer an orchestrator.
All business logic lives in core/application/use_cases/.

Responsibilities:
  - Build Command dataclasses from raw QGIS inputs.
  - Call the appropriate use case.
  - Catch ValueError / RuntimeError and show QMessageBox to the user.
  - Return wizard_results dicts upward to the dialog.

UI layer → AssessmentExecutor (this file)
              ↓ Command dataclasses
           Use Cases (core/application/use_cases/)
              ↓ SpatialEngine / AdminManager
           Infrastructure
"""

import re
import json

from qgis.PyQt.QtWidgets import QMessageBox

from .core.application import (
    CreateScenarioCommand, CreateScenario,
    ApplyOverlayCommand,   ApplyOverlay,
    RollbackVersionCommand, RollbackVersion,
    CompareVersionsCommand, CompareVersions,
)


class AssessmentExecutor:
    """Thin facade: translates UI events into use-case commands."""

    def __init__(self, project_id, admin_manager, project_db_id):
        """
        Args:
            project_id:     str — project name prefix for output layer naming
            admin_manager:  AdminManager instance
            project_db_id:  int — project database ID in admin.sqlite
        """
        self.project_id    = project_id
        self.admin_manager = admin_manager
        self.project_db_id = project_db_id

    # ------------------------------------------------------------------ #
    #  Validation helper (used by the dialog before execution)
    # ------------------------------------------------------------------ #

    def validate_assessment_name(self, assessment_name):
        """Return True if the name is available (not a duplicate)."""
        if self.admin_manager and self.project_db_id is not None:
            return not self.admin_manager.assessment_name_exists(
                self.project_db_id, assessment_name
            )
        return True

    # ------------------------------------------------------------------ #
    #  Case 1: simple (memory) assessment
    # ------------------------------------------------------------------ #

    def execute_simple_assessment(self, assessment_name, target_layer,
                                   description, parent_widget=None):
        """Create a memory layer from selected features (no spatial analysis).

        Delegates to: CreateScenario use case.

        Returns:
            dict or None: wizard_results, or None on failure.
        """
        cmd = CreateScenarioCommand(
            assessment_name=assessment_name,
            description=description,
            project_id=self.project_id,
            project_db_id=self.project_db_id,
            target_layer=target_layer,
        )
        try:
            result = CreateScenario(self.admin_manager).execute(cmd)
        except ValueError as e:
            QMessageBox.warning(parent_widget, "Cannot Create Assessment", str(e))
            return None

        layer_name = result['output_tables'][0] if result['output_tables'] else assessment_name
        QMessageBox.information(
            parent_widget,
            "Layer Created",
            f"Layer '{layer_name}' created successfully!\n\n"
            f"Features: {len(list(target_layer.selectedFeatures()))}"
        )
        return result

    # ------------------------------------------------------------------ #
    #  Case 2: spatial assessment (with overlay analysis)
    # ------------------------------------------------------------------ #

    def execute_spatial_assessment(self, assessment_name, target_layer,
                                    assessment_layers, description,
                                    allow_rerun=False, parent_widget=None):
        """Run spatial overlay analysis and produce SpatiaLite base tables.

        Delegates to: ApplyOverlay use case.

        Args:
            allow_rerun: If True, bypass name uniqueness check (for v2+).

        Returns:
            dict or None: wizard_results, or None on failure.
        """
        cmd = ApplyOverlayCommand(
            assessment_name=assessment_name,
            description=description,
            project_id=self.project_id,
            project_db_id=self.project_db_id,
            target_layer=target_layer,
            assessment_layers=assessment_layers,
            allow_rerun=allow_rerun,
        )
        try:
            result = ApplyOverlay(self.admin_manager).execute(cmd)
        except (ValueError, RuntimeError) as e:
            QMessageBox.critical(parent_widget, "Assessment Failed", str(e))
            return None

        layer_names = "\n• ".join(result['output_tables'])
        QMessageBox.information(
            parent_widget,
            "Assessment Complete",
            f"Assessment created successfully!\n\n"
            f"Base layer(s):\n• {layer_names}"
        )
        return result

    # ------------------------------------------------------------------ #
    #  Case 2b: re-run spatial assessment (new version)
    # ------------------------------------------------------------------ #

    def rerun_spatial_assessment(self, assessment_id, parent_widget=None):
        """Re-run overlay for an existing assessment, creating version n+1.

        Uses the stored target_layer and assessment_layers from admin.sqlite
        to re-execute the overlay on SpatiaLite tables that already exist.

        Returns:
            dict or None: { output_tables, version_ids, assessment_name }
                          or None on failure.
        """
        assessment = self.admin_manager.get_assessment(assessment_id)
        if not assessment:
            QMessageBox.warning(parent_widget, "Error",
                                "Assessment not found in metadata.")
            return None

        input_layers = self.admin_manager.get_assessment_layers(
            assessment_id, layer_type='input'
        )
        if not input_layers:
            QMessageBox.warning(parent_widget, "Not Supported",
                                "Only spatial assessments (with assessment layers) "
                                "support versioning.")
            return None

        project_db_path = self.admin_manager.get_project_db_path(self.project_db_id)
        if not project_db_path:
            QMessageBox.critical(parent_widget, "Error",
                                 "Project database path not found.")
            return None

        target_layer_name = assessment['target_layer']
        assessment_name = assessment['name']
        output_tables = []
        version_ids = []

        # Resolve assessment group: "{seq:02d}_{assessment_name}"
        # seq = position of this assessment among all project assessments
        all_assessments = self.admin_manager.get_assessments_for_project(
            self.project_db_id
        )
        seq = next(
            (i + 1 for i, a in enumerate(all_assessments)
             if a['id'] == assessment_id),
            1
        )
        assessment_group = f"{seq:02d}_{assessment_name}"

        try:
            from .core.spatial_engine import SpatialEngine
            with SpatialEngine(project_db_path) as engine:
                target_table = engine._repo.sanitize_name(target_layer_name)

                # Build assessment table list (same as apply_overlay.py)
                assessment_tables = [
                    engine._repo.sanitize_name(al['layer_name'])
                    for al in input_layers
                ]

                # Merge multiple layers → single overlay (mirrors apply_overlay.py)
                merged_temp = None
                if len(assessment_tables) == 1:
                    overlay_assessment_table = assessment_tables[0]
                else:
                    merged_temp = engine._repo.sanitize_name(
                        f"_merged_{assessment_name}"
                    )
                    union_sql = " UNION ALL ".join(
                        f"SELECT geom FROM {t}" for t in assessment_tables
                    )
                    conn = engine._repo.project_manager.connection
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT srid FROM geometry_columns "
                        "WHERE f_table_name = ? AND f_geometry_column = 'geom'",
                        (assessment_tables[0],)
                    )
                    row = cursor.fetchone()
                    srid = row[0] if row else 4326
                    conn.execute(f"DROP TABLE IF EXISTS {merged_temp}")
                    conn.execute(f"CREATE TABLE {merged_temp} AS {union_sql}")
                    cursor.execute(
                        f"SELECT RecoverGeometryColumn("
                        f"'{merged_temp}', 'geom', {srid}, 'MULTIPOLYGON', 'XY')"
                    )
                    cursor.close()
                    conn.commit()
                    overlay_assessment_table = merged_temp

                # Single base_name — same pattern as apply_overlay.py
                base_name = f"{self.project_id}__{assessment_name}"

                existing = engine._repo.get_versions(
                    engine._repo.sanitize_name(base_name)
                )
                next_v = len(existing) + 1
                group_name = assessment_group
                display_name = f"Result_v{next_v}"

                result = engine.overlay(
                    target_table, overlay_assessment_table, base_name,
                    group_name=group_name,
                    layer_display_name=display_name,
                )
                output_tables.append(result['table'])
                version_ids.append(result['version_id'])

                if merged_temp:
                    conn = engine._repo.project_manager.connection
                    conn.execute(f"DROP TABLE IF EXISTS {merged_temp}")
                    conn.commit()

        except (ValueError, RuntimeError) as e:
            QMessageBox.critical(parent_widget, "New Version Failed", str(e))
            return None

        # Record new output layers in admin.sqlite
        for table_name in output_tables:
            self.admin_manager.add_assessment_layer(
                assessment_id, table_name, 'output'
            )
            self.admin_manager.set_layer_visibility(assessment_id, table_name, True)

        # Record provenance
        self._record_provenance(
            assessment_id=assessment_id,
            output_tables=output_tables,
            target_layer_name=target_layer_name,
            assessment_layer_names=[al['layer_name'] for al in input_layers],
            run_name=f"Run v{next_v}"
        )

        # Snapshot weights for this new version (preserves history)
        for table_name in output_tables:
            v_match = re.search(r'__v(\d+)$', table_name)
            v_num = int(v_match.group(1)) if v_match else next_v
            self.admin_manager.snapshot_analysis_for_version(
                assessment_id, table_name, v_num
            )

        layer_names = "\n• ".join(output_tables)
        QMessageBox.information(
            parent_widget,
            "New Version Created",
            f"New version created successfully!\n\n"
            f"Table(s):\n• {layer_names}"
        )

        return {
            'assessment_name': assessment_name,
            'output_tables': output_tables,
            'version_ids': version_ids,
        }

    # ------------------------------------------------------------------ #
    #  Case 3: rollback to a previous version
    # ------------------------------------------------------------------ #

    def rollback_to_version(self, scenario_name, version_id,
                            parent_widget=None):
        """Restore HEAD to a previous version — O(1).

        Delegates to: RollbackVersion use case.

        Returns:
            dict or None: { table, version_id, layer }, or None on failure.
        """
        cmd = RollbackVersionCommand(
            scenario_name=scenario_name,
            version_id=version_id,
            project_db_id=self.project_db_id,
        )
        try:
            result = RollbackVersion(self.admin_manager).execute(cmd)
        except (ValueError, RuntimeError) as e:
            QMessageBox.critical(parent_widget, "Rollback Failed", str(e))
            return None

        QMessageBox.information(
            parent_widget,
            "Rollback Complete",
            f"Restored to version {version_id}.\n"
            f"Table: {result['table']}"
        )
        return result

    # ------------------------------------------------------------------ #
    #  Case 4: compare two versions side-by-side
    # ------------------------------------------------------------------ #

    def compare_versions(self, scenario_name, version_id_a, version_id_b,
                         parent_widget=None):
        """Load two version snapshots as QGIS layers for visual comparison.

        Delegates to: CompareVersions use case.

        Returns:
            dict or None: { layer_a, layer_b, version_id_a, version_id_b },
                          or None on failure.
        """
        cmd = CompareVersionsCommand(
            scenario_name=scenario_name,
            version_id_a=version_id_a,
            version_id_b=version_id_b,
            project_db_id=self.project_db_id,
        )
        try:
            result = CompareVersions(self.admin_manager).execute(cmd)
        except (ValueError, RuntimeError) as e:
            QMessageBox.critical(parent_widget, "Compare Failed", str(e))
            return None

        return result

    # ------------------------------------------------------------------ #
    #  Metadata recording (delegates to AdminManager directly)
    # ------------------------------------------------------------------ #

    def record_new_version(self, existing_assessment_id, wizard_results):
        """Record new output layers + provenance for an existing assessment (v2+).

        Does NOT create a new assessment record — only adds output layers and
        provenance under the existing assessment_id.

        Args:
            existing_assessment_id: Primary key of the existing assessment.
            wizard_results:         dict with output_tables, assessment_layers, etc.
        """
        if not (self.admin_manager and existing_assessment_id):
            return
        try:
            for table_name in wizard_results.get('output_tables', []):
                self.admin_manager.add_assessment_layer(
                    existing_assessment_id, table_name, 'output'
                )
                self.admin_manager.set_layer_visibility(
                    existing_assessment_id, table_name, True
                )

            if wizard_results.get('assessment_layers'):
                _tables = wizard_results.get('output_tables', [])
                _v = int(re.search(r'__v(\d+)$', _tables[0]).group(1)) if _tables and re.search(r'__v(\d+)$', _tables[0]) else 1
                self._record_provenance(
                    assessment_id=existing_assessment_id,
                    output_tables=_tables,
                    target_layer_name=wizard_results.get('target_layer', ''),
                    assessment_layer_names=wizard_results.get('assessment_layers', []),
                    run_name=f"Run v{_v}"
                )

            # Auto-create MCDA config with equal weights if not yet configured
            if not self.admin_manager.get_analysis_config(existing_assessment_id):
                input_layers = self.admin_manager.get_assessment_layers(
                    existing_assessment_id, 'input'
                )
                n = len(input_layers)
                weights = (
                    {il['layer_name']: round(1.0 / n, 4) for il in input_layers}
                    if n else {}
                )
                self.admin_manager.create_analysis_config(
                    existing_assessment_id, weights=weights
                )

            # Snapshot the weights used for each new output table (preserves history)
            for table_name in wizard_results.get('output_tables', []):
                v_match = re.search(r'__v(\d+)$', table_name)
                v_num = int(v_match.group(1)) if v_match else 1
                self.admin_manager.snapshot_analysis_for_version(
                    existing_assessment_id, table_name, v_num
                )

        except Exception as e:
            print(f"Warning: Could not record new version metadata: {e}")

    def record_assessment(self, wizard_results):
        """Persist assessment metadata to admin.sqlite.

        Creates the assessment record, sets initial layer visibility, and —
        for spatial assessments — records provenance + task_details.

        Args:
            wizard_results: dict with assessment_name, target_layer, etc.

        Returns:
            int or None: new assessment_id, or None on failure.
        """
        if not (self.admin_manager and self.project_db_id is not None):
            return None

        try:
            assessment_id = self.admin_manager.create_assessment(
                project_id=self.project_db_id,
                name=wizard_results.get('assessment_name', ''),
                description=wizard_results.get('description', ''),
                target_layer=wizard_results.get('target_layer', ''),
                assessment_layers=wizard_results.get('assessment_layers', []),
                output_tables=wizard_results.get('output_tables', [])
            )

            for table_name in wizard_results.get('output_tables', []):
                self.admin_manager.set_layer_visibility(assessment_id, table_name, True)

            if wizard_results.get('assessment_layers'):
                _tables = wizard_results.get('output_tables', [])
                _v = int(re.search(r'__v(\d+)$', _tables[0]).group(1)) if _tables and re.search(r'__v(\d+)$', _tables[0]) else 1
                self._record_provenance(
                    assessment_id=assessment_id,
                    output_tables=_tables,
                    target_layer_name=wizard_results.get('target_layer', ''),
                    assessment_layer_names=wizard_results.get('assessment_layers', []),
                    run_name=f"Run v{_v}"
                )

                # Auto-create MCDA config with equal weights on first spatial assessment
                assessment_layer_names = wizard_results.get('assessment_layers', [])
                n = len(assessment_layer_names)
                weights = (
                    {name: round(1.0 / n, 4) for name in assessment_layer_names}
                    if n else {}
                )
                self.admin_manager.create_analysis_config(assessment_id, weights=weights)

                # Snapshot the weights used for each output table (preserves history)
                for table_name in wizard_results.get('output_tables', []):
                    v_match = re.search(r'__v(\d+)$', table_name)
                    v_num = int(v_match.group(1)) if v_match else 1
                    self.admin_manager.snapshot_analysis_for_version(
                        assessment_id, table_name, v_num
                    )

            return assessment_id

        except Exception as e:
            print(f"Warning: Could not record assessment in metadata: {e}")
            return None

    def _record_provenance(self, assessment_id, output_tables,
                           target_layer_name, assessment_layer_names,
                           run_name="Run v1"):
        """Create provenance + task_details entries in admin.sqlite."""
        if not self.admin_manager:
            return
        operation = "union+intersect"
        try:
            provenance_id = self.admin_manager.create_provenance(
                assessment_id=assessment_id,
                name=run_name,
                description="Base spatial analysis: union + intersection"
            )
            self.admin_manager.add_task(
                provenance_id=provenance_id,
                step_order=1,
                operation=operation,
                category="spatial_analysis",
                engine_type="spatialite",
                input_tables=[target_layer_name] + assessment_layer_names,
                output_tables=output_tables,
                added_to_map=True
            )
        except Exception as e:
            print(f"Warning: Could not record provenance: {e}")

    # ------------------------------------------------------------------ #
    #  MCDA Scoring
    # ------------------------------------------------------------------ #

    def apply_mcda_score(self, assessment_id, table_name, parent_widget=None):
        """Apply weighted area-proportional MCDA score to a SpatiaLite overlay table.

        Adds (or updates) a MCDA_SCORE column computed as:
            MCDA_SCORE_i = layer_weight * (area_i / total_area_in_table)

        Args:
            assessment_id: int — used to look up MCDA config and layer weights
            table_name:    str — the overlay result table (e.g. proj__Assess__v2)
            parent_widget: QWidget — parent for QMessageBox dialogs
        Returns:
            bool: True on success, False on failure
        """
        from qgis.core import QgsProject

        config = self.admin_manager.get_analysis_config(assessment_id)
        if not config:
            QMessageBox.warning(
                parent_widget, "No MCDA Config",
                "No MCDA configuration found for this assessment.\n"
                "Run the assessment at least once to auto-create a default config."
            )
            return False

        weights      = json.loads(config.get('weights_json') or '{}')
        score_column = config.get('score_column', 'MCDA_SCORE')

        # Determine which layer's weight applies to this table.
        # _make_base_name produces:
        #   single layer → proj__AssessmentName
        #   multi layer  → proj__AssessmentName_LayerName
        # After versioning:  proj__AssessmentName[_LayerName]__v{n}
        base_no_ver    = re.sub(r'__v\d+$', '', table_name)
        matched_weight = None
        for layer_name, w in weights.items():
            safe = layer_name.replace(' ', '_')
            if base_no_ver.endswith(f'_{safe}'):
                matched_weight = w
                break
        if matched_weight is None:
            # Single-assessment-layer: use the first (and only) weight
            matched_weight = next(iter(weights.values()), 1.0)

        project_db_path = self.admin_manager.get_project_db_path(self.project_db_id)
        if not project_db_path:
            QMessageBox.warning(parent_widget, "Error", "Project database path not found.")
            return False

        try:
            from .core.spatial_engine import SpatialEngine
            with SpatialEngine(project_db_path) as engine:
                conn = engine._repo.project_manager.connection
                # Add score column if it does not exist yet
                try:
                    conn.execute(
                        f'ALTER TABLE "{table_name}" '
                        f'ADD COLUMN "{score_column}" REAL DEFAULT 0'
                    )
                except Exception:
                    pass  # column already exists — fine

                # Weighted area-proportional score
                conn.execute(f"""
                    UPDATE "{table_name}"
                    SET "{score_column}" = {matched_weight} * (
                        COALESCE(ST_Area(geom), 0) /
                        NULLIF(
                            (SELECT SUM(COALESCE(ST_Area(geom), 0))
                             FROM "{table_name}"),
                            0
                        )
                    )
                """)
                conn.commit()

            # Refresh any QGIS layer currently displaying this table
            for layer in QgsProject.instance().mapLayers().values():
                if table_name in (layer.name() or ''):
                    layer.reload()

            QMessageBox.information(
                parent_widget, "MCDA Applied",
                f"Score column '{score_column}' computed and saved to '{table_name}'.\n"
                f"Layer weight used: {matched_weight * 100:.0f}%"
            )
            return True

        except Exception as e:
            QMessageBox.critical(parent_widget, "MCDA Error", str(e))
            return False
