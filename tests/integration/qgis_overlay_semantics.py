# -*- coding: utf-8 -*-
"""Integration test (needs QGIS 4 Python): per-feature coverage of overlay outputs.

F-02 semantics: an overlay table stores only the intersection fragments (plus a
``no_overlap`` row for features with no positive-area intersection), and every
row carries ``source_area`` — the area of the original target feature. The
results grid derives from it:

    total_area      = source_area of the target feature
    intersect_area  = area of the UNION of its intersect fragments
                      (overlapping assessment polygons are not double counted)
    no_overlap_area = total_area - intersect_area
    coverage_pct    = intersect_area / total_area

Tables written before F-02 (no ``source_area`` column) keep the old formulas.

Run through tools/run_tests.sh (it sets PLUGROOT and SP to scratch dirs).
"""
import os, sys, traceback, sqlite3
SP = os.environ["SP"]
from qgis.PyQt.QtCore import QSettings, QCoreApplication
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, os.path.join(SP, "settings"))
QCoreApplication.setOrganizationName("qaw-test"); QCoreApplication.setApplicationName("qaw-test")

from qgis.core import QgsApplication, QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry
app = QgsApplication([], True); app.initQgis()
sys.path.insert(0, os.environ["PLUGROOT"])
from qgis.PyQt.QtWidgets import QMessageBox
for n in ("information", "warning", "critical"):
    setattr(QMessageBox, n, staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
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

def mk(name, polys):
    l = QgsVectorLayer("Polygon?crs=EPSG:4326&field=nombre:string", name, "memory")
    feats = []
    for i, wkt in enumerate(polys):
        f = QgsFeature(l.fields()); f.setGeometry(QgsGeometry.fromWkt(wkt)); f.setAttributes([f"{name}{i}"]); feats.append(f)
    l.dataProvider().addFeatures(feats); QgsProject.instance().addMapLayer(l); return l

def box(x0, y0, x1, y1):
    return f"POLYGON(({x0} {y0},{x1} {y0},{x1} {y1},{x0} {y1},{x0} {y0}))"

# Target features (input_id = insertion order):
#   1 A  4x4 (16)  covered by two OVERLAPPING zones → union 3x4 = 12 → 75 %
#   2 C  2x2 (4)   only shares an edge with a zone (zero-area contact) → 0 %
#   3 D  2x2 (4)   isolated → 0 %
#   4 E  2x2 (4)   half covered → 50 %
target = mk("lotes", [box(0, 0, 4, 4), box(10, 0, 12, 2), box(20, 0, 22, 2), box(30, 0, 32, 2)])
zones = mk("zonas", [box(0, 0, 2, 4), box(1, 0, 3, 4), box(12, 0, 14, 2), box(31, 0, 33, 2)])
strip = mk("franja", [box(-1, 0, 40, 1)])

from q_assessment_wizard.core.infrastructure.persistence.admin_manager import AdminManager
from q_assessment_wizard.ui.assessment_executor import AssessmentExecutor
am = AdminManager(os.path.join(os.environ["PLUGROOT"], "q_assessment_wizard")); am.connect()
pid = am.create_project("cov", "t")
ex = AssessmentExecutor("cov", am, pid)

def grid_rows(table):
    g = ex.get_results_grid(table)
    return {r[0]: dict(zip(g['columns'], r)) for r in g['rows']}

def near(a, b, tol=0.01):
    return a is not None and abs(a - b) < tol

# ── 1. one assessment layer ─────────────────────────────────────────────────
r1 = step("overlay with one layer", lambda: ex.execute_spatial_assessment("uno", target, [zones], "d"))
t1 = r1['output_tables'][0] if r1 else None
rows = step("grid (one layer)", lambda: grid_rows(t1)) or {}
check("every target feature has a row (incl. edge-only contact)", sorted(rows) == [1, 2, 3, 4], str(sorted(rows)))
expect = {1: (16, 12, 4, 75.0, 'High (>=75%)'),
          2: (4, 0, 4, 0.0, 'None (0%)'),
          3: (4, 0, 4, 0.0, 'None (0%)'),
          4: (4, 2, 2, 50.0, 'Medium (25-74%)')}
for fid, (total, inter, rest, pct, cls) in expect.items():
    r = rows.get(fid, {})
    ok = (near(r.get('total_area'), total) and near(r.get('intersect_area'), inter)
          and near(r.get('no_overlap_area'), rest) and near(r.get('coverage_pct'), pct)
          and r.get('coverage_class') == cls)
    check(f"feature {fid}: total {total}, covered {inter}, rest {rest}, {pct}% {cls}", ok, str(r))

series = step("histogram series", lambda: ex.get_comparison_series({"a": t1, "b": t1}, "coverage_pct"))
if series:
    check("histogram coverage_pct uses the same formula", sorted(round(v, 1) for v in series["a"]) == [0.0, 0.0, 50.0, 75.0], str(series["a"]))
series = step("histogram total_area", lambda: ex.get_comparison_series({"a": t1, "b": t1}, "total_area"))
if series:
    check("histogram total_area = original feature areas", sorted(round(v, 1) for v in series["a"]) == [4.0, 4.0, 4.0, 16.0], str(series["a"]))

# ── 2. two assessment layers (cumulative steps carry source_area) ─────────
r2 = step("overlay with two layers", lambda: ex.execute_spatial_assessment("dos", target, [zones, strip], "d"))
t2 = r2['output_tables'][0] if r2 else None
rows2 = step("grid (two layers)", lambda: grid_rows(t2)) or {}
check("two layers: every target feature has a row", sorted(rows2) == [1, 2, 3, 4], str(sorted(rows2)))
check("two layers: total_area is the original feature area",
      all(near(rows2.get(f, {}).get('total_area'), a) for f, a in {1: 16, 2: 4, 3: 4, 4: 4}.items()), str(rows2))
check("two layers: covered + rest = total, coverage within 0–100 %",
      all(near(r['intersect_area'] + r['no_overlap_area'], r['total_area']) and 0 <= r['coverage_pct'] <= 100
          for r in rows2.values()) and rows2, str(rows2))
check("two layers: A covered by zones ∩ strip = 3x1 → 18.75 %",
      near(rows2.get(1, {}).get('intersect_area'), 3) and near(rows2.get(1, {}).get('coverage_pct'), 18.8, 0.06), str(rows2.get(1)))

# ── 3. tables written before F-02 keep the old formulas ─────────────────────
db = am.get_project_db_path(pid)
def make_legacy():
    c = sqlite3.connect(db)
    c.execute(f'CREATE TABLE legacy_v1 AS SELECT input_id, identity_id, geom, split_type, shape_area, shape_length FROM "{t1}"')
    c.commit(); c.close()
step("legacy table (no source_area)", make_legacy)
legacy = step("grid (legacy table)", lambda: grid_rows("legacy_v1")) or {}
check("legacy: total = sum of stored fragments (16), 100 %",
      near(legacy.get(1, {}).get('total_area'), 16) and near(legacy.get(1, {}).get('coverage_pct'), 100.0), str(legacy.get(1)))

print("\nRESULT:", "ALL PASS" if not FAILS else f"{len(FAILS)} FAIL: {FAILS}")
sys.stdout.flush(); sys.stderr.flush()
os._exit(1 if FAILS else 0)
