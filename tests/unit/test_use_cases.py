# -*- coding: utf-8 -*-
"""Unit tests for core/application use cases, with fake ports (no QGIS)."""

import json
import unittest

from core.application import (
    CreatePortfolio, CreatePortfolioCommand,
    CreateProject, CreateProjectCommand,
    UpdateWeights, UpdateWeightsCommand,
    SetLayerVisibility, SetLayerVisibilityCommand,
    GetProjectTree, GetAnalysisWeights, GetWeightsConfig, FindAssessmentId,
    FindExistingLayers, MigrateLayers, MigrateLayersCommand,
    GetComparisonSeries, GetComparisonSeriesCommand,
    GetResultsGrid, GetResultsGridCommand,
    CreateScenario, CreateScenarioCommand,
    ApplyMcdaScore, ApplyMcdaScoreCommand,
    OperationCancelled,
)
from tests.fakes import FakeMetadataRepo, FakeEngine, FakeMapLayers, FakeLayer


def portfolio_cmd(**overrides):
    base = dict(assessment_id=1, source_table="p__a__v1", name="North",
                col_benefits="b", col_cost="c", col_priority="p",
                budget=1000.0, buckets=[{"name": "A", "amount": 600.0}])
    base.update(overrides)
    return CreatePortfolioCommand(**base)


class CreatePortfolioTest(unittest.TestCase):

    def setUp(self):
        self.repo = FakeMetadataRepo()
        self.uc = CreatePortfolio(self.repo)

    def test_saves_pending_config(self):
        result = self.uc.execute(portfolio_cmd())
        stored = self.repo.get_portfolio(result['portfolio_id'])
        self.assertEqual(stored['status'], 'pending')
        self.assertEqual(stored['config']['col_benefits'], 'b')
        self.assertEqual(stored['config']['buckets'], [{"name": "A", "amount": 600.0}])

    def test_rules(self):
        for bad, message in (
            (dict(name="  "), "required"),
            (dict(col_cost="b"), "distinct"),
            (dict(col_priority=""), "required"),
            (dict(budget=-1), "negative"),
            (dict(buckets=[{"name": "A", "amount": 1500.0}]), "exceeds"),
        ):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, message):
                self.uc.execute(portfolio_cmd(**bad))

    def test_duplicate_name_rejected(self):
        self.uc.execute(portfolio_cmd())
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.uc.execute(portfolio_cmd())


class CatalogTest(unittest.TestCase):

    def setUp(self):
        self.repo = FakeMetadataRepo()

    def test_create_project_requires_name(self):
        with self.assertRaises(ValueError):
            CreateProject(self.repo).execute(CreateProjectCommand("   "))
        pid = CreateProject(self.repo).execute(CreateProjectCommand(" demo "))
        self.assertEqual(self.repo.projects[pid]['name'], "demo")

    def test_update_weights_sum_rule(self):
        uc = UpdateWeights(self.repo)
        with self.assertRaisesRegex(ValueError, "100%"):
            uc.execute(UpdateWeightsCommand(1, {"a": 0.5, "b": 0.4}))
        with self.assertRaisesRegex(ValueError, "negative"):
            uc.execute(UpdateWeightsCommand(1, {"a": 1.2, "b": -0.2}))
        uc.execute(UpdateWeightsCommand(1, {"a": 0.6, "b": 0.402}))    # within ±0.5 %
        self.assertEqual(json.loads(self.repo.configs[1]['weights_json']), {"a": 0.6, "b": 0.402})

    def test_set_visibility(self):
        SetLayerVisibility(self.repo).execute(SetLayerVisibilityCommand(3, "t__v1", False))
        self.assertEqual(self.repo.get_layer_visibility(3), {"t__v1": False})


