# Assessment Wizard — Architecture Reference

> QGIS Plugin | Clean Architecture | SpatiaLite + Immutable Versioning
> Last updated: 2026-02-16

---

## 1. Overview

Assessment Wizard is a QGIS plugin for spatial overlay analysis and assessment management. It follows **Clean Architecture** principles with strict layer separation: UI, Application, Domain, and Infrastructure.

**Core capabilities:**
- Create and manage assessment projects
- Run versioned spatial overlay analysis (intersection + union) via SpatiaLite
- Track immutable version snapshots (Git-like)
- Rollback to any previous version — O(1), no spatial recalculation
- Compare two versions side-by-side as QGIS layers
- Persist all metadata in `admin.sqlite` (central) and per-project `.sqlite` files

---

## 2. File Tree

```
assessment_wizard/
├── __init__.py                          # Plugin entry point (classFactory)
├── assessment_wizard.py                 # Plugin class (QassessmentWizard)
├── assessment_wizard_dialog.py          # Multi-page wizard UI
├── assessment_executor.py               # Thin UI facade over use cases
├── admin_manager.py                     # Central metadata DB (admin.sqlite)
├── project_manager.py                   # Per-project SpatiaLite DB
├── spatial_analysis_spatialite.py       # Spatial SQL queries (overlay)
├── layer_migration.py                   # QGIS → SpatiaLite migration service
├── geometry_utils.py                    # CRS transformations, geometry helpers
├── map_tools.py                         # Custom QgsMapTools (click, rectangle)
├── main_form.py                         # Main form, tree model, version panel
├── resources.py                         # Qt compiled resources
│
├── core/
│   ├── application/
│   │   ├── __init__.py                  # Re-exports all use cases + commands
│   │   └── use_cases/
│   │       ├── __init__.py
│   │       ├── commands.py              # Command dataclasses (input DTOs)
│   │       ├── create_scenario.py       # CreateScenario use case
│   │       ├── apply_overlay.py         # ApplyOverlay use case
│   │       ├── rollback_version.py      # RollbackVersion use case
│   │       └── compare_versions.py      # CompareVersions use case
│   │
│   ├── domain/
│   │   └── models/
│   │       ├── layer_role.py            # LayerRole enum
│   │       ├── project.py               # Project entity
│   │       ├── scenario.py              # Scenario + LayerRef entities
│   │       └── spatial_version.py       # SpatialVersion entity
│   │
│   └── spatial_engine/
│       ├── __init__.py
│       ├── engine.py                    # SpatialEngine facade (context manager)
│       ├── operations.py                # OperationRunner + OverlayOperation enum
│       └── repository.py               # SpatialRepository (thin DB wrapper)
│
├── admin.sqlite                         # Central metadata database
└── projects/                            # Per-project SpatiaLite databases
    └── {project_name}.sqlite
```

---

## 3. Layer Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  UI LAYER                                                       │
│  main_form.py · assessment_wizard_dialog.py                     │
│  map_tools.py · geometry_utils.py · layer_migration.py         │
└──────────────────────────────┬──────────────────────────────────┘
                               │ UI events
┌──────────────────────────────▼──────────────────────────────────┐
│  THIN FACADE                                                    │
│  assessment_executor.py (AssessmentExecutor)                    │
│  Builds Commands · catches ValueError/RuntimeError · QMessageBox│
└──────────────────────────────┬──────────────────────────────────┘
                               │ Command dataclasses
┌──────────────────────────────▼──────────────────────────────────┐
│  APPLICATION LAYER — USE CASES                                  │
│  core/application/use_cases/                                    │
│  CreateScenario · ApplyOverlay · RollbackVersion · CompareVersions│
└──────────────────────────────┬──────────────────────────────────┘
                               │ domain objects + engine API
┌──────────────────────────────▼──────────────────────────────────┐
│  DOMAIN LAYER                                                   │
│  core/domain/models/                                            │
│  Project · Scenario · LayerRef · SpatialVersion · LayerRole     │
│  (no QGIS imports, no DB access)                                │
└──────────────────────────────┬──────────────────────────────────┘
                               │ storage + spatial ops
