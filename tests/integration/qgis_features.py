# -*- coding: utf-8 -*-
"""Integration test (needs QGIS 4 Python): results grid (+ CSV/PDF export),
comparison histogram, portfolio wizard, context menus, layer migration
(incl. cancel), explorer facade, i18n in all four languages.

Run through tools/run_tests.sh (it sets PLUGROOT and SP to scratch dirs).
"""
import os, sys, traceback, csv
SP = os.environ["SP"]
from qgis.PyQt.QtCore import QSettings, QCoreApplication
# Isolate settings: never touch the user's real QGIS profile.
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, os.path.join(SP, "settings"))
QCoreApplication.setOrganizationName("qaw-test"); QCoreApplication.setApplicationName("qaw-test")

from qgis.core import QgsApplication, QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry
app = QgsApplication([], True); app.initQgis()
sys.path.insert(0, os.environ["PLUGROOT"])
from qgis.PyQt.QtWidgets import QMainWindow, QMessageBox, QMenu, QDialog
from qgis.gui import QgsMapCanvas

msgs = []
for n in ("information", "warning", "critical"):
    setattr(QMessageBox, n, staticmethod(lambda *a, _n=n, **k: msgs.append((_n, a[1] if len(a) > 1 else '', a[2] if len(a) > 2 else '')) or QMessageBox.StandardButton.Ok))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)

FAILS = []
def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond: FAILS.append(name)
def step(name, fn):
    try:
        return fn()
    except Exception:
        print("FAIL (exception) " + name); traceback.print_exc(file=sys.stdout); FAILS.append(name)

canvas = QgsMapCanvas()
class I: pass
iface = I(); iface._mw = QMainWindow(); iface.mainWindow = lambda: iface._mw; iface.mapCanvas = lambda: canvas
iface.messageBar = lambda: None; iface.addDockWidget = lambda a, d: None; iface.removeDockWidget = lambda d: None
iface.addToolBarIcon = iface.removeToolBarIcon = lambda a: None; iface.addPluginToMenu = iface.removePluginMenu = lambda m, a: None

import q_assessment_wizard as pkg
from q_assessment_wizard.ui.i18n import translator
translator.set_language('en', persist=False)
plugin = pkg.classFactory(iface); plugin.initGui(); plugin.run()
mf = plugin.main_form; am = plugin.admin_manager
check("toolbar icon loaded from icon.png", not plugin.explorer_action.icon().isNull())

def mk(name, polys):
    l = QgsVectorLayer("Polygon?crs=EPSG:4326&field=nombre:string&field=costo:double&field=beneficio:double", name, "memory")
    feats = []
    for i, wkt in enumerate(polys):
        f = QgsFeature(l.fields()); f.setGeometry(QgsGeometry.fromWkt(wkt)); f.setAttributes([f"{name}{i}", 10.0 * (i + 1), 5.0 * (i + 2)]); feats.append(f)
    l.dataProvider().addFeatures(feats); QgsProject.instance().addMapLayer(l); return l
target = mk("parcelas", ["POLYGON((0 0,2 0,2 2,0 2,0 0))", "POLYGON((2 0,4 0,4 2,2 2,2 0))", "POLYGON((6 0,8 0,8 2,6 2,6 0))"])
assess = mk("riesgo", ["POLYGON((1 1,3 1,3 3,1 3,1 1))"])
g = QgsProject.instance().layerTreeRoot().addGroup("Base Layers"); g.addLayer(target); g.addLayer(assess)

pid = am.create_project("demo", "t")
from q_assessment_wizard.ui.assessment_executor import AssessmentExecutor
ex = AssessmentExecutor("demo", am, pid)
r1 = ex.execute_spatial_assessment("overlay", target, [assess], "d"); ex.record_assessment(r1)
aid = next(a['id'] for a in am.get_assessments_for_project(pid) if a['name'] == 'overlay')
r2 = ex.rerun_spatial_assessment(aid)
target.selectAll(); rs = ex.execute_simple_assessment("simple", target, "d"); ex.record_assessment(rs)
v1, v2 = r1['output_tables'][0], r2['output_tables'][0]
ex.apply_mcda_score(aid, v2)

