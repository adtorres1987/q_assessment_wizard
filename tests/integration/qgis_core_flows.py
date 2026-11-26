# -*- coding: utf-8 -*-
"""Integration test (needs QGIS 4 Python): projects, simple and spatial
assessments, versions (rerun / compare / rollback), MCDA, the wizard pages,
map tools, tree nodes and checkboxes, unload.

Run through tools/run_tests.sh (it sets PLUGROOT to a scratch copy).
"""
import sys, os, traceback
from qgis.core import QgsApplication, QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry
app = QgsApplication([], True); app.initQgis()
sys.path.insert(0, os.environ["PLUGROOT"])
from qgis.PyQt.QtWidgets import QMainWindow, QMessageBox
from qgis.gui import QgsMapCanvas
msgs=[]
for n in ("information","warning","critical"):
    setattr(QMessageBox, n, staticmethod(lambda *a, _n=n, **k: msgs.append((_n, a[1] if len(a)>1 else '', a[2] if len(a)>2 else '')) or QMessageBox.StandardButton.Ok))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
canvas = QgsMapCanvas()
class I: pass
iface=I(); iface._mw=QMainWindow(); iface.mainWindow=lambda: iface._mw; iface.mapCanvas=lambda: canvas
iface.messageBar=lambda: None; iface.addDockWidget=lambda a,d: None; iface.removeDockWidget=lambda d: None
iface.addToolBarIcon=iface.removeToolBarIcon=lambda a: None; iface.addPluginToMenu=iface.removePluginMenu=lambda m,a: None
import q_assessment_wizard as pkg
plugin = pkg.classFactory(iface); plugin.initGui(); plugin.run()
mf = plugin.main_form; am = plugin.admin_manager
FAILED = []
def step(name, fn):
    try: r = fn(); print("OK  ", name, "->", r if not isinstance(r, dict) else {k: (v if not hasattr(v,'name') else v.name()) for k,v in r.items() if k!='layer'}); return r
    except Exception: print("FAIL", name); FAILED.append(name); traceback.print_exc(file=sys.stdout); return None
pid = step("create_project", lambda: am.create_project("prueba_qgis4", "test"))
step("populate_tree", lambda: mf._populate_tree())
def mk(name, polys):
    l = QgsVectorLayer("Polygon?crs=EPSG:4326&field=nombre:string&field=valor:double", name, "memory")
    feats=[]
    for i,wkt in enumerate(polys):
        f=QgsFeature(l.fields()); f.setGeometry(QgsGeometry.fromWkt(wkt)); f.setAttributes([f"{name}{i}", float(i)]); feats.append(f)
    l.dataProvider().addFeatures(feats); QgsProject.instance().addMapLayer(l); return l
target = mk("parcelas", ["POLYGON((0 0,2 0,2 2,0 2,0 0))","POLYGON((2 0,4 0,4 2,2 2,2 0))"])
assess = mk("riesgo", ["POLYGON((1 1,3 1,3 3,1 3,1 1))"])
from q_assessment_wizard.ui.assessment_executor import AssessmentExecutor
ex = AssessmentExecutor("prueba_qgis4", am, pid)
target.selectAll()
step("simple assessment (CreateScenario)", lambda: ex.execute_simple_assessment("simple1", target, "d"))
r = step("spatial assessment (ApplyOverlay)", lambda: ex.execute_spatial_assessment("overlay1", target, [assess], "d"))
if r: step("record_assessment", lambda: ex.record_assessment({"assessment_name":"overlay1","description":"d","target_layer":"parcelas","assessment_layers":["riesgo"],"output_tables":r["output_tables"], **{k:v for k,v in r.items() if k not in('layer',)}}))
asmts = am.get_assessments_for_project(pid); print("assessments:", [(a.get('id'),a.get('name')) for a in asmts])
aid = next((a['id'] for a in asmts if a.get('name')=='overlay1'), None)
if aid:
    r2 = step("rerun (v2)", lambda: ex.rerun_spatial_assessment(aid))
    from q_assessment_wizard.core.infrastructure.spatial import SpatialEngine
    with SpatialEngine(am.get_project_db_path(pid)) as eng:
        scen = [n for n in ["prueba_qgis4__overlay1"]][0]; vers = eng.get_versions(scen); print("versions:", [(v['id'], v['table_name'], v.get('is_current')) for v in vers])
    if len(vers)>=2:
        step("compare_versions", lambda: ex.compare_versions(scen, vers[0]['id'], vers[1]['id']))
        step("rollback_to_version", lambda: ex.rollback_to_version(scen, vers[0]['id']))
    step("apply_mcda_score", lambda: ex.apply_mcda_score(aid, vers[-1]['table_name']))
