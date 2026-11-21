# -*- coding: utf-8 -*-
"""Find Qt/QGIS attribute chains (e.g. ``Qt.Checked``) that do not exist in the
running Qt — typically PyQt5-style unscoped enums that break on PyQt6.

    <QGIS python> tools/check_qt6_enums.py [plugin_root]

Needs the QGIS Python (qgis + PyQt importable). ``uic.loadUiType`` is a known
false positive (submodule not imported by the scanner).
"""
import ast, sys, os, importlib
root = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
mods = {"qgis.PyQt.QtCore","qgis.PyQt.QtGui","qgis.PyQt.QtWidgets","qgis.core","qgis.gui","PyQt5.QtCore","PyQt5.QtGui","PyQt5.QtWidgets"}
def mapmod(m): return m.replace("PyQt5","qgis.PyQt")
results = {}
for dp, dn, fn in os.walk(root):
    if any(x in dp for x in ("/tests", "/tools", "__pycache__", ".git")): continue
    for f in fn:
        if not f.endswith(".py"): continue
        p = os.path.join(dp,f); src = open(p).read()
        tree = ast.parse(src)
        names = {}
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module in mods:
                for a in n.names: names[a.asname or a.name] = (mapmod(n.module), a.name)
            if isinstance(n, ast.ImportFrom) and n.module in ("qgis.PyQt","PyQt5"):
                for a in n.names: names[a.asname or a.name] = ("qgis.PyQt", a.name)
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute):
                chain=[]; cur=n
                while isinstance(cur, ast.Attribute): chain.append(cur.attr); cur=cur.value
                if isinstance(cur, ast.Name) and cur.id in names:
                    chain.append(cur.id); chain.reverse()
                    results.setdefault(".".join(chain), []).append((os.path.relpath(p,root), n.lineno, names[cur.id]))
bad = []
for expr, locs in sorted(results.items()):
    head = expr.split(".")[0]; mod, real = locs[0][2]
    try:
        obj = getattr(importlib.import_module(mod), real)
        for part in expr.split(".")[1:]: obj = getattr(obj, part)
    except Exception as e:
        bad.append((expr, locs))
bad = [b for b in bad if b[0] != "uic.loadUiType"]
for expr, locs in bad:
    print(expr, "  ->", ", ".join(f"{a}:{b}" for a,b,_ in locs))
print("TOTAL BAD", len(bad), "of", len(results))
sys.exit(1 if bad else 0)