# ── 1. Results grid query (use case) ───────────────────────────────────────
grid = step("grid query", lambda: ex.get_results_grid(v1))
if grid:
    rows = {r[0]: dict(zip(grid['columns'], r)) for r in grid['rows']}
    check("grid: one row per target feature", len(rows) == 3, f"rows={len(rows)}")
    # Coverage relative to the original feature (F-02): 2x2 parcels with a 1x1 overlap → 25 %.
    ok_hit = all(abs(rows[i]['coverage_pct'] - 25.0) < 0.01 and rows[i]['coverage_class'] == 'Medium (25-74%)'
                 and abs(rows[i]['intersect_area'] - 1) < 1e-6 and abs(rows[i]['no_overlap_area'] - 3) < 1e-6
                 and abs(rows[i]['total_area'] - 4) < 1e-6 for i in (1, 2))
    ok_miss = rows[3]['coverage_pct'] == 0 and rows[3]['coverage_class'] == 'None (0%)' and abs(rows[3]['no_overlap_area'] - 4) < 1e-6
    check("grid: intersecting features 25%/Medium (1 of 4), isolated feature 0%/None (area 4)", ok_hit and ok_miss, str(rows))
    check("grid: sorted by coverage desc", grid['rows'][-1][0] == 3)
    check("grid v1: no mcda column (not scored)", 'mcda_score' not in grid['columns'])
g2 = step("grid v2 (MCDA scored)", lambda: ex.get_results_grid(v2))
if g2:
    check("grid v2: mcda_score column present", 'mcda_score' in g2['columns'], str(g2['columns']))
try:
    ex.get_results_grid("tabla_que_no_existe"); check("grid: missing table raises LookupError", False)
except LookupError:
    check("grid: missing table raises LookupError", True)

# ── 2. Results grid dialog: group, filter, chart, CSV + PDF export ─────────
from q_assessment_wizard.ui.dialogs import ResultsGridDialog, CompareHistogramDialog, PortfolioWizard
from q_assessment_wizard.ui.dialogs import results_grid_dialog as rgd
check("matplotlib Qt6 backend available", rgd.HAS_MPL)
def grid_dialog():
    d = ResultsGridDialog(v1, grid['rows'], grid['columns'])
    d.show()
    d.group_combo.setCurrentIndex(d.group_combo.findData("coverage_class"))
    grouped_rows = d.proxy.rowCount()
    d.group_combo.setCurrentIndex(0)
    d.filter_input.setText("Medium"); filtered = d.proxy.rowCount(); d.filter_input.setText("")
    chart_ok = d.chart_col_combo.count() > 0 and len(d.figure.axes) == 1
    csv_path = os.path.join(SP, "grid.csv"); d.write_table(csv_path, use_xlsx=False)
    with open(csv_path, encoding="utf-8-sig") as fh: data = list(csv.reader(fh))
    pdf_path = os.path.join(SP, "grid.pdf"); d.write_pdf(pdf_path, include_grid=True, include_chart=True)
    pdf_ok = os.path.exists(pdf_path) and open(pdf_path, "rb").read(4) == b"%PDF" and os.path.getsize(pdf_path) > 5000
    return grouped_rows, filtered, chart_ok, data, pdf_ok, os.path.getsize(pdf_path)
res = step("grid dialog", grid_dialog)
if res:
    grouped_rows, filtered, chart_ok, data, pdf_ok, pdf_size = res
    check("grid dialog: grouping adds one header per class", grouped_rows == 5, f"rows={grouped_rows}")
    check("grid dialog: filter 'Medium' keeps 2 rows", filtered == 2, f"rows={filtered}")
    check("grid dialog: chart drawn", chart_ok)
    check("grid dialog: CSV header + 3 rows", len(data) == 4 and data[0][:2] == ['input_id', 'fragments'], str(data[:2]))
    check("grid dialog: PDF written (grid + chart)", pdf_ok, f"{pdf_size} bytes")

# ── 3. Context menus per node type ──────────────────────────────────────────
menus = {}
orig_exec = QMenu.exec
def capture_menu(self, *a, **k):
    menus.setdefault("last", [act.text() for act in self.actions() if act.text()]); return None
QMenu.exec = capture_menu
from q_assessment_wizard.ui.panels import ROLE_TYPE, ROLE_OUTPUT_TABLES
from qgis.PyQt.QtWidgets import QTreeWidgetItemIterator
def items_by_type():
    out = {}; it = QTreeWidgetItemIterator(mf.tree)
    while it.value():
        out.setdefault(it.value().data(0, ROLE_TYPE), []).append(it.value()); it += 1
    return out