┌──────────────────────────────▼──────────────────────────────────┐
│  INFRASTRUCTURE LAYER                                           │
│  core/spatial_engine/  (SpatialEngine · OperationRunner · Repo) │
│  admin_manager.py      (AdminManager — admin.sqlite)            │
│  project_manager.py    (ProjectManager — project .sqlite)       │
│  spatial_analysis_spatialite.py  (SQL overlay queries)          │
└─────────────────────────────────────────────────────────────────┘
```

**Rule:** Higher layers never import lower layers directly. Use cases import `SpatialEngine` (facade), not `ProjectManager`. Domain has no framework dependencies.

---

## 4. Key Classes

### 4.1 UI Layer

| Class | File | Responsibility |
|-------|------|----------------|
| `QassessmentWizard` | `assessment_wizard.py` | Plugin lifecycle, toolbar icon, `run()` |
| `AssessmentMainForm` | `main_form.py` | Main dialog — tree + version panel + "New Assessment" |
| `EMDSTreeModel` | `main_form.py` | Populates 5-level EMDS QTreeWidget from admin.sqlite |
| `VersionHistoryPanel` | `main_form.py` | Git-like version list, HEAD marker (★), rollback/compare buttons |
| `QassessmentWizardDialog` | `assessment_wizard_dialog.py` | 3-page wizard: name → layers → map selection |
| `LayerMigrationService` | `layer_migration.py` | Migrates QGIS layers → SpatiaLite with progress dialog |
| `FeatureSelectionTool` | `map_tools.py` | Click-based feature selection (QgsMapTool) |
| `RectangleSelectTool` | `map_tools.py` | Rectangle drag-selection (QgsMapTool) |

**VersionHistoryPanel** emits two signals:
```python
rollback_requested = pyqtSignal(str, int)      # (scenario_name, version_id)
compare_requested  = pyqtSignal(str, int, int)  # (scenario_name, vid_a, vid_b)
```

**EMDSTreeModel tree levels:**
```
Project
  ├── Base Layers
  │     └── layer_name
  └── Assessments
        └── Assessment Name
              └── Provenance Name
                    └── Task (operation)
                          └── result_table_name  ← ROLE_SCENARIO_NAME stored here
```

---

### 4.2 Thin Facade

**`AssessmentExecutor`** (`assessment_executor.py`)

Translates UI events into use-case Commands and handles all exceptions:

| Method | Command built | Use case called |
|--------|--------------|-----------------|
| `execute_simple_assessment()` | `CreateScenarioCommand` | `CreateScenario` |
| `execute_spatial_assessment()` | `ApplyOverlayCommand` | `ApplyOverlay` |
| `rollback_to_version()` | `RollbackVersionCommand` | `RollbackVersion` |
| `compare_versions()` | `CompareVersionsCommand` | `CompareVersions` |

Additionally: `validate_assessment_name()`, `record_assessment()`, `_record_provenance()`.

---

### 4.3 Application Layer — Commands

All commands are `@dataclass` input DTOs in `core/application/use_cases/commands.py`:

```python
@dataclass
class CreateScenarioCommand:
    assessment_name: str
    description: str
    project_id: str
    project_db_id: int
    target_layer: object          # QgsVectorLayer

@dataclass
class ApplyOverlayCommand:
    assessment_name: str
    description: str
    project_id: str
    project_db_id: int
    target_layer: object          # QgsVectorLayer
    assessment_layers: List       # list[QgsVectorLayer]

@dataclass
class RollbackVersionCommand:
    scenario_name: str
    version_id: int
    project_db_id: int
    group_name: str = "Output Layers"

@dataclass
class CompareVersionsCommand:
    scenario_name: str
    version_id_a: int
    version_id_b: int
    project_db_id: int
    group_name: str = "Comparison"
