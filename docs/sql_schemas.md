# SQL Schemas, Table Relationships & Process Flow Diagrams

> Assessment Wizard Plugin — Technical Reference
> Last updated: 2026-02-17

---

## Table of Contents

1. [SQL Schemas](#1-sql-schemas)
   - 1.1 [admin.sqlite — Central Metadata](#11-adminsqlite--central-metadata)
   - 1.2 [projects/{name}.sqlite — Per-Project SpatiaLite](#12-projectsnamesqlite--per-project-spatialite)
   - 1.3 [Dynamic Spatial Tables](#13-dynamic-spatial-tables)
2. [Table Relationships](#2-table-relationships)
   - 2.1 [Entity-Relationship Diagram — admin.sqlite](#21-entity-relationship-diagram--adminsqlite)
   - 2.2 [Entity-Relationship Diagram — project.sqlite](#22-entity-relationship-diagram--projectsqlite)
   - 2.3 [Cross-Database Relationships](#23-cross-database-relationships)
   - 2.4 [Cardinality Reference](#24-cardinality-reference)
3. [Process Flow Diagrams](#3-process-flow-diagrams)
   - 3.1 [Flow 1: Spatial Assessment (ApplyOverlay)](#31-flow-1-spatial-assessment-applyoverlay)
   - 3.2 [Flow 2: Simple Assessment (CreateScenario)](#32-flow-2-simple-assessment-createscenario)
   - 3.3 [Flow 3: Rollback Version](#33-flow-3-rollback-version)
   - 3.4 [Flow 4: Compare Versions](#34-flow-4-compare-versions)
   - 3.5 [Flow 5: Project Creation](#35-flow-5-project-creation)
   - 3.6 [Flow 6: Metadata Recording (post-assessment)](#36-flow-6-metadata-recording-post-assessment)

---

## 1. SQL Schemas

### 1.1 `admin.sqlite` — Central Metadata

Source: `admin_manager.py` → `AdminManager._create_tables()`

```sql
-- ============================================================
-- PROJECTS — Top-level entity for each workspace
-- ============================================================
CREATE TABLE IF NOT EXISTS projects (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid                 TEXT    UNIQUE NOT NULL,
    name                 TEXT    NOT NULL UNIQUE,
    description          TEXT    DEFAULT '',
    db_path              TEXT    NOT NULL,              -- Relative: projects/{name}.sqlite
    created_at           TEXT    DEFAULT CURRENT_TIMESTAMP,
    is_deleted           INTEGER DEFAULT 0,             -- 0=active, 1=soft-deleted
    base_layer_names     TEXT    DEFAULT '',             -- JSON array of layer names
    db_type              TEXT    DEFAULT 'spatialite',   -- 'spatialite' | 'postgresql' | 'geodatabase'
    qgs_project_file     TEXT    DEFAULT '',             -- Path to linked .qgs/.qgz
    db_connection_string TEXT    DEFAULT '',             -- For remote DB backends
    workspace_paths      TEXT    DEFAULT ''              -- Additional workspace metadata
);

-- ============================================================
-- ASSESSMENTS — Each analysis run within a project
-- ============================================================
CREATE TABLE IF NOT EXISTS assessments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid            TEXT    UNIQUE NOT NULL,
    project_id      INTEGER NOT NULL,
    name            TEXT    NOT NULL,
    description     TEXT    DEFAULT '',
    target_layer    TEXT    DEFAULT '',                  -- Original QGIS layer name
    spatial_extent  TEXT    DEFAULT '',
    created_at      TEXT    DEFAULT CURRENT_TIMESTAMP,
    is_deleted      INTEGER DEFAULT 0,                  -- 0=active, 1=soft-deleted
    UNIQUE(project_id, name),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

-- ============================================================
-- ASSESSMENT_LAYERS — Layers participating in each assessment
-- ============================================================
CREATE TABLE IF NOT EXISTS assessment_layers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_id   INTEGER NOT NULL,
    layer_name      TEXT    NOT NULL,
    layer_type      TEXT    NOT NULL CHECK(layer_type IN ('input', 'output', 'reference')),
    geometry_type   TEXT    DEFAULT '',
    FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE CASCADE
);

-- ============================================================
-- LAYER_VISIBILITY_STATE — Per-assessment layer toggle state
-- ============================================================
CREATE TABLE IF NOT EXISTS layer_visibility_state (
    assessment_id   INTEGER NOT NULL,
    layer_name      TEXT    NOT NULL,
    visible         INTEGER DEFAULT 1,                  -- 1=visible, 0=hidden
    PRIMARY KEY (assessment_id, layer_name),
    FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE CASCADE
);

-- ============================================================
-- WORKFLOW_STEPS — Ordered operations within an assessment
-- ============================================================
CREATE TABLE IF NOT EXISTS workflow_steps (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_id   INTEGER NOT NULL,
    step_order      INTEGER NOT NULL,
    operation       TEXT    NOT NULL,
    parameters      TEXT    DEFAULT '',                  -- JSON or free text
    created_at      TEXT    DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE CASCADE
);

-- ============================================================
-- PROVENANCE — Named provenance records per assessment
-- ============================================================
CREATE TABLE IF NOT EXISTS provenance (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid            TEXT    UNIQUE NOT NULL,
    assessment_id   INTEGER NOT NULL,
    name            TEXT    NOT NULL,
    description     TEXT    DEFAULT '',
    created_at      TEXT    DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE CASCADE
);

-- ============================================================
-- TASK_DETAILS — Individual tasks within a provenance record
-- Supports hierarchical nesting via parent_task_id (DAG)
-- ============================================================
CREATE TABLE IF NOT EXISTS task_details (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid            TEXT    UNIQUE NOT NULL,
    provenance_id   INTEGER NOT NULL,
    parent_task_id  INTEGER DEFAULT NULL,               -- Self-referencing FK for tree
    step_order      INTEGER NOT NULL,
    operation       TEXT    NOT NULL,                    -- e.g. 'union+intersect', 'CDP'
    category        TEXT    DEFAULT '',
    input_tables    TEXT    DEFAULT '',                  -- JSON array
    output_tables   TEXT    DEFAULT '',                  -- JSON array
    db_type         TEXT    DEFAULT 'spatialite',
    added_to_map    INTEGER DEFAULT 1,
    scenario        TEXT    DEFAULT '',
    symbology       TEXT    DEFAULT '',
    duration_ms     INTEGER DEFAULT 0,
    parameters      TEXT    DEFAULT '',                  -- JSON or free text
    comments        TEXT    DEFAULT '',
    engine_type     TEXT    DEFAULT 'spatialite',        -- 'spatialite' | 'netweaver' | 'cdp' | 'lpa'
    is_scenario     INTEGER DEFAULT 0,                  -- 1 = what-if alternate scenario
    created_at      TEXT    DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (provenance_id)  REFERENCES provenance(id)    ON DELETE CASCADE,
    FOREIGN KEY (parent_task_id) REFERENCES task_details(id)  ON DELETE SET NULL
);

-- ============================================================
-- SPATIAL_REFERENCES — Overlay layer metadata per assessment
-- ============================================================
CREATE TABLE IF NOT EXISTS spatial_references (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid                TEXT    UNIQUE NOT NULL,
    assessment_id       INTEGER NOT NULL,
    name                TEXT    NOT NULL,
    overlay_layer_name  TEXT    DEFAULT '',              -- SpatiaLite table used as overlay
    source_tables       TEXT    DEFAULT '',              -- JSON array
    source_db_type      TEXT    DEFAULT 'spatialite',
    source_db_path      TEXT    DEFAULT '',
    srid                INTEGER DEFAULT 4326,
    created_at          TEXT    DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE CASCADE
);

-- ============================================================
-- APP_SETTINGS — Single-row configuration table
-- ============================================================
CREATE TABLE IF NOT EXISTS app_settings (
    id                        INTEGER PRIMARY KEY CHECK (id = 1),
    plugin_version            TEXT DEFAULT '',
    default_project_dir       TEXT DEFAULT '',
    default_base_layers_group TEXT DEFAULT 'Base Layers',
    output_group_name         TEXT DEFAULT 'Output Layers',
    symbology_defaults        TEXT DEFAULT '',
    misc                      TEXT DEFAULT ''
);
INSERT OR IGNORE INTO app_settings (id) VALUES (1);
```

**Incremental Migrations** (`_migrate_schema()`):

```sql
-- Applied idempotently via ALTER TABLE ... ADD COLUMN (wrapped in try/except)
ALTER TABLE projects     ADD COLUMN is_deleted           INTEGER DEFAULT 0;
ALTER TABLE projects     ADD COLUMN base_layer_names     TEXT DEFAULT '';
ALTER TABLE projects     ADD COLUMN db_type              TEXT DEFAULT 'spatialite';
ALTER TABLE projects     ADD COLUMN qgs_project_file     TEXT DEFAULT '';
ALTER TABLE projects     ADD COLUMN db_connection_string TEXT DEFAULT '';
ALTER TABLE projects     ADD COLUMN workspace_paths      TEXT DEFAULT '';
ALTER TABLE assessments  ADD COLUMN is_deleted           INTEGER DEFAULT 0;
ALTER TABLE task_details ADD COLUMN engine_type          TEXT DEFAULT 'spatialite';
ALTER TABLE task_details ADD COLUMN is_scenario          INTEGER DEFAULT 0;
```

---

### 1.2 `projects/{name}.sqlite` — Per-Project SpatiaLite

Source: `project_manager.py` → `ProjectManager._create_tables()`

```sql
-- SpatiaLite initialization (called once on project creation)
-- SELECT InitSpatialMetaData(1);
-- Creates: geometry_columns, spatial_ref_sys, views_geometry_columns, etc.

-- ============================================================
-- BASE_LAYERS_REGISTRY — Registry of migrated QGIS layers
-- ============================================================
CREATE TABLE IF NOT EXISTS base_layers_registry (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    layer_name      TEXT    UNIQUE NOT NULL,
    geometry_type   TEXT    DEFAULT '',                  -- 'POINT', 'LINESTRING', 'POLYGON', etc.
    srid            INTEGER DEFAULT 4326,
    source          TEXT    DEFAULT '',
    feature_count   INTEGER DEFAULT 0,
    created_at      TEXT    DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- ASSESSMENT_RESULTS_METADATA — Output layer tracking
-- ============================================================
CREATE TABLE IF NOT EXISTS assessment_results_metadata (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_uuid     TEXT    NOT NULL,                -- Links to admin.sqlite → assessments.uuid
    output_layer        TEXT    NOT NULL,
    operation           TEXT    NOT NULL,
    source_target       TEXT    DEFAULT '',
    source_assessment   TEXT    DEFAULT '',
    feature_count       INTEGER DEFAULT 0,
    created_at          TEXT    DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- SPATIAL_VERSIONS — Immutable version tracking (Git-like)
-- ============================================================
CREATE TABLE IF NOT EXISTS spatial_versions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_name       TEXT    NOT NULL,                -- Base name (no __v{n} suffix)
    table_name          TEXT    NOT NULL,                -- Actual SpatiaLite table
    description         TEXT    DEFAULT '',
    parent_version_id   INTEGER DEFAULT NULL,            -- Linked list → previous version
    is_current          INTEGER DEFAULT 1,               -- HEAD pointer: 1=active, 0=archived
    created_at          TEXT    DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (parent_version_id) REFERENCES spatial_versions(id)
);
```

---

### 1.3 Dynamic Spatial Tables

Created at runtime during overlay analysis. One table per version:

```sql
-- Template (actual names use sanitized convention):
-- {project_id}__{assessment_name}__v{n}
--
-- Example: forestproject__deforestation_2024__v3

CREATE TABLE {versioned_name} (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    -- columns inherited from source layers:
    input_id        INTEGER,            -- FK to target layer feature
    identity_id     INTEGER,            -- FK to assessment layer feature
    split_type      TEXT,               -- 'intersection' or 'union'
    shape_area      REAL,
    shape_length    REAL
    -- additional columns from source layer attributes
);

-- Geometry registration (SpatiaLite API):
SELECT AddGeometryColumn('{versioned_name}', 'geom', {srid}, '{geom_type}', 'XY');
SELECT RecoverGeometryColumn('{versioned_name}', 'geom', {srid}, '{geom_type}', 'XY');
SELECT CreateSpatialIndex('{versioned_name}', 'geom');
```

**Table naming convention:**

```
{project_id}__{assessment_name}__v{n}
│              │                  │
│              │                  └─ version number (auto-incremented)
│              └─ assessment name (sanitized)
└─ project name/id (sanitized)

Separator: double underscore (__) — preserved by sanitize_table_name()
Regex guard: re.sub(r'_{3,}', '__', ...) collapses 3+ underscores to 2
```

---

## 2. Table Relationships

### 2.1 Entity-Relationship Diagram — `admin.sqlite`

```
┌──────────────────┐
│   app_settings   │    Single-row config (id=1)
│ (singleton)      │    No relationships
└──────────────────┘


┌──────────────────┐       1:N        ┌──────────────────────┐
│    projects      │─────────────────▶│    assessments        │
│                  │                  │                       │
│  id (PK)        │                  │  id (PK)              │
│  uuid (UNIQUE)   │                  │  uuid (UNIQUE)        │
│  name (UNIQUE)   │                  │  project_id (FK) ─────┘
│  db_path         │                  │  name                 │
│  db_type         │                  │  target_layer         │
│  is_deleted      │                  │  is_deleted           │
└──────────────────┘                  │  UNIQUE(project_id,   │
                                      │         name)         │
                                      └───────────┬───────────┘
                                                  │
                            ┌─────────────────────┼──────────────────────┐
                            │ 1:N                 │ 1:N                  │ 1:N
                            ▼                     ▼                      ▼
                ┌──────────────────┐  ┌────────────────────┐  ┌───────────────────┐
                │assessment_layers │  │layer_visibility_   │  │  workflow_steps    │
                │                  │  │     state           │  │                   │
                │ id (PK)          │  │ assessment_id (PK) │  │ id (PK)           │
                │ assessment_id(FK)│  │ layer_name (PK)    │  │ assessment_id(FK) │
                │ layer_name       │  │ visible            │  │ step_order        │
                │ layer_type       │  └────────────────────┘  │ operation         │
                │ geometry_type    │                           └───────────────────┘
                └──────────────────┘
                            │
                            │ 1:N (assessment_id)
                            ▼
                ┌──────────────────────┐       1:N        ┌──────────────────────┐
                │    provenance        │─────────────────▶│    task_details       │
                │                      │                  │                       │
                │  id (PK)             │                  │  id (PK)              │
                │  uuid (UNIQUE)       │                  │  uuid (UNIQUE)        │
                │  assessment_id (FK)  │                  │  provenance_id (FK)───┘
                │  name                │                  │  parent_task_id (FK)──┐
                └──────────────────────┘                  │  step_order           │
                                                          │  operation            │
                            │ 1:N (assessment_id)         │  engine_type          │
                            ▼                             │  is_scenario          │
                ┌──────────────────────┐                  │  input_tables (JSON)  │
                │ spatial_references   │                  │  output_tables (JSON) │
                │                      │                  └───────────┬───────────┘
                │ id (PK)              │                              │
                │ uuid (UNIQUE)        │                    Self-referencing FK
                │ assessment_id (FK)   │                    (parent_task_id → id)
                │ name                 │                    Enables hierarchical
                │ overlay_layer_name   │                    task trees (DAG)
                │ srid                 │
                └──────────────────────┘
```

---

### 2.2 Entity-Relationship Diagram — `project.sqlite`

```
┌────────────────────────┐
│  base_layers_registry  │       Standalone — no FK relationships
│                        │       Tracks which QGIS layers have been
│  id (PK)               │       migrated into this SpatiaLite DB
│  layer_name (UNIQUE)   │
│  geometry_type          │
│  srid                  │
│  feature_count          │
└────────────────────────┘


┌───────────────────────────────┐
│  assessment_results_metadata  │      Standalone — links to admin.sqlite
│                               │      via assessment_uuid (logical FK)
│  id (PK)                      │
│  assessment_uuid ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ▶ admin.sqlite → assessments.uuid
│  output_layer                 │
│  operation                    │
│  source_target                │
│  feature_count                │
└───────────────────────────────┘


┌──────────────────────┐
│   spatial_versions   │◀──┐    Self-referencing linked list
│                      │   │    Each version points to its parent
│  id (PK)             │   │
│  scenario_name       │   │    Versions for same scenario share
│  table_name          │   │    the same scenario_name value
│  parent_version_id ──┘   │
│  is_current              │    HEAD pointer: exactly one row
│  created_at              │    per scenario has is_current=1
└──────────────────────────┘
         │
         │  table_name references
         ▼
┌──────────────────────────┐
│  {project}__              │   Dynamic spatial tables
│  {assessment}__v{n}       │   Created at runtime by
│                           │   SpatialEngine.overlay()
│  id, geom, input_id,     │
│  identity_id, split_type, │
│  shape_area, shape_length │
└───────────────────────────┘
```

---

### 2.3 Cross-Database Relationships

```
┌─────────────────────────────────────────────────────────────────┐
│                         admin.sqlite                            │
│                                                                 │
│  projects.db_path ──────────────────────────────┐               │
│    "projects/forest.sqlite"                     │               │
│                                                 │ absolute path │
│  assessments.uuid ── ── ── ── ── ── ── ── ──┐  │ resolved via  │
│    "a1b2c3d4-..."                            │  │ AdminManager. │
│                                              │  │ get_project_  │
└──────────────────────────────────────────────│──│─db_path()─────┘
                                               │  │
                        ┌──────────────────────┘  │
                        │ logical FK (uuid match) │
                        ▼                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                   projects/forest.sqlite                        │
│                                                                 │
│  assessment_results_metadata.assessment_uuid                    │
│    "a1b2c3d4-..."   (matches admin assessments.uuid)            │
│                                                                 │
│  spatial_versions.table_name ─────▶ dynamic table name          │
│    "forest__deforestation__v2"      in same database            │
│                                                                 │
│  base_layers_registry.layer_name ─▶ migrated data table         │
│    "parcels"                        in same database            │
└─────────────────────────────────────────────────────────────────┘
```

Key cross-DB links:
- `projects.db_path` → points to the physical `.sqlite` file for each project
- `assessment_results_metadata.assessment_uuid` → logical FK to `admin.sqlite → assessments.uuid`
- No enforced FK across databases — integrity maintained by application code

---

### 2.4 Cardinality Reference

| Parent | Child | Cardinality | FK Column | ON DELETE |
|--------|-------|-------------|-----------|-----------|
| `projects` | `assessments` | 1 : N | `project_id` | CASCADE |
| `assessments` | `assessment_layers` | 1 : N | `assessment_id` | CASCADE |
| `assessments` | `layer_visibility_state` | 1 : N | `assessment_id` | CASCADE |
| `assessments` | `workflow_steps` | 1 : N | `assessment_id` | CASCADE |
| `assessments` | `provenance` | 1 : N | `assessment_id` | CASCADE |
| `assessments` | `spatial_references` | 1 : N | `assessment_id` | CASCADE |
| `provenance` | `task_details` | 1 : N | `provenance_id` | CASCADE |
| `task_details` | `task_details` | 1 : N (self) | `parent_task_id` | SET NULL |
| `spatial_versions` | `spatial_versions` | 1 : N (self) | `parent_version_id` | *(none)* |

**Composite keys:**
- `layer_visibility_state(assessment_id, layer_name)` — composite PK
- `assessments(project_id, name)` — UNIQUE constraint

**Check constraints:**
- `assessment_layers.layer_type IN ('input', 'output', 'reference')`
- `app_settings.id = 1` (enforced singleton row)

---

## 3. Process Flow Diagrams

### 3.1 Flow 1: Spatial Assessment (`ApplyOverlay`)

The primary flow — creates versioned spatial overlay tables.

```
┌──────────┐    click "Finish"    ┌───────────────────────┐
│  Wizard  │─────────────────────▶│  AssessmentMainForm   │
│  Dialog  │  returns:            │  _on_wizard_finished() │
└──────────┘  assessment_name,    └───────────┬───────────┘
              target_layer,                   │
              assessment_layers               │
                                              ▼
                                ┌───────────────────────────┐
                                │  AssessmentExecutor        │
                                │  execute_spatial_          │
                                │  assessment()              │
                                │                            │
                                │  1. Build ApplyOverlay     │
                                │     Command                │
                                │  2. Call use case           │
                                │  3. Catch exceptions       │
                                │  4. Show QMessageBox       │
                                └─────────────┬─────────────┘
                                              │ ApplyOverlayCommand
                                              ▼
                                ┌───────────────────────────┐
                                │  ApplyOverlay.execute()    │
                                │                            │
                                │  Validate:                 │
                                │  ├ name unique?            │
                                │  └ assessment_layers ≥ 1?  │
                                └─────────────┬─────────────┘
                                              │
                               ┌──────────────┤
                               │ ValueError   │ OK
                               │ (bubbles up) │
                               ▼              ▼
                          ┌─────────┐  ┌────────────────────────────┐
                          │ ABORT   │  │  get_project_db_path()     │
                          └─────────┘  │  from AdminManager          │
                                       └─────────────┬──────────────┘
                                                     │ db_path
                                                     ▼
                                       ┌────────────────────────────┐
                                       │  SpatialEngine.__enter__() │
                                       │  Opens SpatiaLite          │
                                       │  connection                │
                                       └─────────────┬──────────────┘
                                                     │
                              ┌───────────────────────┤
                              │ FOR EACH LAYER        │
                              ▼                       │
                 ┌──────────────────────────┐         │
                 │ engine.prepare_layer()    │         │
                 │                           │         │
                 │ ProjectManager checks:    │         │
                 │ ├ table_exists()?         │         │
                 │ │  YES → return name      │         │
                 │ │  NO  ↓                  │         │
                 │ ├ CREATE TABLE            │         │
                 │ ├ AddGeometryColumn       │         │
                 │ ├ INSERT features         │         │
                 │ ├ RecoverGeometryColumn   │         │
                 │ └ CreateSpatialIndex      │         │
                 │                           │         │
                 │ Returns: table_name       │         │
                 └──────────────┬────────────┘         │
                                │                      │
                                └──────────────────────┘
                                                     │
                              ┌───────────────────────┤
                              │ FOR EACH ASSESSMENT   │
                              │ LAYER                 │
                              ▼                       │
                 ┌──────────────────────────────────┐  │
                 │ engine.overlay(target, assess,    │  │
                 │                base_name)          │  │
                 │                                    │  │
                 │ 1. Count existing versions         │  │
                 │    n = len(get_versions()) + 1     │  │
                 │                                    │  │
                 │ 2. versioned = base__v{n}          │  │
                 │                                    │  │
                 │ 3. Intersection → tmp_intersect    │  │
                 │    SQL: CREATE TABLE AS SELECT     │  │
                 │         ST_Intersection(...)        │  │
                 │                                    │  │
                 │ 4. Union → tmp_union               │  │
                 │    SQL: CREATE TABLE AS SELECT     │  │
                 │         ST_Union(...)               │  │
                 │                                    │  │
                 │ 5. RENAME tmp_union → final        │  │
                 │ 6. DROP tmp_intersect              │  │
                 │                                    │  │
                 │ 7. INSERT INTO spatial_versions    │  │
                 │    (scenario, table, is_current=1) │  │
                 │                                    │  │
                 │ 8. Load as QgsVectorLayer          │  │
                 │    Add to "Output Layers" group    │  │
                 │                                    │  │
                 │ Returns: {table, version_id, layer}│  │
                 └─────────────────┬────────────────┘  │
                                   │                   │
                                   └───────────────────┘
                                                     │
                                                     ▼
                                       ┌────────────────────────────┐
                                       │  SpatialEngine.__exit__()  │
                                       │  Closes connection         │
                                       └─────────────┬──────────────┘
                                                     │
                                                     ▼
                                       ┌────────────────────────────┐
                                       │  Returns wizard_results:   │
                                       │  {                         │
                                       │    assessment_name,        │
                                       │    target_layer,           │
                                       │    assessment_layers,      │
                                       │    output_tables,          │
                                       │    description,            │
                                       │    version_ids             │
                                       │  }                         │
                                       └─────────────┬──────────────┘
                                                     │
                                                     ▼
                                       ┌────────────────────────────┐
                                       │  AssessmentExecutor        │
                                       │  .record_assessment()      │
                                       │  → See Flow 6              │
                                       └─────────────┬──────────────┘
                                                     │
                                                     ▼
                                       ┌────────────────────────────┐
                                       │  QMessageBox.information   │
                                       │  "Assessment Complete"     │
                                       └────────────────────────────┘
```

**SQL executed during overlay (inside `SpatialAnalyzerLite`):**

```sql
-- Step 3: Intersection
CREATE TABLE {tmp_intersect} AS
SELECT
    a.ROWID AS input_id,
    b.ROWID AS identity_id,
    ST_Intersection(a.geom, b.geom) AS geom,
    'intersection' AS split_type,
    ST_Area(ST_Intersection(a.geom, b.geom)) AS shape_area,
    ST_Length(ST_Intersection(a.geom, b.geom)) AS shape_length
FROM {target_table} a, {assessment_table} b
WHERE ST_Intersects(a.geom, b.geom)
  AND a.ROWID IN (
      SELECT ROWID FROM SpatialIndex
      WHERE f_table_name = '{target_table}' AND search_frame = b.geom
  );

-- Step 4: Union
CREATE TABLE {tmp_union} AS
SELECT * FROM {tmp_intersect}
UNION ALL
SELECT
    a.ROWID AS input_id,
    NULL AS identity_id,
    ST_Difference(a.geom, (
        SELECT ST_Union(b.geom) FROM {assessment_table} b
        WHERE ST_Intersects(a.geom, b.geom)
    )) AS geom,
    'union' AS split_type,
    ... -- area, length
FROM {target_table} a;

-- Step 5: Geometry registration
SELECT RecoverGeometryColumn('{final_table}', 'geom', {srid}, '{geom_type}', 'XY');
SELECT CreateSpatialIndex('{final_table}', 'geom');
```

---

### 3.2 Flow 2: Simple Assessment (`CreateScenario`)

Creates a memory layer from selected features — no spatial analysis engine involved.

```
┌──────────┐    click "Finish"    ┌───────────────────────┐
│  Wizard  │─────────────────────▶│  AssessmentExecutor   │
│  (Page 3)│  target_layer with   │  execute_simple_      │
└──────────┘  selected features   │  assessment()         │
                                  └───────────┬───────────┘
                                              │ CreateScenarioCommand
                                              ▼
                                ┌───────────────────────────┐
                                │  CreateScenario.execute()  │
                                │                            │
                                │  Validate:                 │
                                │  ├ name unique?            │
                                │  └ selectedFeatures ≥ 1?   │
                                └─────────────┬─────────────┘
                                              │
                     ┌────────────────────────┤
                     │ ValueError             │ OK
                     ▼                        ▼
                ┌─────────┐    ┌────────────────────────────┐
                │ ABORT   │    │  Build QGIS memory layer:   │
                │ QMsg    │    │                              │
                └─────────┘    │  1. Get geometry type + CRS  │
                               │     from target_layer        │
                               │                              │
                               │  2. QgsVectorLayer(          │
                               │       "{geom}?crs={crs}",    │
                               │       layer_name, "memory")  │
                               │                              │
                               │  3. Copy fields from target  │
                               │  4. Copy selected features   │
                               │  5. updateExtents()          │
                               └──────────────┬───────────────┘
                                              │
                                              ▼
                               ┌────────────────────────────┐
                               │  Add to QGIS project:      │
                               │                             │
                               │  group = "Output Layers"    │
                               │  QgsProject.addMapLayer()   │
                               │  group.addLayer()           │
                               └──────────────┬──────────────┘
                                              │
                                              ▼
                               ┌────────────────────────────┐
                               │  Returns wizard_results:   │
                               │  {                         │
                               │    assessment_name,        │
                               │    target_layer,           │
                               │    assessment_layers: [],  │
                               │    output_tables: [name],  │
                               │    description,            │
                               │    version_ids: []  ← no   │
                               │                  versioning│
                               │  }                         │
                               └────────────────────────────┘
```

---

### 3.3 Flow 3: Rollback Version

O(1) operation — moves HEAD pointer, no spatial recalculation.

```
┌─────────────────────┐  click "Rollback   ┌─────────────────────┐
│ VersionHistoryPanel │  to selected"       │  AssessmentMainForm │
│                     │────────────────────▶│  _on_rollback_      │
│  selected: v2       │  signal:            │  version()          │
│  (not HEAD)         │  rollback_requested │                     │
└─────────────────────┘  (scenario, vid)    └──────────┬──────────┘
                                                       │
                                                       ▼
                                         ┌───────────────────────────┐
                                         │  AssessmentExecutor       │
                                         │  .rollback_to_version()   │
                                         │                           │
                                         │  Build RollbackVersion    │
                                         │  Command                  │
                                         └─────────────┬─────────────┘
                                                       │ RollbackVersionCommand
                                                       ▼
                                         ┌───────────────────────────┐
                                         │  RollbackVersion.execute()│
                                         │                           │
                                         │  1. get_project_db_path() │
                                         └─────────────┬─────────────┘
                                                       │
                                                       ▼
                                         ┌───────────────────────────────┐
                                         │  SpatialEngine                │
                                         │  .rollback_to_version()       │
                                         │                               │
                                         │  1. get_version_by_id(vid)    │
                                         │     → {table_name, ...}       │
                                         │                               │
                                         │  2. set_current_version()     │
                                         │     SQL:                      │
                                         │     UPDATE spatial_versions   │
                                         │       SET is_current = 0      │
                                         │       WHERE scenario_name = ? │
                                         │                               │
                                         │     UPDATE spatial_versions   │
                                         │       SET is_current = 1      │
                                         │       WHERE id = ?            │
                                         │                               │
                                         │  3. Load table as QGIS layer  │
                                         │     Add to "Output Layers"    │
                                         │                               │
                                         │  Returns:                     │
                                         │  {table, version_id, layer}   │
                                         └───────────────┬───────────────┘
                                                         │
                                                         ▼
                                         ┌───────────────────────────┐
                                         │  QMessageBox.information  │
                                         │  "Restored to version {n}"│
                                         └───────────────────────────┘
```

**SQL executed (2 statements, O(1)):**

```sql
-- Clear all HEAD pointers for this scenario
UPDATE spatial_versions
   SET is_current = 0
 WHERE scenario_name = '{scenario_name}';

-- Set new HEAD
UPDATE spatial_versions
   SET is_current = 1
 WHERE id = {version_id};
```

---

### 3.4 Flow 4: Compare Versions

Read-only — loads two snapshots as separate QGIS layers. Does NOT move HEAD.

```
┌─────────────────────┐  click "Compare    ┌─────────────────────┐
│ VersionHistoryPanel │  with HEAD"         │  AssessmentMainForm │
│                     │────────────────────▶│  _on_compare_       │
│  selected: v1       │  signal:            │  versions()         │
│  HEAD: v3           │  compare_requested  │                     │
└─────────────────────┘  (scenario,v1,v3)   └──────────┬──────────┘
                                                       │
                                                       ▼
                                         ┌───────────────────────────┐
                                         │  AssessmentExecutor       │
                                         │  .compare_versions()      │
                                         │                           │
                                         │  Build CompareVersions    │
                                         │  Command                  │
                                         └─────────────┬─────────────┘
                                                       │ CompareVersionsCommand
                                                       ▼
                                         ┌───────────────────────────┐
                                         │  CompareVersions.execute()│
                                         │                           │
                                         │  1. get_project_db_path() │
                                         └─────────────┬─────────────┘
                                                       │
                                                       ▼
                                         ┌───────────────────────────────┐
                                         │  SpatialEngine                │
                                         │                               │
                                         │  1. engine.load_version(v1)   │
                                         │     ├ get_version_by_id(v1)   │
                                         │     │ → {table_name: ...}     │
                                         │     └ create_qgis_layer()     │
                                         │       name: "scenario [v1]"   │
                                         │       group: "Comparison"     │
                                         │                               │
                                         │  2. engine.load_version(v3)   │
                                         │     ├ get_version_by_id(v3)   │
                                         │     │ → {table_name: ...}     │
                                         │     └ create_qgis_layer()     │
                                         │       name: "scenario [v3]"   │
                                         │       group: "Comparison"     │
                                         │                               │
                                         │  ⚠ No is_current change       │
                                         │  ⚠ Both layers are read-only  │
                                         │                               │
                                         │  Returns:                     │
                                         │  {layer_a, layer_b,           │
                                         │   version_id_a, version_id_b} │
                                         └───────────────────────────────┘
```

**SQL executed (read-only):**

```sql
-- Load version metadata (×2):
SELECT * FROM spatial_versions WHERE id = {version_id};

-- Each version's table is loaded via SpatiaLite URI:
-- dbname='{db_path}' table='{table_name}' (geom)
```

---

### 3.5 Flow 5: Project Creation

```
┌──────────────────────┐   create_project(name)   ┌───────────────────┐
│  AssessmentMainForm  │──────────────────────────▶│  AdminManager     │
│  or Dialog           │                           │                   │
└──────────────────────┘                           └─────────┬─────────┘
                                                             │
                              ┌───────────────────────────────┤
                              │                               │
                              ▼                               ▼
               ┌────────────────────────┐    ┌──────────────────────────────┐
               │  admin.sqlite          │    │  ProjectManager              │
               │                        │    │  (creates new SpatiaLite DB) │
               │  INSERT INTO projects  │    │                              │
               │  (uuid, name,          │    │  1. Create file:             │
               │   description, db_path)│    │     projects/{name}.sqlite   │
               │                        │    │                              │
               │  db_path =             │    │  2. InitSpatialMetaData(1)   │
               │  "projects/{name}      │    │                              │
               │         .sqlite"       │    │  3. CREATE TABLE             │
               └────────────────────────┘    │     base_layers_registry     │
                                             │                              │
                                             │  4. CREATE TABLE             │
                                             │     assessment_results_      │
                                             │     metadata                 │
                                             │                              │
                                             │  5. CREATE TABLE             │
                                             │     spatial_versions         │
                                             └──────────────────────────────┘
```

---

### 3.6 Flow 6: Metadata Recording (post-assessment)

Called by `AssessmentExecutor` after a successful spatial assessment.

```
┌───────────────────────────────────────────┐
│  AssessmentExecutor.record_assessment()   │
│  Input: wizard_results dict               │
└─────────────────────┬─────────────────────┘
                      │
                      ▼
        ┌───────────────────────────────────┐
        │  AdminManager.create_assessment() │
        │                                   │
        │  INSERT INTO assessments          │
        │  (uuid, project_id, name,         │
        │   description, target_layer)      │
        │                                   │
        │  For each layer in results:       │
        │    INSERT INTO assessment_layers  │
        │    (assessment_id, layer_name,    │
        │     layer_type)                   │
        │                                   │
        │  Returns: assessment_id           │
        └──────────────┬────────────────────┘
                       │
                       ▼
        ┌───────────────────────────────────┐
        │  Set layer visibility             │
        │                                   │
        │  For each output_table:           │
        │    INSERT INTO                    │
        │    layer_visibility_state         │
        │    (assessment_id, layer_name,    │
        │     visible=1)                    │
        └──────────────┬────────────────────┘
                       │
                       │  if assessment_layers exist:
                       ▼
        ┌───────────────────────────────────┐
        │  _record_provenance()             │
        │                                   │
        │  1. INSERT INTO provenance        │
        │     (uuid, assessment_id,         │
        │      name="Initial Assessment",   │
        │      description="Base spatial    │
        │       analysis: union+intersect") │
        │                                   │
        │     Returns: provenance_id        │
        │                                   │
        │  2. INSERT INTO task_details      │
        │     (uuid, provenance_id,         │
        │      step_order=1,                │
        │      operation="union+intersect", │
        │      category="spatial_analysis", │
        │      engine_type="spatialite",    │
        │      input_tables=[target] +      │
        │        assessment_layers,         │
        │      output_tables=output_tables, │
        │      added_to_map=1)              │
        └───────────────────────────────────┘
```

**Complete SQL sequence for metadata recording:**

```sql
-- 1. Create assessment
INSERT INTO assessments (uuid, project_id, name, description, target_layer)
VALUES ('{uuid}', {project_id}, '{name}', '{desc}', '{target_layer}');

-- 2. Register layers
INSERT INTO assessment_layers (assessment_id, layer_name, layer_type, geometry_type)
VALUES ({assessment_id}, '{input_name}', 'input', '{geom_type}');

INSERT INTO assessment_layers (assessment_id, layer_name, layer_type, geometry_type)
VALUES ({assessment_id}, '{output_name}', 'output', '{geom_type}');

-- 3. Set visibility
INSERT OR REPLACE INTO layer_visibility_state (assessment_id, layer_name, visible)
VALUES ({assessment_id}, '{output_table}', 1);

-- 4. Create provenance
INSERT INTO provenance (uuid, assessment_id, name, description)
VALUES ('{uuid}', {assessment_id}, 'Initial Assessment',
        'Base spatial analysis: union + intersection');

-- 5. Create task record
INSERT INTO task_details (uuid, provenance_id, step_order, operation,
                          category, engine_type, input_tables, output_tables, added_to_map)
VALUES ('{uuid}', {provenance_id}, 1, 'union+intersect',
        'spatial_analysis', 'spatialite',
        '["target_layer", "assess_layer"]',  -- JSON
        '["project__assessment__v1"]',        -- JSON
        1);
```