mf._populate_tree(); nodes = items_by_type()
def menu_for(item):
    menus.clear(); mf.tree.scrollToItem(item); mf._on_context_menu(mf.tree.visualItemRect(item).center()); return menus.get("last", [])
for t in ("project", "analysis"):
    for it in nodes.get(t, [])[:1]:
        it.parent() and it.parent().setExpanded(True)
        if it.parent() and it.parent().parent(): it.parent().parent().setExpanded(True)
QgsApplication.processEvents()
proj_menu = menu_for(nodes['project'][0]); an_menu = menu_for(nodes['analysis'][0])
check("menu project: has Compare Outputs", any("Compare" in t for t in proj_menu), str(proj_menu))
check("menu analysis: has Results Grid + Portfolio", any("Results Grid" in t for t in an_menu) and any("Portfolio" in t for t in an_menu), str(an_menu))
QMenu.exec = orig_exec

# ── 4. Grid from the tree, incl. simple (memory) assessment fallback ────────
shown = []
ResultsGridDialog.exec = lambda self: shown.append((self.layer_name, list(self.columns), len(self.all_rows))) or 0
def analysis_item(table):
    return next(i for i in items_by_type()['analysis'] if (i.data(0, ROLE_OUTPUT_TABLES) or [None])[0] == table)
step("tree grid (overlay)", lambda: mf._on_view_results(analysis_item(v1)))
step("tree grid (simple fallback)", lambda: mf._on_view_results(analysis_item(rs['output_tables'][0])))
check("tree grid overlay opened with summary columns", shown and shown[0][1][0] == 'input_id', str(shown[:1]))
check("tree grid simple assessment falls back to layer attributes", len(shown) == 2 and 'nombre' in shown[1][1] and shown[1][2] == 3, str(shown[1:]))

# ── 5. Comparison histogram from the project node ──────────────────────────
hist = []
CompareHistogramDialog.exec = lambda self: hist.append(self) or 0
mf.tree.setCurrentItem(items_by_type()['project'][0])
step("compare outputs", mf._on_compare_outputs)
if hist:
    d = hist[0]
    labels = [d.list_widget.item(i).text() for i in range(d.list_widget.count())]
    check("histogram: lists only SpatiaLite overlay results (v1, v2)", len(labels) == 2, str(labels))
    from qgis.PyQt.QtCore import Qt
    for i in range(d.list_widget.count()): d.list_widget.item(i).setCheckState(Qt.CheckState.Checked)
    for bt in ("equal_range", "equal_dist"):
        d.bintype_combo.setCurrentIndex(d.bintype_combo.findData(bt))
        step(f"histogram plot {bt}", d.plot)
    check("histogram: plotted 1 butterfly pair", len(d.figure.axes) == 1 and "2 outputs" in d.status_lbl.text() and "6 total" in d.status_lbl.text(), d.status_lbl.text())
else:
    check("histogram dialog opened", False)

# ── 6. Portfolio wizard → CreatePortfolio → tree node → delete ─────────────
def drive_wizard(self, name="Cartera A", cols=("shape_area", "shape_length", "input_id"), budget=1000.0, bucket_a=600.0, bucket_b=None):
    self.show()
    self._page_name.name_edit.setText(name); self.next()
    for combo, col in zip((self._page_columns.benefits_combo, self._page_columns.cost_combo, self._page_columns.priority_combo), cols):
        combo.setCurrentIndex(max(0, combo.findText(col)))
    self.next()
    self._page_budget.budget_spin.setValue(budget); self.next()
    self._page_buckets._buckets[0][3].setValue(bucket_a)
    if bucket_b is not None:
        self._page_buckets._buckets[1][0].setChecked(True); self._page_buckets._buckets[1][3].setValue(bucket_b)
    self.next()
    reached_summary = self.currentId() == 4
    self.summary_html = self._page_summary.browser.toHtml()
    self.reached_summary = reached_summary
    return QDialog.DialogCode.Accepted if reached_summary else QDialog.DialogCode.Rejected
wizards = []
def exec_wiz(self, **kw):
    wizards.append(self); return drive_wizard(self, **PW_ARGS)