```

---

### 4.4 Application Layer — Use Cases

| Use case | Validates | Engine call | Returns |
|----------|-----------|-------------|---------|
| `CreateScenario` | name unique, ≥1 selected feature | — (memory layer only) | `wizard_results` dict |
| `ApplyOverlay` | name unique, ≥1 assessment layer | `prepare_layer()` + `overlay()` | `wizard_results` dict |
| `RollbackVersion` | project_db_id valid | `rollback_to_version()` | `{table, version_id, layer}` |
| `CompareVersions` | project_db_id valid | `load_version()` × 2 | `{layer_a, layer_b, version_id_a, version_id_b}` |

**Error contract:**
Use cases raise `ValueError` (business rule violation) or `RuntimeError` (infrastructure failure). They never call `QMessageBox` — that responsibility belongs to `AssessmentExecutor`.

---

### 4.5 Domain Layer

| Class | File | Purpose |
|-------|------|---------|
| `LayerRole` | `layer_role.py` | Enum: `TARGET`, `ASSESSMENT`, `MARKER` |
| `Project` | `project.py` | Entity: name, db_path, db_type, base_layer_names |
| `LayerRef` | `scenario.py` | Immutable ref: name, role, table_name (post-migration) |
| `Scenario` | `scenario.py` | Aggregate: target_layer, assessment_layers, output_tables |
| `SpatialVersion` | `spatial_version.py` | Snapshot: scenario_id, table_name, is_current, parent_version_id |

Domain has **no QGIS imports**, no database access, no framework dependencies.

---

### 4.6 Infrastructure — SpatialEngine

**`SpatialEngine`** (`core/spatial_engine/engine.py`) — facade for all spatial operations:

```python
# Usage (context manager):
with SpatialEngine(db_path) as engine:
    table = engine.prepare_layer(qgs_layer)           # migrate if needed
    result = engine.overlay(target, assessment, name)  # versioned analysis
```

**Public API:**

| Method | Description |
|--------|-------------|
| `prepare_layer(qgs_layer)` | Migrate QGIS layer → SpatiaLite if not already there. Returns `table_name`. |
| `overlay(target, assessment, output_name, group_name)` | Run spatial overlay. Creates `output_name__v{n}` table. Returns `{table, version_id, layer}`. |
| `rollback_to_version(scenario_name, version_id, group_name)` | Move HEAD pointer. O(1). Returns `{table, version_id, layer}`. |
| `load_version(version_id, display_name, group_name)` | Load snapshot as read-only QGIS layer. No HEAD move. |
| `get_versions(scenario_name)` | All versions for scenario, newest first. |
| `get_current_version(scenario_name)` | HEAD version only. |
| `get_version_by_id(version_id)` | Single version by ID. |

**Internal structure:**
- `SpatialEngine` → delegates to `OperationRunner` (SQL ops) + `SpatialRepository` (storage)
- `SpatialRepository` → thin wrapper over `ProjectManager`

---

### 4.7 Infrastructure — Database Managers

**`AdminManager`** (`admin_manager.py`) — central `admin.sqlite`:

| Category | Key methods |
|----------|------------|
| Projects | `create_project()`, `get_all_projects()`, `delete_project()`, `purge_project()` |
| Assessments | `create_assessment()`, `get_assessments_for_project()`, `assessment_name_exists()` |
| Layers | `add_assessment_layer()`, `set_layer_visibility()`, `get_visible_layers()` |
| Provenance | `create_provenance()`, `add_task()`, `get_tasks_for_provenance()`, `build_task_tree()` |
| Settings | `get_app_setting()`, `set_app_setting()` |
| Utility | `get_project_db_path(project_id)` → absolute path to project's `.sqlite` |

**`ProjectManager`** (`project_manager.py`) — per-project `.sqlite` (SpatiaLite):

| Category | Key methods |
|----------|------------|
| Layers | `migrate_layer()`, `is_layer_registered()`, `register_base_layer()` |
| Tables | `table_exists()`, `drop_table()`, `rename_table()` |
| Versions | `create_version()`, `get_versions()`, `get_current_version()`, `set_current_version()` |
| Results | `record_result()`, `get_results_for_assessment()` |
| Utility | `sanitize_table_name()`, `get_spatialite_type()` |

---

## 5. Database Schemas

### 5.1 `admin.sqlite` (central metadata)

```sql
projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    db_path TEXT NOT NULL,            -- relative: projects/{name}.sqlite
    db_type TEXT DEFAULT 'spatialite',
    qgs_project_file TEXT,
    base_layer_names TEXT,            -- JSON array
    is_deleted INTEGER DEFAULT 0,
    created_at TEXT
)

assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE NOT NULL,
    project_id INTEGER NOT NULL,      -- FK → projects.id
    name TEXT NOT NULL,
    description TEXT,
    target_layer TEXT,
    is_deleted INTEGER DEFAULT 0,
    UNIQUE(project_id, name)
)

provenance (
    id, uuid, assessment_id,          -- FK → assessments.id
    name, description, created_at
)

task_details (
    id, uuid, provenance_id,          -- FK → provenance.id
    parent_task_id,                   -- FK → task_details.id (hierarchical)
    step_order, operation, category,
    input_tables TEXT,                -- JSON array
    output_tables TEXT,               -- JSON array
    engine_type TEXT,                 -- 'spatialite' | 'netweaver' | 'cdp'
    is_scenario INTEGER,              -- 1 = what-if scenario
    duration_ms INTEGER, parameters TEXT
)

layer_visibility_state (
    assessment_id, layer_name,        -- PK composite
    visible INTEGER DEFAULT 1
)

app_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),  -- single-row config
    default_base_layers_group TEXT,
    output_group_name TEXT,
    plugin_version TEXT
)
```

### 5.2 `projects/{name}.sqlite` (per-project SpatiaLite)

```sql
base_layers_registry (
    id, layer_name TEXT UNIQUE,
    geometry_type TEXT, srid INTEGER,
    feature_count INTEGER, created_at TEXT
)

spatial_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_name TEXT NOT NULL,      -- base name (no __v{n} suffix)
    table_name TEXT NOT NULL,         -- actual SpatiaLite table
    description TEXT,
    parent_version_id INTEGER,        -- FK → spatial_versions.id
    is_current INTEGER DEFAULT 1,     -- HEAD pointer: 1 = active
    created_at TEXT
)

-- Dynamic spatial tables (one per overlay result):
-- {project_id}__{assessment_name}__v{n}
-- Columns: id, input_id, identity_id, geom (GEOMETRY), split_type, shape_area, shape_length
```

---

## 6. Data Flow: Spatial Overlay

```
User clicks "Finish" in wizard
    │
    ▼
AssessmentExecutor.execute_spatial_assessment(name, target, assessment_layers)
    │   builds ApplyOverlayCommand
    ▼
ApplyOverlay.execute(cmd)
    │   validates name uniqueness + assessment_layers non-empty
    │   gets project_db_path from AdminManager
    ▼
SpatialEngine(project_db_path).__enter__()
    │
    ├── for each layer:
    │       engine.prepare_layer(qgs_layer)
    │           → SpatialRepository.ensure_layer()
    │           → ProjectManager.migrate_layer()
    │               AddGeometryColumn → INSERT features
    │               RecoverGeometryColumn → CreateSpatialIndex
    │
    └── for each assessment_layer:
            engine.overlay(target_table, assess_table, base_name)
                → version_num = len(get_versions(base_name)) + 1
                → versioned_name = base_name + "__v" + str(version_num)
                → OperationRunner.execute(target, assess, versioned_name, UNION)
                    → SpatialAnalyzerLite.analyze_and_create_layer()
                        ST_Intersection + ST_Union SQL
                → ProjectManager.create_version(scenario_name, versioned_name)
                → OperationRunner.create_qgis_layer() → adds to QGIS project
                → returns {table, version_id, layer}
    │
    ▼
ApplyOverlay returns wizard_results dict
    │
    ▼
AssessmentExecutor.record_assessment(wizard_results)
    │   AdminManager.create_assessment()
    │   AdminManager.create_provenance()
    │   AdminManager.add_task()
    ▼
