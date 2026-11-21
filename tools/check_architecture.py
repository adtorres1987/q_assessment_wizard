# -*- coding: utf-8 -*-
"""Clean-architecture dependency rules, checked statically on imports.

    python3 tools/check_architecture.py [plugin_root]

No QGIS needed. Exits non-zero when a layer imports something it must not:
  core/domain          no QGIS, no Qt, no sqlite3; no application/infrastructure/ui
  core/application     no QGIS, no Qt, no sqlite3; no infrastructure/ui
  core/infrastructure  no Qt bindings directly; no ui
  ui                   no sqlite3; no infrastructure (except the composition
                       point ui/assessment_executor.py)
"""
import ast, os, sys
root = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORBIDDEN = {
    # layer prefix          : (forbidden external roots, forbidden internal prefixes)
    "core/domain":         ({"qgis", "PyQt5", "PyQt6", "sqlite3"}, ("core.application", "core.infrastructure", "ui", "plugin")),
    "core/application":    ({"qgis", "PyQt5", "PyQt6", "sqlite3"},
                            ("core.infrastructure", "ui", "plugin")),
    "core/infrastructure": ({"PyQt5", "PyQt6"}, ("ui", "plugin")),
    "ui":                  ({"sqlite3"}, ("core.infrastructure", "plugin")),
}
# Composition points allowed to wire infrastructure adapters into use cases.
ALLOWED = {"ui/assessment_executor.py": ("core.infrastructure",)}
def modname(path):
    return os.path.relpath(path, root)[:-3].replace(os.sep, ".")
def resolve(path, node):
    parts = modname(path).split(".")
    if not path.endswith("__init__.py"):
        parts = parts[:-1]
    if node.level > 1:
        parts = parts[:len(parts) - (node.level - 1)]
    return ".".join(parts + ([node.module] if node.module else []))
violations = 0
for layer, (ext_bad, int_bad) in FORBIDDEN.items():
    for dp, dn, fn in os.walk(os.path.join(root, layer)):
        dn[:] = [d for d in dn if d != "__pycache__"]
        for f in fn:
            if not f.endswith(".py"):
                continue
            p = os.path.join(dp, f)
            for node in ast.walk(ast.parse(open(p).read())):
                targets = []
                if isinstance(node, ast.Import):
                    targets = [(a.name, False) for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    targets = [(resolve(p, node) if node.level else node.module or "", bool(node.level))]
                for name, internal in targets:
                    top = name.split(".")[0]
                    rel = os.path.relpath(p, root)
                    if internal and name.startswith(ALLOWED.get(rel, ("\0",))):
                        continue
                    if (not internal and top in ext_bad) or (internal and name.startswith(int_bad)):
                        violations += 1
                        print(f"   VIOLATION {os.path.relpath(p, root)}:{node.lineno} imports {name}")
print(f"LAYER RULES: {violations} violation(s)")
sys.exit(1 if violations else 0)