class ExplorerQueriesTest(unittest.TestCase):

    def setUp(self):
        self.repo = FakeMetadataRepo()
        self.pid = self.repo.create_project("demo")
        self.repo.base_layers[self.pid] = [{'layer_name': 'parcels'}]
        self.with_prov = self.repo.add_assessment(self.pid, "overlay", output_tables=["demo__overlay__v1"])
        self.repo.provenance[self.with_prov] = [{'id': 10}]
        self.repo.task_trees[10] = [
            {'output_tables': json.dumps(["demo__overlay__v1"]),
             'children': [{'output_tables': json.dumps(["demo__overlay__v2"])},
                          {'output_tables': 'not json'}]},
        ]
        self.simple = self.repo.add_assessment(self.pid, "simple", output_tables=["demo__simple"])
        self.repo.configs[self.with_prov] = {'weights_json': '{"riesgo": 1.0}'}
        self.repo.configs[self.simple] = {'weights_json': '{broken'}
        self.repo.visibility[self.with_prov] = {"demo__overlay__v1": False}

    def test_project_tree_read_model(self):
        tree = GetProjectTree(self.repo).execute()
        self.assertEqual(len(tree), 1)
        project = tree[0]
        self.assertEqual(project['base_layers'], [{'layer_name': 'parcels'}])
        overlay, simple = project['assessments']
        self.assertEqual(overlay['analysis_tables'], ["demo__overlay__v1", "demo__overlay__v2"])
        self.assertEqual(overlay['weights'], {"riesgo": 1.0})
        self.assertEqual(overlay['visibility'], {"demo__overlay__v1": False})
        # no provenance → falls back to the assessment's output tables
        self.assertEqual(simple['analysis_tables'], ["demo__simple"])
        self.assertEqual(simple['weights'], {})            # invalid JSON is tolerated

    def test_analysis_weights_prefers_snapshot(self):
        uc = GetAnalysisWeights(self.repo)
        self.repo.snapshots["demo__overlay__v1"] = {'weights_json': '{"old": 1.0}'}
        self.assertEqual(uc.execute(self.with_prov, "demo__overlay__v1"), {"old": 1.0})
        self.assertEqual(uc.execute(self.with_prov, "demo__overlay__v2"), {"riesgo": 1.0})
        self.assertIsNone(uc.execute(999, ""))

    def test_weights_config_lists_input_layers_first(self):
        self.repo.layers[self.with_prov] = [{'layer_name': 'b', 'layer_type': 'input'},
                                            {'layer_name': 'out', 'layer_type': 'output'}]
        config = GetWeightsConfig(self.repo).execute(self.with_prov)
        self.assertEqual(config['layer_names'], ['b', 'riesgo'])

    def test_find_assessment_id(self):
        uc = FindAssessmentId(self.repo)
        self.assertEqual(uc.execute(self.pid, "simple"), self.simple)
        self.assertIsNone(uc.execute(self.pid, "missing"))


class MigrationTest(unittest.TestCase):

    def setUp(self):
        FakeEngine.reset()
        self.repo = FakeMetadataRepo()
        self.pid = self.repo.create_project("demo")
        self.layers = {"Parcels": FakeLayer("Parcels"), "Risk": FakeLayer("Risk")}

    def test_find_existing(self):
        FakeEngine.tables = {"parcels"}
        found = FindExistingLayers(self.repo, FakeEngine).execute(
            MigrateLayersCommand(self.pid, self.layers))
        self.assertEqual(found, ["Parcels"])

    def test_summary(self):
        FakeEngine.migrate_stats = [
            {'table_name': 'parcels', 'inserted': 3, 'errors': 1},
            {'table_name': 'risk', 'error': 'boom', 'inserted': 0, 'errors': 0},
        ]
        summary = MigrateLayers(self.repo, FakeEngine).execute(
            MigrateLayersCommand(self.pid, self.layers))
        self.assertEqual(summary, {'migrated': ['parcels'], 'failed': ['risk: boom'],
                                   'inserted': 3, 'errors': 1})

    def test_cancel_propagates(self):
        def cancel(*_):
            raise OperationCancelled()
        with self.assertRaises(OperationCancelled):
            MigrateLayers(self.repo, FakeEngine).execute(
                MigrateLayersCommand(self.pid, self.layers, cancel))

    def test_missing_db_path(self):
        with self.assertRaises(RuntimeError):
            MigrateLayers(self.repo, FakeEngine).execute(MigrateLayersCommand(999, self.layers))