QMessageBox.information("Assessment Complete")
```

---

## 7. Immutable Versioning

The versioning system is modeled after Git:

| Concept | Git | Assessment Wizard |
|---------|-----|-------------------|
| Repository | `.git/` | `projects/{name}.sqlite` |
| Commit | SHA hash | `spatial_versions.id` |
| Branch | `refs/heads/` | `scenario_name` |
| HEAD | pointer to latest | `is_current = 1` |
| Snapshot | tree objects | SpatiaLite table `{name}__v{n}` |
| Rollback | `git checkout` | `set_current_version()` → O(1) |

**Table naming convention:**
```
{project_id}__{assessment_name}__v{n}

Example:  forestproject__deforestation_2024__v3
          ├─────────────┘ ├────────────────────┘ └─┘
          project_id      assessment_name          version
```

`sanitize_table_name()` in `project_manager.py` preserves `__` separators using `re.sub(r'_{3,}', '__', ...)`.

---

## 8. Wizard Pages

```
Page 1 — Assessment Info
  Input: assessment_name, description
  Input: target_layer (QgsComboBox — layers from "Base Layers" group only)

Page 2 — Layer Selection
  TableWidget with all layers from "Base Layers" group
  Columns: Layer Name | Geometry Type | Status
  Status options: Target | Include | Spatial Marker | Do Not Include

Page 3 — Feature Selection (only if no assessment layers selected)
  Embedded QGIS map canvas
  FeatureSelectionTool (click) or RectangleSelectTool (drag)
  Selected features become the memory layer output
```

**Layer group constraint:** The wizard reads layers **only** from the `"Base Layers"` QGIS layer group (`QgsProject.layerTreeRoot().findGroup("Base Layers")`). Output layers are added to the project root (not inside any group) to avoid naming collisions.

---

## 9. Key Patterns

### Context managers for DB connections
```python
with SpatialEngine(db_path) as engine:
    ...
# Connection always closed, even on exception
```

### Soft vs. permanent delete
```python
admin_manager.delete_project(id)   # sets is_deleted=1, data preserved
admin_manager.purge_project(id)    # removes row + deletes .sqlite file
```

### Rollback is O(1)
```python
# No spatial recalculation. Just flips a flag.
UPDATE spatial_versions SET is_current = 0 WHERE scenario_name = ?
UPDATE spatial_versions SET is_current = 1 WHERE id = ?
```

### Command → Use Case boundary
```
# UI side (AssessmentExecutor):
cmd = ApplyOverlayCommand(...)
try:
    result = ApplyOverlay(admin_manager).execute(cmd)
except (ValueError, RuntimeError) as e:
    QMessageBox.critical(...)

# Use case side (no QMessageBox):
def execute(self, cmd):
    if not cmd.assessment_layers:
        raise ValueError("At least one assessment layer required.")
    ...
```

---

## 10. Extension Points

The schema includes fields that enable future capabilities:

| Field | Table | Future use |
|-------|-------|-----------|
| `db_type` | `projects` | PostgreSQL/PostGIS, Esri Geodatabase backends |
| `engine_type` | `task_details` | NetWeaver, CDP, LPA analysis engines |
| `is_scenario` | `task_details` | What-if / parametric scenarios |
| `parent_task_id` | `task_details` | Hierarchical task trees (DAG provenance) |
| `db_connection_string` | `projects` | Remote database connection strings |

---

## 11. Import Dependency Graph

```
assessment_wizard_dialog.py
  ├── geometry_utils.py          (leaf — only qgis.core)
  ├── map_tools.py               → geometry_utils.py
  ├── layer_migration.py         → project_manager.py
  └── assessment_executor.py
        └── core/application/
              └── use_cases/
                    └── core/spatial_engine/
                          └── spatial_analysis_spatialite.py

main_form.py
  ├── assessment_wizard_dialog.py (above)
  ├── admin_manager.py           → project_manager.py
  └── core/spatial_engine/       (VersionHistoryPanel lazy import)
```

No circular imports. Higher layers depend on lower layers, never the reverse.
