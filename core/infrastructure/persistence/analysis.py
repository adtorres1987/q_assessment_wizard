# -*- coding: utf-8 -*-
"""MCDA analysis configuration (weights) and per-version snapshots."""

import json


class AnalysisMixin:
    """Analysis configs and weight snapshots per output table."""

    def create_analysis_config(self, assessment_id, model_type='MCDA',
                               score_column='MCDA_SCORE', weights=None):
        """Insert or update the Default MCDA configuration for an assessment.

        Writes to 'analyses' and syncs 'assessment_criteria' + 'analysis_weights'.

        Args:
            assessment_id: int
            model_type:    str — e.g. 'MCDA' or 'weighted_sum'
            score_column:  str — name of the score column in the overlay table
            weights:       dict {layer_name: float} — values should sum to 1.0
        Returns:
            int: analysis_id of the inserted/updated record
        """
        weights_dict = weights or {}
        weights_json = json.dumps(weights_dict)
        cursor = self.connection.cursor()

        # ── New schema: upsert into 'analyses' ───────────────────────────
        cursor.execute(
            "SELECT id FROM analyses WHERE assessment_id = ? AND name = 'Default'",
            (assessment_id,)
        )
        row = cursor.fetchone()
        if row:
            analysis_id = row[0]
            cursor.execute(
                """UPDATE analyses
                   SET model_type = ?, score_column = ?, weights_json = ?, status = 'valid'
                   WHERE id = ?""",
                (model_type, score_column, weights_json, analysis_id)
            )
        else:
            cursor.execute(
                """INSERT INTO analyses
                       (assessment_id, name, model_type, score_column, status, weights_json)
                   VALUES (?, 'Default', ?, ?, 'valid', ?)""",
                (assessment_id, model_type, score_column, weights_json)
            )
            analysis_id = cursor.lastrowid

        # ── Sync normalized weights (delete + re-insert) ─────────────────
        cursor.execute("DELETE FROM analysis_weights WHERE analysis_id = ?", (analysis_id,))
        total = sum(weights_dict.values()) or 1.0
        for layer_name, weight in weights_dict.items():
            # Find or create criterion for (assessment, layer)
            cursor.execute(
                "SELECT id FROM assessment_criteria WHERE assessment_id = ? AND layer_name = ?",
                (assessment_id, layer_name)
            )
            crit_row = cursor.fetchone()
            if crit_row:
                criterion_id = crit_row[0]
                cursor.execute(
                    "UPDATE assessment_criteria SET weight_default = ? WHERE id = ?",
                    (weight, criterion_id)
                )
            else:
                cursor.execute(
                    """INSERT INTO assessment_criteria
                           (assessment_id, layer_name, criterion_name, weight_default)
                       VALUES (?, ?, ?, ?)""",
                    (assessment_id, layer_name, layer_name, weight)
                )
                criterion_id = cursor.lastrowid

            cursor.execute(
                """INSERT INTO analysis_weights
                       (analysis_id, criterion_id, weight, normalized_weight)
                   VALUES (?, ?, ?, ?)""",
                (analysis_id, criterion_id, weight, weight / total)
            )

        self.connection.commit()
        cursor.close()
        return analysis_id

    def get_analysis_config(self, assessment_id):
        """Return MCDA config dict for the given assessment, or None.

        Returns the Default config row from 'analyses'. If only versioned
        snapshots exist, returns the most recent one.

        Returns:
            dict with keys: id, assessment_id, model_type, score_column,
                            weights_json, created_at
        """
        cursor = self.connection.cursor()
        # Prefer the mutable 'Default' row; fall back to newest snapshot
        cursor.execute(
            """SELECT id, assessment_id, model_type, score_column, weights_json, created_at
               FROM analyses WHERE assessment_id = ?
               ORDER BY CASE WHEN name = 'Default' THEN 0 ELSE 1 END,
                        created_at DESC LIMIT 1""",
            (assessment_id,)
        )
        row = cursor.fetchone()
        cursor.close()
        if not row:
            return None
        return {
            'id': row[0], 'assessment_id': row[1],
            'model_type': row[2], 'score_column': row[3],
            'weights_json': row[4], 'created_at': row[5],
        }

    def update_analysis_config(self, assessment_id, model_type=None,
                               score_column=None, weights=None):
        """Partial update of analysis config — only updates provided fields.

        Args:
            assessment_id: int
            model_type:    str or None
            score_column:  str or None
            weights:       dict or None — if provided, replaces existing weights
        """
        config = self.get_analysis_config(assessment_id) or {}
        new_model_type   = model_type   or config.get('model_type',   'MCDA')
        new_score_column = score_column or config.get('score_column', 'MCDA_SCORE')
        new_weights = (
            weights if weights is not None
            else json.loads(config.get('weights_json') or '{}')
        )
        self.create_analysis_config(
            assessment_id, new_model_type, new_score_column, new_weights
        )

    def snapshot_analysis_for_version(self, assessment_id, output_table, version_num):
        """Create an immutable analyses snapshot for one completed run.

        Copies weights_json from the current 'Default' row into a new
        'v{version_num}' row, then records output_table in analysis_results.
        This preserves the weights used for each specific run.

        Args:
            assessment_id: int
            output_table:  str — the versioned overlay table name (e.g. '1__urban__v2')
            version_num:   int — version number extracted from the table name

        Returns:
            int: analysis_id of the new snapshot row, or None on failure.
        """
        config = self.get_analysis_config(assessment_id)
        weights_json = config.get('weights_json', '{}') if config else '{}'
        model_type   = config.get('model_type',   'weighted_sum') if config else 'weighted_sum'
        score_column = config.get('score_column', 'MCDA_SCORE')   if config else 'MCDA_SCORE'

        cursor = self.connection.cursor()
        try:
            cursor.execute(
                """INSERT INTO analyses
                       (assessment_id, name, model_type, score_column, status, weights_json)
                   VALUES (?, ?, ?, ?, 'valid', ?)""",
                (assessment_id, f"v{version_num}", model_type, score_column, weights_json)
            )
            analysis_id = cursor.lastrowid

            cursor.execute(
                """INSERT INTO analysis_results
                       (analysis_id, output_table, output_layer_name)
                   VALUES (?, ?, ?)""",
                (analysis_id, output_table, output_table)
            )
            self.connection.commit()
            return analysis_id
        except Exception as e:
            print(f"AdminManager.snapshot_analysis_for_version warning: {e}")
            return None
        finally:
            cursor.close()

    def get_analysis_for_output_table(self, output_table):
        """Return the analyses snapshot row linked to a specific output table, or None.

        Looks up analysis_results by output_table and returns the corresponding
        analyses row (the versioned snapshot, not the mutable 'Default').

        Returns:
            dict with keys: id, assessment_id, name, model_type, score_column,
                            status, weights_json, created_at — or None.
        """
        cursor = self.connection.cursor()
        cursor.execute(
            """SELECT a.id, a.assessment_id, a.name, a.model_type, a.score_column,
                      a.status, a.weights_json, a.created_at
               FROM analyses a
               JOIN analysis_results ar ON ar.analysis_id = a.id
               WHERE ar.output_table = ?
               ORDER BY a.created_at DESC LIMIT 1""",
            (output_table,)
        )
        row = cursor.fetchone()
        cursor.close()
        if not row:
            return None
        return {
            'id': row[0], 'assessment_id': row[1], 'name': row[2],
            'model_type': row[3], 'score_column': row[4],
            'status': row[5], 'weights_json': row[6], 'created_at': row[7],
        }