step("populate_tree after", lambda: mf._populate_tree())
from q_assessment_wizard.ui.wizard.assessment_wizard_dialog import QassessmentWizardDialog
root = QgsProject.instance().layerTreeRoot(); g = root.addGroup("Base Layers")
for l in (target, assess): g.addLayer(l)
dlg = step("open wizard dialog", lambda: QassessmentWizardDialog(parent=mf, iface=iface, executor=AssessmentExecutor("prueba_qgis4", am, pid)))
if dlg:
    def walk():
        dlg.show(); dlg.populate_layers() if dlg.tableWidget_layers.rowCount()==0 else None
        dlg.lineEdit_name.setText("wizard1")
        for row in range(dlg.tableWidget_layers.rowCount()):
            nm = dlg.tableWidget_layers.item(row,0).text(); cb = dlg.tableWidget_layers.cellWidget(row,2)
            cb.setCurrentText(dlg.STATUS_TARGET if nm=="parcelas" else dlg.STATUS_INCLUDE)
        ids=[dlg.currentId()]
        dlg.next(); ids.append(dlg.currentId())
        dlg.select_all_features(); dlg.update_selection_count()
        dlg.zoom_in(); dlg.zoom_out(); dlg.zoom_to_layer(); dlg.toggle_rectangle_select(); dlg.toggle_pan(); dlg.clear_selection(); dlg.select_all_features()
        dlg.next(); ids.append(dlg.currentId())
        return ids
    step("wizard pages + tools", walk)
    def maptools():
        from qgis.gui import QgsMapMouseEvent
        from qgis.PyQt.QtCore import QEvent, QPoint, Qt
        from q_assessment_wizard.ui.wizard.map_tools import RectangleSelectTool, FeatureSelectionTool
        c = dlg.map_canvas or canvas; c.resize(400,400); c.setLayers([target]); c.setExtent(target.extent()); c.refresh()
        hits=[]
        t = RectangleSelectTool(c, target, lambda *a: hits.append(a)); c.setMapTool(t)
        mk_ev = lambda typ, x, y, mods=Qt.KeyboardModifier.NoModifier: QgsMapMouseEvent(c, typ, QPoint(x,y), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, mods)
        t.canvasPressEvent(mk_ev(QEvent.Type.MouseButtonPress, 10, 10))
        t.canvasMoveEvent(mk_ev(QEvent.Type.MouseMove, 300, 300))
        t.canvasReleaseEvent(mk_ev(QEvent.Type.MouseButtonRelease, 300, 300, Qt.KeyboardModifier.ShiftModifier))
        t.canvasPressEvent(mk_ev(QEvent.Type.MouseButtonPress, 100, 100)); t.canvasReleaseEvent(mk_ev(QEvent.Type.MouseButtonRelease, 100, 100))
        t.deactivate()
        f = FeatureSelectionTool(c, target, lambda *a: hits.append(a))
        f.canvasReleaseEvent(mk_ev(QEvent.Type.MouseButtonRelease, 100, 100))
        return f"callbacks={len(hits)} selected={target.selectedFeatureCount()}"
    step("map tools (rect + click, shift)", maptools)
    def finish():
        dlg.accept(); return dlg.get_results()
    step("wizard accept (full run)", finish)
step("display_results + tree", lambda: (mf._populate_tree(), [(a['id'],a['name']) for a in am.get_assessments_for_project(pid)]))
def tree_walk():
    from qgis.PyQt.QtWidgets import QTreeWidgetItemIterator
    from qgis.PyQt.QtCore import Qt
    mf._populate_tree(); seen=[]; it=QTreeWidgetItemIterator(mf.tree)
    items=[]
    while it.value(): items.append(it.value()); it += 1
    for item in items:
        item.setExpanded(True); mf.tree.setCurrentItem(item)
        t = item.data(0, Qt.ItemDataRole.UserRole); seen.append(t)
        if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
            before=item.checkState(0); mf._toggle_result_visibility(item); seen.append(f"toggle {before.name}->{item.checkState(0).name}")
    return seen
step("tree walk + detail panels + checkboxes", tree_walk)
step("unload", plugin.unload)
print("MESSAGES:"); [print("  ", m) for m in msgs]
print("\nRESULT:", "ALL PASS" if not FAILED else f"{len(FAILED)} FAIL: {FAILED}")
# Skip interpreter finalization: tearing down Qt/QGIS objects in GC order
# intermittently segfaults (rc 134/139) after all checks have already run.
sys.stdout.flush(); sys.stderr.flush()
os._exit(1 if FAILED else 0)
