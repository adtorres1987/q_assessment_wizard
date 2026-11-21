# -*- coding: utf-8 -*-
"""
Read-only use cases for the EMDS Project Explorer panel.

They return plain dicts/lists (read models) so the UI never queries the
metadata repository itself.

  - GetProjectTree        — everything the explorer tree shows
  - GetProjectSummary     — counts shown for a project node
  - GetAssessmentDetails  — assessment card (target, layers, weights)
  - GetAnalysisWeights    — weights used by one analysis version
  - GetWeightsConfig      — layers + current weights for the weights editor
  - GetPortfolio          — one stored portfolio configuration
  - FindAssessmentId      — assessment id by name within a project
"""

import json

from ..ports import MetadataRepositoryPort


def _weights_from(config):
    """Weights dict stored in an analysis config row ({} if absent/invalid)."""
    if not config:
        return {}
    try:
        return json.loads(config.get('weights_json') or '{}')
    except (ValueError, TypeError):
        return {}


class _Query:

    def __init__(self, metadata_repo: MetadataRepositoryPort):
        if metadata_repo is None:
            raise RuntimeError(f"{type(self).__name__} requires a metadata_repo instance.")
        self._meta = metadata_repo


class GetProjectTree(_Query):
    """Use case: projects → base layers / assessments → analyses + portfolios."""

    def execute(self) -> list:
        """Returns a list of project dicts::

            {'id', 'name',
             'base_layers': [{'layer_name', ...}],
             'assessments': [{'id', 'name', 'target_layer', 'output_tables',
                              'weights': {layer: fraction},
                              'analysis_tables': [table, ...],
                              'visibility': {table: bool},
                              'portfolios': [portfolio dict, ...]}]}
        """
        tree = []
        for project in self._meta.get_all_projects():
            assessments = []
            for assessment in self._meta.get_assessments_for_project(project['id']):
                tables = self._analysis_tables(assessment['id']) \
                    or list(assessment.get('output_tables', []))
                assessments.append({
                    **assessment,
                    'weights': _weights_from(self._meta.get_analysis_config(assessment['id'])),
                    'analysis_tables': tables,
                    'visibility': self._meta.get_layer_visibility(assessment['id']) if tables else {},
                    'portfolios': self._meta.get_portfolios_for_assessment(assessment['id']),
                })
            tree.append({
                **project,
                'base_layers': self._meta.get_base_layers_for_project(project['id']),
                'assessments': assessments,
            })
        return tree

    def _analysis_tables(self, assessment_id):
        """All output tables recorded in the assessment's provenance task trees."""
        tables = []
        for provenance in self._meta.get_provenance_for_assessment(assessment_id):
            self._collect(self._meta.build_task_tree(provenance['id']), tables)
        return tables

    @classmethod
    def _collect(cls, tasks, tables):
        for task in tasks:
            try:
                tables.extend(json.loads(task.get('output_tables') or '[]'))
            except (ValueError, TypeError):
                pass
            if task.get('children'):
                cls._collect(task['children'], tables)


class GetProjectSummary(_Query):
    """Use case: summary of one project."""

    def execute(self, project_id) -> dict:
        return {'assessment_count': len(self._meta.get_assessments_for_project(project_id))}


class GetAssessmentDetails(_Query):
    """Use case: data for the assessment card."""

    def execute(self, assessment_id) -> dict:
        """Returns {'assessment': dict | None, 'input_layers': list, 'weights': dict}."""
        return {
            'assessment': self._meta.get_assessment(assessment_id),
            'input_layers': self._meta.get_assessment_layers(assessment_id, 'input'),
            'weights': _weights_from(self._meta.get_analysis_config(assessment_id)),
        }


class GetAnalysisWeights(_Query):
    """Use case: weights used by one analysis version.

    Prefers the snapshot tied to *table_name* (preserves history) and falls
    back to the assessment's current config.
    """

    def execute(self, assessment_id, table_name='') -> dict:
        """Returns the weights dict, or None when no config exists at all."""
        config = (self._meta.get_analysis_for_output_table(table_name)
                  if table_name else None) or self._meta.get_analysis_config(assessment_id)
        return _weights_from(config) if config else None


class GetWeightsConfig(_Query):
    """Use case: input for the MCDA weights editor."""

    def execute(self, assessment_id) -> dict:
        """Returns {'layer_names': [...], 'weights': {layer: fraction}}.

        Layer names are the assessment's input layers followed by any layer
        that only appears in the stored weights.
        """
        weights = _weights_from(self._meta.get_analysis_config(assessment_id))
        names = [layer['layer_name']
                 for layer in self._meta.get_assessment_layers(assessment_id, 'input')]
        names += [name for name in weights if name not in names]
        return {'layer_names': names, 'weights': weights}


class GetPortfolio(_Query):
    """Use case: one stored portfolio (or None)."""

    def execute(self, portfolio_id):
        return self._meta.get_portfolio(portfolio_id)


class FindAssessmentId(_Query):
    """Use case: id of the assessment called *name* in a project (or None)."""

    def execute(self, project_id, name):
        for assessment in self._meta.get_assessments_for_project(project_id):
            if assessment['name'] == name:
                return assessment['id']
        return None
