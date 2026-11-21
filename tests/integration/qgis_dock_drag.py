# -*- coding: utf-8 -*-
"""Integration test (needs QGIS 4 Python): dragging dock widgets must not crash.

QGIS 4.0.3 / Qt 6.9.3 segfaults in QWidgetAnimator::animate when docks are
dragged with QMainWindow animations on; the plugin disables them while
loaded. Usage: qgis_dock_drag.py plugin <rounds>   (or `plain` for the bare
Qt reproduction, which is expected to crash with VARIANT=none).
"""
import sys, os, faulthandler; faulthandler.enable()
from qgis.core import QgsApplication
app = QgsApplication([], True); app.initQgis()
from qgis.PyQt.QtWidgets import QMainWindow, QDockWidget, QTextEdit, QStyleFactory, QApplication
from qgis.PyQt.QtCore import Qt, QPoint
from qgis.PyQt.QtTest import QTest
print("styles", QStyleFactory.keys(), "current", app.style().name())
mode = sys.argv[1]
mw = QMainWindow(); mw.resize(1200, 800); mw.setCentralWidget(QTextEdit())
for i, area in enumerate([Qt.DockWidgetArea.LeftDockWidgetArea]*2 + [Qt.DockWidgetArea.RightDockWidgetArea]):
    d = QDockWidget(f"QGIS dock {i}", mw); d.setObjectName(f"d{i}"); d.setWidget(QTextEdit()); mw.addDockWidget(area, d)
if mode == "plugin":
    sys.path.insert(0, os.environ["PLUGROOT"])
    class I: pass
    iface=I(); iface.mainWindow=lambda: mw; iface.addDockWidget=mw.addDockWidget; iface.removeDockWidget=mw.removeDockWidget
    iface.addToolBarIcon=iface.removeToolBarIcon=lambda a: None; iface.addPluginToMenu=iface.removePluginMenu=lambda m,a: None
    from qgis.gui import QgsMapCanvas; c=QgsMapCanvas(); iface.mapCanvas=lambda: c; iface.messageBar=lambda: None
    import q_assessment_wizard as pkg
    plugin = pkg.classFactory(iface); plugin.initGui(); mw.show(); QTest.qWait(50); plugin.run(); dock = plugin.dock
else:
    dock = QDockWidget("plain", mw); dock.setObjectName("plain"); dock.setWidget(QTextEdit()); mw.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock); mw.show()
QTest.qWait(300)
variant = os.environ.get("VARIANT","none")
from qgis.PyQt.QtWidgets import QProxyStyle, QStyle
class NoAnim(QProxyStyle):
    def styleHint(self, hint, opt=None, w=None, ret=None):
        if hint == QStyle.StyleHint.SH_Widget_Animation_Duration: return 0
        return super().styleHint(hint, opt, w, ret)
if variant == "A": mw.setAnimated(False)
if variant == "B": dock._st = NoAnim(); dock.setStyle(dock._st)
if variant == "C": app.setStyle(NoAnim())
print("variant", variant, "style", app.style().name(), "animated", mw.isAnimated(), "dur", app.style().styleHint(QStyle.StyleHint.SH_Widget_Animation_Duration), flush=True)
def drag(dock, targets):
    tb = dock.titleBarWidget() or dock
    start = QPoint(20, 8)
    QTest.mousePress(dock, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    for tgt in targets:
        local = dock.mapFromGlobal(mw.mapToGlobal(tgt))
        QTest.mouseMove(dock, local); QTest.qWait(15)
    local = dock.mapFromGlobal(mw.mapToGlobal(targets[-1]))
    QTest.mouseRelease(dock, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, local); QTest.qWait(250)
path = []
for k in range(60): path.append(QPoint(10 + (k*19) % 1180, 40 + (k*37) % 740))
for rnd in range(int(sys.argv[2])):
    drag(dock, path[rnd % 7::3] + [QPoint(5, 400), QPoint(1195, 400), QPoint(600, 795)])
    if rnd % 1 == 0: print("round", rnd, "floating", dock.isFloating(), "area", mw.dockWidgetArea(dock), flush=True)
print("NO CRASH", mode)
if mode == "plugin":
    plugin.admin_manager.create_project("p1","x"); plugin.main_form._populate_tree()
    other = mw.findChild(QDockWidget, "d0")
    for rnd in range(15): drag(other, path[rnd % 5::4] + [QPoint(1195, 300)])
    print("dragged QGIS dock too; animated while loaded:", mw.isAnimated())
    plugin.unload(); print("after unload animated:", mw.isAnimated())