PortfolioWizard.exec = exec_wiz
PW_ARGS = {}
an_v1 = analysis_item(v1)
msgs.clear(); step("portfolio wizard (valid)", lambda: mf._on_portfolio_wizard(an_v1))
check("portfolio: wizard reached summary page", wizards and wizards[-1].reached_summary)
check("portfolio: saved message shown", any(m[1] == "Portfolio Saved" for m in msgs), str(msgs[-1:]))
pfs = am.get_portfolios_for_assessment(aid)
check("portfolio: stored as pending with config", len(pfs) == 1 and pfs[0]['status'] == 'pending' and pfs[0]['config']['col_benefits'] == 'shape_area' and pfs[0]['source_table'] == v1, str(pfs))
check("portfolio: wizard columns exclude geometry", wizards and 'geom' not in [wizards[-1]._page_columns.benefits_combo.itemText(i) for i in range(wizards[-1]._page_columns.benefits_combo.count())])
msgs.clear(); step("portfolio duplicate", lambda: mf._on_portfolio_wizard(analysis_item(v1)))
check("portfolio: duplicate name rejected by use case", any("already exists" in m[2] for m in msgs), str(msgs))
PW_ARGS = {"name": "Cartera B", "budget": 1000.0, "bucket_a": 700.0, "bucket_b": 500.0}
msgs.clear(); step("portfolio buckets>budget", lambda: mf._on_portfolio_wizard(analysis_item(v1)))
check("portfolio: buckets over budget blocked on bucket page", wizards and not wizards[-1].reached_summary and len(am.get_portfolios_for_assessment(aid)) == 1)
pf_nodes = items_by_type().get('portfolio', [])
check("tree: portfolio node shown", len(pf_nodes) == 1 and "Cartera A" in pf_nodes[0].text(0) and "pending" in pf_nodes[0].text(0), pf_nodes and pf_nodes[0].text(0))
pf_nodes and mf.tree.setCurrentItem(pf_nodes[0])
check("portfolio details panel", "shape_area" in mf.results_text_edit.toPlainText() and "1,000.00" in mf.results_text_edit.toPlainText(), mf.results_text_edit.toPlainText().replace("\n", " | "))

# ── 7. Language switch → Spanish everywhere, logic still works ─────────────
mf.language_combo.setCurrentIndex(mf.language_combo.findData('es'))
check("es: panel buttons", mf.btn_new_project.text() == "🗂 Nuevo proyecto" and mf.btn_compare.text() == "📊 Comparar resultados", mf.btn_new_project.text())
check("es: dock title + action", plugin.dock.windowTitle() == "EMDS – Explorador de proyectos" and plugin.explorer_action.text() == "Explorador EMDS")
labels = [i.text(0) for i in items_by_type().get('analysis', [])]
check("es: tree labels", any("Análisis v1" in t for t in labels) and any(i.text(0) == "⚙ Pesos" for i in items_by_type().get('weights', [])), str(labels[:2]))
pf_nodes = items_by_type().get('portfolio', [])
check("es: portfolio status translated", pf_nodes and "pendiente" in pf_nodes[0].text(0), pf_nodes and pf_nodes[0].text(0))
from q_assessment_wizard.ui.wizard.assessment_wizard_dialog import QassessmentWizardDialog
def spanish_wizard():
    dlg = QassessmentWizardDialog(parent=mf, iface=iface, executor=AssessmentExecutor("demo", am, pid))
    dlg.show()
    title_ok = dlg.windowTitle() == "Asistente de evaluación"
    combo = dlg.tableWidget_layers.cellWidget(0, 2)
    combo_labels = [combo.itemText(i) for i in range(combo.count())]
    dlg.lineEdit_name.setText("es_run")
    for row in range(dlg.tableWidget_layers.rowCount()):
        nm = dlg.tableWidget_layers.item(row, 0).text(); cb = dlg.tableWidget_layers.cellWidget(row, 2)
        dlg._set_status(cb, dlg.STATUS_TARGET if nm == "parcelas" else dlg.STATUS_INCLUDE)
    # Only-one-target rule still enforced with translated labels:
    cb_other = dlg.tableWidget_layers.cellWidget(1, 2); dlg._set_status(cb_other, dlg.STATUS_TARGET)
    one_target = sum(dlg._status_of(dlg.tableWidget_layers.cellWidget(r, 2)) == dlg.STATUS_TARGET for r in range(2)) == 1
    for row in range(dlg.tableWidget_layers.rowCount()):
        nm = dlg.tableWidget_layers.item(row, 0).text(); cb = dlg.tableWidget_layers.cellWidget(row, 2)
        dlg._set_status(cb, dlg.STATUS_TARGET if nm == "parcelas" else dlg.STATUS_INCLUDE)
    dlg.next(); page2 = dlg.currentId(); target_lbl = dlg.label_target_layer_name.text()
    dlg.select_all_features(); count_lbl = dlg.label_selection_count.text()
    dlg.next(); page3 = dlg.currentId(); summary = dlg.label_complexity_summary.text()
    status_cell = dlg.tableWidget_summary_layers.item(0, 2).text()
    dlg.accept(); res = dlg.get_results()
    return title_ok, combo_labels, one_target, page2, page3, target_lbl, count_lbl, summary, status_cell, res
