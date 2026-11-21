# -*- coding: utf-8 -*-
"""
In-memory fakes of the application ports, for unit tests without QGIS.

  FakeMetadataRepo  — MetadataRepositoryPort (subset used by the use cases)
  FakeEngine        — SpatialEnginePort, usable as ``engine_factory(db_path)``
  FakeMapLayers     — MapLayersPort
  FakeLayer         — minimal stand-in for a QgsVectorLayer (name only)
"""

import json


class FakeLayer:
    def __init__(self, name, selected=0):
        self._name = name
        self.selected = selected

    def name(self):
        return self._name


class FakeMetadataRepo:

    def __init__(self):
        self.projects = {}        # id -> dict
        self.assessments = {}     # id -> dict (with 'output_tables')
        self.layers = {}          # assessment_id -> [{'layer_name', 'layer_type'}]
        self.visibility = {}      # assessment_id -> {table: bool}
        self.configs = {}         # assessment_id -> {'weights_json', ...}
        self.snapshots = {}       # output_table -> config dict
        self.provenance = {}      # assessment_id -> [{'id'}]
        self.task_trees = {}      # provenance_id -> [task dict]
        self.portfolios = {}      # id -> dict
        self.base_layers = {}     # project_id -> [{'layer_name'}]
        self.db_paths = {}        # project_id -> path
        self.calls = []

    # projects
    def get_all_projects(self):
        return [p for p in self.projects.values() if not p.get('is_deleted')]

    def create_project(self, name, description=""):
        pid = len(self.projects) + 1
        self.projects[pid] = {'id': pid, 'name': name, 'description': description}
        self.db_paths[pid] = f"/tmp/{name}.sqlite"
        return pid

    def delete_project(self, project_id):
        self.projects[project_id]['is_deleted'] = True

    def get_project_db_path(self, project_id):
        return self.db_paths.get(project_id)

    def get_base_layers_for_project(self, project_id):
        return self.base_layers.get(project_id, [])

    # assessments
    def add_assessment(self, project_id, name, output_tables=(), target_layer='t'):
        aid = len(self.assessments) + 1
        self.assessments[aid] = {'id': aid, 'project_id': project_id, 'name': name,
                                 'target_layer': target_layer,
                                 'output_tables': list(output_tables)}
        return aid

    def get_assessments_for_project(self, project_id):
        return [a for a in self.assessments.values()
                if a['project_id'] == project_id and not a.get('is_deleted')]

    def get_assessment(self, assessment_id):
        return self.assessments.get(assessment_id)

    def assessment_name_exists(self, project_id, name):
        return any(a['name'] == name for a in self.get_assessments_for_project(project_id))

    def delete_assessment(self, assessment_id):
        self.assessments[assessment_id]['is_deleted'] = True

    def get_assessment_layers(self, assessment_id, layer_type=None):
        return [lr for lr in self.layers.get(assessment_id, [])
                if layer_type is None or lr['layer_type'] == layer_type]

    def set_layer_visibility(self, assessment_id, table, visible):
        self.visibility.setdefault(assessment_id, {})[table] = visible

    def get_layer_visibility(self, assessment_id):
        return dict(self.visibility.get(assessment_id, {}))

    # analysis config
    def get_analysis_config(self, assessment_id):
        return self.configs.get(assessment_id)

    def update_analysis_config(self, assessment_id, weights=None, **_):
        cfg = self.configs.setdefault(assessment_id, {'score_column': 'MCDA_SCORE'})
        if weights is not None:
            cfg['weights_json'] = json.dumps(weights)

    def get_analysis_for_output_table(self, table):
        return self.snapshots.get(table)

    # provenance
    def get_provenance_for_assessment(self, assessment_id):
        return self.provenance.get(assessment_id, [])

    def build_task_tree(self, provenance_id):
        return self.task_trees.get(provenance_id, [])

    # portfolios
    def create_portfolio(self, assessment_id, source_table, name, config_json):
        pid = len(self.portfolios) + 1
        self.portfolios[pid] = {'id': pid, 'assessment_id': assessment_id,
                                'source_table': source_table, 'name': name,
                                'config': json.loads(config_json), 'status': 'pending'}
        return pid

    def portfolio_name_exists(self, assessment_id, name):
        return any(p['assessment_id'] == assessment_id and p['name'] == name
                   for p in self.portfolios.values())

    def get_portfolios_for_assessment(self, assessment_id):
        return [p for p in self.portfolios.values() if p['assessment_id'] == assessment_id]

    def get_portfolio(self, portfolio_id):
        return self.portfolios.get(portfolio_id)

    def delete_portfolio(self, portfolio_id):
        self.portfolios.pop(portfolio_id, None)


class FakeEngine:
    """SpatialEnginePort fake. Configure class-level state per test."""

    tables = set()            # existing table names
    values = {}               # (table, field) -> [floats]
    summary = {}              # table -> (columns, rows)
    migrate_stats = []        # list returned by migrate_layers
    scored = []               # (table, column, weight) calls
    opened = []               # db paths opened

    def __init__(self, db_path):
        self.db_path = db_path

    @classmethod
    def reset(cls):
        cls.tables, cls.values, cls.summary = set(), {}, {}
        cls.migrate_stats, cls.scored, cls.opened = [], [], []

    def __enter__(self):
        FakeEngine.opened.append(self.db_path)
        return self

    def __exit__(self, *exc):
        return False

    def sanitize_name(self, raw):
        return raw.lower()

    def table_exists(self, name):
        return name in FakeEngine.tables

    def migrate_layers(self, layers, progress_callback=None):
        for i, name in enumerate(layers):
            if progress_callback:
                progress_callback(i, len(layers), name, f"Migrating {name}")
        return list(FakeEngine.migrate_stats)

    def results_values(self, table, field):
        if table not in FakeEngine.tables:
            raise LookupError(table)
        return FakeEngine.values.get((table, field), [])

    def results_summary(self, table):
        if table not in FakeEngine.tables:
            raise LookupError(table)
        return FakeEngine.summary[table]

    def result_columns(self, table):
        return FakeEngine.summary[table][0]

    def score_table(self, table, column, weight):
        FakeEngine.scored.append((table, column, weight))


class FakeMapLayers:

    def __init__(self):
        self.memory_layers = []
        self.reloaded = []

    def selected_feature_count(self, layer):
        return layer.selected

    def add_selection_as_memory_layer(self, layer, name, group_name):
        self.memory_layers.append((layer.name(), name, group_name))
        return object()

    def reload_layers_showing(self, table_name):
        self.reloaded.append(table_name)
