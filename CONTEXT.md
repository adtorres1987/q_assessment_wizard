# Assessment Wizard — Project Context

**Last updated:** 2026-02-19
**Plugin:** QGIS 3 Python plugin (PyQGIS + SpatiaLite)
**Repo:** https://github.com/adtorres1987/q_assessment_wizard
**Detailed reference:** `architecture.md` · `docs/sql_schemas.md` · `EMDS8_ADAPTATION_NOTES.md`

---

## What This Plugin Does

A QGIS wizard that lets field ecologists run **spatial overlay assessments** (intersection + union) on vector layers, track results with **Git-like immutable versioning**, and navigate project history via a tree view. Based on the EMDS 3 model (Steve): Project → Assessment → Provenance → Work Close Steps.

---

## Architecture at a Glance

```
UI Layer          main_form.py · assessment_wizard_dialog.py
     ↓
Facade Layer      assessment_executor.py  (Commands → Use Cases, QMessageBox on error)
     ↓
Application       core/application/use_cases/  (business logic, no QGIS imports)
     ↓
Domain            core/domain/models/  (pure Python, zero framework imports)
     ↓
Infrastructure    SpatialEngine · AdminManager · ProjectManager
```

**Two databases:**
- `admin.sqlite` — central metadata (projects, assessments, provenance, tasks)
- `projects/{name}.sqlite` — per-project SpatiaLite (layers, versioned spatial tables)

**Table naming convention:** `{project_id}__{assessment_name}__v{n}`
Double underscore `__` is the separator; `sanitize_table_name()` preserves it.

---

## Implementation Status

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | SpatialEngine facade, decouple UI from SQL | ✅ Done |
| 2 | Domain models: Project, Scenario, SpatialVersion | ✅ Done |
| 3 | Immutable versioning (spatial_versions + HEAD pointer) | ✅ Done |
| 4 | Use cases: CreateScenario, ApplyOverlay, RollbackVersion, CompareVersions | ✅ Done |
| 5 | UI git-like redesign: VersionHistoryPanel, tree navigation | 🔄 In progress |

**Recently added (2026-02-19):**
- `get_assessment(assessment_id)` in `admin_manager.py`
- `rerun_spatial_assessment()` + `record_new_version()` in `assessment_executor.py`
- `allow_rerun: bool` flag in `ApplyOverlayCommand` + `ApplyOverlay._validate()`
- "New Version" context menu on assessment tree node (`main_form.py`)
- **Option B flow** in wizard: duplicate name → `editingFinished` → ask for v2+ → repopulate table with Output Layers (blue background)

---

## Key Files

| File | Responsibility |
|------|---------------|
| `assessment_wizard.py` | Plugin lifecycle, toolbar, `run()` |
| `main_form.py` | Tree view (EMDSTreeModel), VersionHistoryPanel, CRUD actions |
| `assessment_wizard_dialog.py` | 3-page wizard UI (name → layers → map selection) |
| `assessment_executor.py` | Thin facade: builds Commands, catches errors, shows QMessageBox |
| `admin_manager.py` | All admin.sqlite CRUD (projects, assessments, provenance, tasks, etc.) |
| `project_manager.py` | SpatiaLite CRUD: layer migration, spatial_versions table, sanitize_table_name |
| `core/spatial_engine/engine.py` | `SpatialEngine` public API: `prepare_layer()`, `overlay()`, `rollback_to_version()`, `get_versions()` |
| `core/application/use_cases/apply_overlay.py` | Versioned spatial overlay use case |
| `core/application/use_cases/commands.py` | Input DTOs for all 4 use cases |
| `spatial_analysis_spatialite.py` | `SpatialAnalyzerLite` — SQL overlay queries (called by `operations.py`) |

---

## Versioning Model (Git-like)

```
scenario_name = "proj__erosion"   ← branch name (base table name)
v1: spatial_versions.id=1, is_current=0  → table proj__erosion__v1
v2: spatial_versions.id=2, is_current=1  → table proj__erosion__v2  ← HEAD
```

- **Rollback** = O(1) UPDATE on `is_current` — no spatial recalculation
- **New version** = `engine.overlay()` auto-increments: counts existing versions → creates `__v{n+1}`
- **Compare** = loads 2 versions as separate QGIS layers without moving HEAD

---

## New Version Flow (Wizard — Option B)

```
User types existing assessment name in wizard
  → editingFinished → _on_name_editing_finished()
    → Detects duplicate immediately
    → QMessageBox: "Create new version (v2+)?"
      → Yes: _creating_new_version=True
             populate_layers() + _add_output_layers_to_table()
             Table shows: Base Layers (white) + Output Layers (light blue)
      → No:  clear name field, set focus

User configures layers → Finish → accept()
  → Skips name uniqueness check (allow_rerun=True)
  → execute_spatial_assessment(..., allow_rerun=True)
    → ApplyOverlay._validate() skips name check
    → engine.overlay() creates __v{n+1}
  → record_new_version(existing_assessment_id, results)
    → Adds output layers to existing assessment (no new assessment record)
    → Records provenance + task_details
```

Also available via context menu: right-click assessment → "New Version" → `rerun_spatial_assessment()` (re-runs with same stored layers, no wizard).

---

## Wizard Layer Selection Rules

- **Normal flow (v1):** table shows only "Base Layers" QGIS group
- **New version (v2+):** table also shows "Output Layers" group (light blue background)
- Target layer: defines spatial extent — one only, enforced by `on_status_changed()`
- Assessment layers: overlay inputs — one or more
- Simple assessment (target only, no assessment layers) → memory layer, no versioning

---

## Key Patterns

```python
# Context manager for SpatialEngine
with SpatialEngine(db_path) as engine:
    table = engine.prepare_layer(qgs_layer)
    result = engine.overlay(target_table, assessment_table, base_name)

# Command pattern
cmd = ApplyOverlayCommand(
    assessment_name=name, project_id=project_id,
    target_layer=target, assessment_layers=layers,
    allow_rerun=False,   # True for v2+
)
result = ApplyOverlay(admin_manager).execute(cmd)

# Sanitize table name (preserves __ separator)
table = project_manager.sanitize_table_name("My Layer Name")
# → "my_layer_name"  (never "my___layer_name")
```

---

## Known Issues / Limitations

- `spatial_references` table exists in admin.sqlite but is never called from any use case (dead infrastructure, planned for multi-DB support)
- No PostgreSQL backend yet (`db_type` and `db_connection_string` fields reserved)
- No what-if scenario branching (is_scenario flag exists, no UI)
- `rerun_spatial_assessment()` (context menu path) re-runs with stored layer names — if base data has changed in QGIS, changes are NOT picked up (wizard path re-migrates, context menu path does not)

---

## Pending / Next Steps

- [ ] Display version label in wizard table for output layers (e.g. `erosion (v1) [Output]`)
- [ ] PostgreSQL backend activation
- [ ] Expose `spatial_references` in tree view
- [ ] Soft-delete UI (restore deleted projects/assessments)
- [ ] What-if scenario branching UI
- [ ] Chained assessment DAG visualization

---

## Development Notes

- QGIS layers read **only** from "Base Layers" group (+ "Output Layers" in v2+ mode)
- Output layers added to "Output Layers" QGIS group (not inside "Base Layers")
- DB credentials for dev: localhost / wizard_db / postgres / user123 / 5432 (PostgreSQL future)
- `SpatialAnalyzerLite.analyze_and_create_layer()` returns key `total_count` (not `total`)
- `re.sub(r'_{3,}', '__', ...)` in `sanitize_table_name()` collapses 3+ underscores to 2