class ResultQueriesTest(unittest.TestCase):

    def setUp(self):
        FakeEngine.reset()
        self.repo = FakeMetadataRepo()
        self.pid = self.repo.create_project("demo")

    def test_comparison_needs_two_series_with_data(self):
        uc = GetComparisonSeries(self.repo, FakeEngine)
        with self.assertRaises(ValueError):
            uc.execute(GetComparisonSeriesCommand(self.pid, {"a": "t1"}, "fragments"))
        FakeEngine.tables = {"t1", "t2"}
        FakeEngine.values = {("t1", "fragments"): [1, 2], ("t2", "fragments"): []}
        with self.assertRaisesRegex(ValueError, "No data"):
            uc.execute(GetComparisonSeriesCommand(self.pid, {"a": "t1", "b": "t2"}, "fragments"))
        FakeEngine.values[("t2", "fragments")] = [3]
        series = uc.execute(GetComparisonSeriesCommand(self.pid, {"a": "t1", "b": "t2"}, "fragments"))
        self.assertEqual(series, {"a": [1, 2], "b": [3]})

    def test_grid_missing_table_is_lookup_error(self):
        with self.assertRaises(LookupError):
            GetResultsGrid(self.repo, FakeEngine).execute(GetResultsGridCommand(self.pid, "nope"))


class ScenarioAndMcdaTest(unittest.TestCase):

    def setUp(self):
        FakeEngine.reset()
        self.repo = FakeMetadataRepo()
        self.pid = self.repo.create_project("demo")
        self.map = FakeMapLayers()

    def test_create_scenario_requires_selection(self):
        uc = CreateScenario(self.repo, self.map)
        cmd = CreateScenarioCommand("s1", "", "demo", self.pid, FakeLayer("parcels", selected=0))
        with self.assertRaisesRegex(ValueError, "No features"):
            uc.execute(cmd)

    def test_create_scenario_adds_memory_layer(self):
        uc = CreateScenario(self.repo, self.map)
        result = uc.execute(CreateScenarioCommand("s1", "d", "demo", self.pid,
                                                  FakeLayer("parcels", selected=2)))
        self.assertEqual(result['output_tables'], ["demo__s1"])
        self.assertEqual(self.map.memory_layers, [("parcels", "demo__s1", "Output Layers")])

    def test_create_scenario_duplicate_name(self):
        self.repo.add_assessment(self.pid, "s1")
        with self.assertRaisesRegex(ValueError, "already exists"):
            CreateScenario(self.repo, self.map).execute(
                CreateScenarioCommand("s1", "", "demo", self.pid, FakeLayer("p", selected=1)))

    def test_mcda_scores_and_reloads_layer(self):
        aid = self.repo.add_assessment(self.pid, "overlay")
        self.repo.configs[aid] = {'weights_json': '{"risk": 0.7}', 'score_column': 'MCDA_SCORE'}
        ApplyMcdaScore(self.repo, FakeEngine, self.map).execute(
            ApplyMcdaScoreCommand(aid, "demo__overlay_risk__v2", self.pid))
        self.assertEqual(FakeEngine.scored, [("demo__overlay_risk__v2", "MCDA_SCORE", 0.7)])
        self.assertEqual(self.map.reloaded, ["demo__overlay_risk__v2"])

    def test_mcda_without_config(self):
        aid = self.repo.add_assessment(self.pid, "overlay")
        with self.assertRaisesRegex(ValueError, "No MCDA configuration"):
            ApplyMcdaScore(self.repo, FakeEngine).execute(ApplyMcdaScoreCommand(aid, "t__v1", self.pid))


if __name__ == '__main__':
    unittest.main()