out = step("spanish wizard", spanish_wizard)
if out:
    title_ok, combo_labels, one_target, page2, page3, target_lbl, count_lbl, summary, status_cell, res = out
    check("es wizard: title", title_ok)
    import json
    ES = json.load(open(os.path.join(os.environ["PLUGROOT"], "q_assessment_wizard", "ui", "i18n", "translations", "es.json")))["dialog"]
    expected = [ES['status_do_not_include'], ES['status_include'], ES['status_target'], ES['status_spatial_marker']]
    check("es wizard: status labels translated", combo_labels == expected and combo_labels[2] != 'Include as Target', str(combo_labels))
    check("es wizard: single-target rule works with translated labels", one_target)
    check("es wizard: reached pages 2 and 3", page2 == 1 and page3 == 2, f"{page2},{page3}")
    check("es wizard: page 2/3 labels translated",
          target_lbl == ES['lbl_target_layer'].format(name='parcelas')
          and count_lbl == ES['lbl_selected_count'].format(count=3)
          and summary.splitlines()[0] == ES['summary_easy_complex'], f"{target_lbl} | {count_lbl} | {summary}")
    check("es wizard: page 3 shows translated status", status_cell in (ES['status_target'], ES['status_include']), status_cell)
    check("es wizard: full analysis ran", bool(res) and res['output_tables'] == ['demo__es_run__v1'], str(res and res.get('output_tables')))
check("es: executor/migration messages translated", any(m[1] == "Evaluación completada" for m in msgs) and any(m[1] == "Migración exitosa" or "migr" in m[1].lower() for m in msgs), str([m[1] for m in msgs[-4:]]))
for code, expected in (("pt", "🗂 Novo projeto"), ("de", "🗂 Neues Projekt"), ("en", "🗂 New Project")):
    mf.language_combo.setCurrentIndex(mf.language_combo.findData(code))
    check(f"{code}: panel translated", mf.btn_new_project.text() == expected, mf.btn_new_project.text())
check("language persisted in (isolated) settings", QSettings().value("q_assessment_wizard/language") == "en", str(QSettings().value("q_assessment_wizard/language")))

# ── 7b. Layer migration use cases (incl. cancel) ───────────────────────────
from q_assessment_wizard.core.application import OperationCancelled
from q_assessment_wizard.ui.wizard.layer_migration import LayerMigrationService
extra = mk("extra_layer", ["POLYGON((10 10,11 10,11 11,10 11,10 10))"])
both = {"parcelas": target, "extra_layer": extra}
existing = step("existing_layers", lambda: ex.existing_layers(both))
check("migration: detects already-migrated layer only", existing == ["parcelas"], str(existing))
def cancel_cb(i, total, name, msg): raise OperationCancelled()
try:
    ex.migrate_layers({"extra_layer": extra}, cancel_cb); check("migration: cancel propagates OperationCancelled", False)
except OperationCancelled:
    check("migration: cancel propagates OperationCancelled", True)
