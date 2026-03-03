# Assessment Wizard — Project Context

**Last updated:** 2026-02-25
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
- `admin.sqlite` — central metadata (projects, assessments, provenance, tasks, analyses, weights)
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
| 4 | Use cases: CreateScenario, ApplyOverlay, RollbackVersion | ✅ Done |
| 5 | UI redesign: flat tree + detail panels + weight history | ✅ Done |

**Recently added (2026-02-25):**
- Flat EMDS tree: Project → Base Layers + Assessments → ⚙ Weights + 🔁 Analysis v{n}
- Removed Compare and Settings buttons (not implemented)
- QGIS layer groups: all versions of an assessment stay in one flat group (no subgroup for v2+)
- Provenance naming: `name="Run v{n}"`, `description="Base spatial analysis: union + intersection"`
- Weight history via `snapshot_analysis_for_version()` — immutable `v{n}` rows in `analyses`
- Multi-layer overlay: assessment inputs merged via UNION ALL → single output table
- New schema tables: `analyses`, `assessment_criteria`, `analysis_weights`, `analysis_results`
- `_drop_unused_tables()` removes `spatial_references`, `analysis_comparisons`, `workflow_steps`, `analysis_configurations`

---

## Key Files

| File | Responsibility |
|------|---------------|
| `assessment_wizard.py` | Plugin lifecycle, toolbar, `run()` |
| `main_form.py` | Tree view, stacked detail panel, CRUD actions |
| `assessment_wizard_dialog.py` | 3-page wizard UI (name → layers → map selection) |
| `assessment_executor.py` | Thin facade: builds Commands, catches errors, shows QMessageBox |
| `admin_manager.py` | All admin.sqlite CRUD (projects, assessments, provenance, analyses, weights, etc.) |
| `project_manager.py` | SpatiaLite CRUD: layer migration, spatial_versions table, sanitize_table_name |
| `core/spatial_engine/engine.py` | `SpatialEngine` public API: `prepare_layer()`, `overlay()`, `rollback_to_version()`, `get_versions()` |
| `core/application/use_cases/apply_overlay.py` | Versioned spatial overlay use case (wizard path) |
| `core/application/use_cases/commands.py` | Input DTOs for all use cases |
| `ui/panels/emds_tree_model.py` | `EMDSTreeModel.populate_tree()` — builds the EMDS tree |
| `ui/panels/assessment_detail_panel.py` | Assessment card: target layer, input layers, weights, Edit Weights button |
| `ui/panels/analysis_detail_panel.py` | Analysis card: output table, run date, snapshot weights; `WeightsEditDialog` |
| `ui/panels/version_history_panel.py` | Version history panel (reserved for future use) |

---

## Tree Structure

```
📁 Project
├── 📁 Base Layers
│    └── {layer_name}
├── 📁 Assessment A
│    ├── ⚙ Weights           (type='weights', ROLE_ID=assessment_id)
│    │    └── layer: pct%
│    ├── 🔁 Analysis v1      (type='analysis', checkable)
│    └── 🔁 Analysis v2
└── 📁 Assessment B
     ├── ⚙ Weights
     └── 🔁 Analysis v1
```

**Node types:** `project`, `base_layers_group`, `base_layer`, `assessment`, `weights`, `analysis`

**Detail panel routing (QStackedWidget):**

| Selected node | Stack index | Panel |
|---|---|---|
| `assessment`, `weights` | 0 | `AssessmentDetailPanel` |
| `project`, `base_layers_group`, `base_layer` | 1 | plain text |
| `analysis` | 2 | `AnalysisDetailPanel` |

---

## Versioning Model (Git-like)

```
base_name = "proj__erosion"           ← base table name
v1: spatial_versions row, is_current=0  → table proj__erosion__v1
v2: spatial_versions row, is_current=1  → table proj__erosion__v2  ← HEAD
```

- **Rollback** = O(1) UPDATE on `is_current` — no spatial recalculation
- **New version** = `engine.overlay()` auto-increments via `len(get_versions(base_name)) + 1`
- Single base name per assessment regardless of number of input layers (multi-layer inputs are merged)

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
    → Records provenance (name="Run v{n}") + task_details
    → snapshot_analysis_for_version() captures weights for this run
```

Also available via context menu: right-click assessment → "New Version" → `rerun_spatial_assessment()` (re-runs with same stored layers, no wizard).

---

## Wizard Layer Selection Rules

- **Normal flow (v1):** table shows only "Base Layers" QGIS group
- **New version (v2+):** table also shows "Output Layers" group (light blue background)
- Target layer: defines spatial extent — one only, enforced by `on_status_changed()`
- Assessment layers: overlay inputs — one or more (merged via UNION ALL if multiple)

---

## Weight History Pattern

```
analyses rows:
  name='Default'  → mutable current config (user editable)
  name='v1'       → immutable snapshot of weights used in run 1
  name='v2'       → immutable snapshot of weights used in run 2
```

- `create_analysis_config()` — upserts the `Default` row
- `snapshot_analysis_for_version(assessment_id, output_table, v_num)` — creates immutable `v{n}` row + `analysis_results` link
- `get_analysis_for_output_table(output_table)` — returns snapshot row for a specific run
- `AnalysisDetailPanel.load()` reads snapshot first, falls back to Default config

---

## AssessmentExecutor Constructor

```python
AssessmentExecutor(project_id, admin_manager, project_db_id)
# project_id    = project name string (used as prefix in table names)
# project_db_id = integer PK in admin.sqlite projects table
```

---

## Key Patterns

```python
# Context manager for SpatialEngine
with SpatialEngine(db_path) as engine:
    table = engine.prepare_layer(qgs_layer)
    result = engine.overlay(target_table, assessment_table, base_name,
                            group_name=assessment_group,
                            layer_display_name=display_name)

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

# QGIS layer group — flat (no subgroups for v2+)
assessment_group = f"{seq:02d}_{assessment_name}"
```

---

## Known Issues / Limitations

- No PostgreSQL backend yet (`db_type` and `db_connection_string` fields reserved)
- No what-if scenario branching UI (`is_scenario` flag exists in `task_details`, no UI)
- `rerun_spatial_assessment()` (context menu path) re-runs with stored layer names — if base data has changed in QGIS, changes are NOT picked up (wizard path re-migrates, context menu path does not)
- `admin.sqlite` is not tracked by git (deleted from repo intentionally)

---

## Pending / Next Steps

- [ ] PostgreSQL backend activation
- [ ] Soft-delete UI (restore deleted projects/assessments)
- [ ] What-if scenario branching UI
- [ ] Chained assessment DAG visualization
- [ ] Display version label in wizard table for output layers (e.g. `erosion (v1) [Output]`)

---

## Development Notes

- QGIS layers read **only** from "Base Layers" group (+ "Output Layers" in v2+ mode)
- Output layers added to project-level QGIS group named `{seq:02d}_{assessment_name}` (flat, no nesting)
- `SpatialAnalyzerLite.analyze_and_create_layer()` returns key `total_count` (not `total`)
- `re.sub(r'_{3,}', '__', ...)` in `sanitize_table_name()` collapses 3+ underscores to 2
- `engine._repo.project_manager.connection` (not `engine._repo._conn`) for direct SQL access
- `ST_Area(geom)` not `ST_Area(geometry)` in SpatiaLite
- After `CREATE TABLE AS`, must call `RecoverGeometryColumn()` to register geometry