check("migration: cancelled layer was not migrated", ex.existing_layers({"extra_layer": extra}) == [])
summary = step("migrate_layers", lambda: ex.migrate_layers({"extra_layer": extra}))
check("migration: summary counts", summary and summary['inserted'] == 1 and not summary['failed'], str(summary))
from qgis.PyQt.QtWidgets import QProgressDialog
orig_wc = QProgressDialog.wasCanceled
QProgressDialog.wasCanceled = lambda self: True
msgs.clear(); extra2 = mk("extra_two", ["POLYGON((12 12,13 12,13 13,12 13,12 12))"])
ok = LayerMigrationService(ex).migrate_selected_layers({"extra_two": extra2})
QProgressDialog.wasCanceled = orig_wc
check("migration UI: Cancel shows 'cancelled' (not errors) and returns False",
      ok is False and any(m[1] == translator.tr('dialog.mig_user_cancel_title') for m in msgs)
      and not any(m[1] == translator.tr('dialog.mig_error_title') for m in msgs), str(msgs))

# ── 7c. Explorer facade / catalog use cases ────────────────────────────────
fc = mf.facade
try:
    fc.update_weights(aid, {"riesgo": 0.9}); check("weights: 90% rejected by UpdateWeights", False)
except ValueError as e:
    check("weights: 90% rejected by UpdateWeights", "100%" in str(e), str(e))
check("weights: 100% accepted", fc.update_weights(aid, {"riesgo": 1.0}) == {"riesgo": 1.0})
check("weights: stored and visible in details", fc.assessment_details(aid)['weights'] == {"riesgo": 1.0})
try:
    fc.create_project("   "); check("create_project: empty name rejected", False)
except ValueError:
    check("create_project: empty name rejected", True)
tree_rm = fc.project_tree()
demo = next(p for p in tree_rm if p['name'] == 'demo')
ov = next(a for a in demo['assessments'] if a['name'] == 'overlay')
check("read model: analysis tables from provenance (v1, v2)", sorted(ov['analysis_tables']) == sorted([v1, v2]), str(ov['analysis_tables']))
check("read model: base layers listed", any(b['layer_name'] == 'parcelas' for b in demo['base_layers']), str(demo['base_layers'])[:120])
check("summary: assessment count", fc.project_summary(pid)['assessment_count'] == len(demo['assessments']))
check("executor.find_assessment_id", ex.find_assessment_id("overlay") == aid and ex.find_assessment_id("nope") is None)
wiz = QassessmentWizardDialog(parent=mf, iface=iface, executor=AssessmentExecutor("demo", am, pid))
wiz.lineEdit_name.setText("overlay"); wiz._on_name_editing_finished()
check("wizard: existing name → new-version mode with the right assessment id",
      wiz._creating_new_version and wiz._existing_assessment_id == aid, f"{wiz._creating_new_version} {wiz._existing_assessment_id}")
wiz.reject()
from qgis.PyQt.QtWidgets import QTreeWidgetItemIterator as _It
from q_assessment_wizard.ui.panels import WeightsEditDialog
wd = WeightsEditDialog(aid, fc); spin = next(iter(wd._spinboxes.values())); spin.setValue(50); msgs.clear(); wd._on_save()
check("weights dialog: 50% blocked (dialog stays open, warning)", wd.result() == 0 and any(m[0] == 'warning' for m in msgs), str(msgs))
# panel → weights editor (lazy relative import inside CatalogActionsMixin._on_edit_weights)
opened = []
_orig_wd_exec = WeightsEditDialog.exec
WeightsEditDialog.exec = lambda self: opened.append(self) or 0
step("panel: edit weights opens the editor", lambda: mf._on_edit_weights(aid))
WeightsEditDialog.exec = _orig_wd_exec
check("panel: weights editor opened for the assessment", len(opened) == 1, str(opened))

# ── 8. delete portfolio, unload ────────────────────────────────────────────
items_by_type().get('portfolio') and step("delete portfolio", lambda: mf._on_delete_portfolio(items_by_type()['portfolio'][0]))
check("portfolio deleted", am.get_portfolios_for_assessment(aid) == [] and not items_by_type().get('portfolio'))
step("unload", plugin.unload)
print("\nRESULT:", "ALL PASS" if not FAILS else f"{len(FAILS)} FAIL: {FAILS}")
# Skip interpreter finalization: tearing down Qt/QGIS objects in GC order
# intermittently segfaults (rc 134/139) after all checks have already run.
sys.stdout.flush(); sys.stderr.flush()
os._exit(1 if FAILS else 0)
