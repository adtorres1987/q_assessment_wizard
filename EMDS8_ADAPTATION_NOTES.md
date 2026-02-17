# Notas de adaptación: emdsInfo.Sqlite → Assessment Wizard Plugin

Análisis comparativo entre el schema de **EMDS 8** (`emdsInfo.Sqlite`) y el schema
actual del plugin (`admin.sqlite`). Las mejoras están ordenadas por impacto y facilidad
de implementación.

---

## 1. Resumen del schema EMDS 8

### Jerarquía de tablas

```
Projects  (12 proyectos reales)
  ├── SpatialReferences  (5)  ← overlay layer + fuentes originales por análisis
  ├── LayerSymbologies   (0)  ← simbología serializada por proyecto
  ├── ProjectTableLookups (0) ← mapeo shortname→longname de tablas
  └── Provenances  (9)  ← una por corrida de análisis (directamente bajo Project)
        └── TaskDetails  (9)  ← una por Provenance
              ├── Aliases        (891)  ← campos de entrada del modelo NW
              ├── OutputAliases  (795)  ← campos de salida del modelo NW
              ├── Layers         (0)    ← capas resultado
              ├── MetadataNws    (9)    ← tablas __IT, __IRST de NetWeaver
              ├── MetadataCdps   (0)    ← CDP (Cumulative Decision Priority)
              ├── MetadataGenerics (0)  ← pasos genéricos
              ├── MetadataLpas   (0)    ← LPA (Logic Priority Analysis)
              ├── MetadataBayesFusions (0)
              ├── MetadataScripts (0)
              └── MetdataWorkflows (0)
                    └── MetadataActivities (0)

Reports      (standalone, 0 filas)
AppSettings  (standalone, 1 fila)
```

### Datos observados en los proyectos de Steve

```
Proyectos:     test1, mytest2, test3, test4, test6, tstlong1, test123, ...
Base layers:   USFSregions, Forests, T2_2022_LTA_10172022, T2_Peram
DB type:       geodatabase (ArcGIS), path absoluto en Windows
Engine:        Netweaver (todos los TaskDetails)
Overlay layer: {assessment}__{provenance}___Overlay  (p.ej. test2__Overlay)
Output table:  {assessment}__{provenance}___results
Influence:     {assessment}__{provenance}___results__IT
Influence rank:{assessment}__{provenance}___results__IRST
```

### Diferencias de convención de nombres

| Plugin (actual) | EMDS 8 |
|----------------|--------|
| `project__assessment` (2 guiones) | `project__provenance___results` (3 guiones antes de sufijo) |
| Sin overlay | `project__Overlay` como SpatialReference |
| Sin tablas IT/IRST | `___results__IT`, `___results__IRST` |

---

## 2. Mejoras adaptables — ordenadas por prioridad

---

### PRIORIDAD ALTA

#### 2.1 Columnas `engine_type` y `db_type` en `task_details`

**Origen en EMDS 8:** `TaskDetails.EngineType` (`Netweaver`), `TaskDetails.DatabaseType` (`Sqlite`)

**Estado actual del plugin:** `task_details` ya tiene `db_type TEXT DEFAULT 'spatialite'`.
Falta `engine_type`.

**Adaptación:**
```sql
-- Agregar a task_details en admin_manager.py
ALTER TABLE task_details ADD COLUMN engine_type TEXT DEFAULT 'spatialite';
-- Valores posibles: 'spatialite', 'netweaver', 'cdp', 'lpa', 'script', 'bayes'
```

**En `admin_manager._create_tables()`** añadir la columna al CREATE TABLE:
```sql
engine_type TEXT DEFAULT 'spatialite',
```

**En `_record_provenance()` del executor:**
```python
self.admin_manager.add_task(
    ...
    operation="union+intersect",
    category="spatial_analysis",
    engine_type="spatialite",   # nuevo
    ...
)
```

---

#### 2.2 `SpatialReference` como entidad de primer nivel

**Origen en EMDS 8:** `SpatialReferences` es una tabla propia con FK en `Provenances`.
Captura el overlay layer (`test2__Overlay`) y las fuentes originales de datos
(`OriginalSourceTablesNames`, `OriginalSourceTablesDBTypes`, `OriginalSourceTablesDBConnectionStrings`).

**Estado actual del plugin:** El CRS está implícito en la capa migrada. No existe
tabla de referencia espacial.

**Adaptación mínima** — agregar a `admin.sqlite`:
```sql
CREATE TABLE IF NOT EXISTS spatial_references (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE NOT NULL,
    assessment_id INTEGER NOT NULL,
    name TEXT NOT NULL,                    -- p.ej. "flood__Overlay"
    overlay_layer_name TEXT DEFAULT '',   -- tabla SpatiaLite del overlay
    source_tables TEXT DEFAULT '',        -- JSON: nombres de tablas fuente
    source_db_type TEXT DEFAULT 'spatialite',
    source_db_path TEXT DEFAULT '',       -- path al .sqlite
    srid INTEGER DEFAULT 4326,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE CASCADE
);
```

**En `assessment_executor._record_provenance()`:**
```python
spatial_ref_id = self.admin_manager.create_spatial_reference(
    assessment_id=assessment_id,
    name=f"{self.project_id}__Overlay",
    overlay_layer_name=f"{self.project_id}__overlay",
    source_tables=[target_layer_name] + assessment_layer_names,
    source_db_type='spatialite',
)
```

> **Nota:** EMDS 8 hace FK `Provenances → SpatialReferences`. En el plugin conviene
> hacer FK `spatial_references → assessments` (más simple, sin romper la jerarquía
> actual `Assessment → Provenance → Task`).

---

#### 2.3 Soft delete + versioning en `projects` y `assessments`

**Origen en EMDS 8:** Todas las tablas principales tienen:
```sql
"VersionID" INTEGER NOT NULL,
"IsCurrent" INTEGER NOT NULL,
"IsDeleted" INTEGER NOT NULL
```

**Beneficio:** Permite historial de versiones y papelera de reciclaje sin pérdida
de datos.

**Adaptación mínima** (solo `is_deleted` para papelera básica):
```sql
-- projects
ALTER TABLE projects ADD COLUMN is_deleted INTEGER DEFAULT 0;
-- assessments
ALTER TABLE assessments ADD COLUMN is_deleted INTEGER DEFAULT 0;
```

**Cambios en `admin_manager.py`:**
```python
# get_all_projects: filtrar eliminados
cursor.execute("SELECT ... FROM projects WHERE is_deleted = 0 ORDER BY name")

# delete_project: soft delete en vez de DELETE
def delete_project(self, project_id):
    cursor.execute("UPDATE projects SET is_deleted = 1 WHERE id = ?", (project_id,))
    self.connection.commit()
    cursor.close()
```

> **Versioning completo** (`VersionID`, `IsCurrent`) es complejo — dejarlo para
> cuando se necesite trazabilidad de ediciones.

---

#### 2.4 `BaseLayerNames` en `projects`

**Origen en EMDS 8:** `Projects.BaseLayerNames` = `"USFSregions,Forests,T2_2022_LTA_10172022,T2_Peram"` (CSV).

**Estado actual del plugin:** Las base layers se registran en `base_layers_registry`
dentro de cada `project_XXX.sqlite` (SpatiaLite). La tabla `admin.sqlite/projects`
no tiene esta información.

**Adaptación:**
```sql
ALTER TABLE projects ADD COLUMN base_layer_names TEXT DEFAULT '';
-- Almacenar como JSON: '["USFSregions", "Forests", "T2_2022_LTA_10172022"]'
```

**Ventaja:** Permite mostrar las base layers en el TreeView sin abrir el SpatiaLite
del proyecto (acceso más rápido desde `admin.sqlite`).

**En `LayerMigrationService.migrate_selected_layers()`**, al final de la migración
exitosa, actualizar el campo:
```python
layer_names = list(layers_dict.keys())
admin_manager.update_project_base_layers(project_db_id, layer_names)
```

---

### PRIORIDAD MEDIA

#### 2.5 `GeoDatabaseType` y `GeoDatabaseConnectionString` en `projects`

**Origen en EMDS 8:** `Projects.GeoDatabaseType` (`geodatabase`),
`Projects.GeoDatabaseConnectionString` (path completo al `.geodatabase`).

**Estado actual del plugin:** `projects.db_path` guarda solo el path relativo al
`.sqlite`. No hay campo para tipo de DB.

**Adaptación:**
```sql
ALTER TABLE projects ADD COLUMN db_type TEXT DEFAULT 'spatialite';
-- Valores: 'spatialite', 'postgresql', 'geodatabase'
ALTER TABLE projects ADD COLUMN db_connection_string TEXT DEFAULT '';
-- Para PostgreSQL: 'host=localhost dbname=wizard_db user=postgres'
```

**Beneficio:** Prepara el plugin para el deploy en web con PostgreSQL sin cambiar
la interfaz del `AdminManager`.

---

#### 2.6 `MapDocumentName` y `WorkspacePaths` en `projects`

**Origen en EMDS 8:** `Projects.MapDocumentName` (nombre del `.mxd`/`.qgs`),
`Projects.WorkspacePaths` (paths a workspaces adicionales).

**Adaptación para QGIS:**
```sql
ALTER TABLE projects ADD COLUMN qgs_project_file TEXT DEFAULT '';
-- Path al .qgs/.qgz asociado al proyecto
ALTER TABLE projects ADD COLUMN workspace_paths TEXT DEFAULT '';
-- JSON: ["/path/to/rasters", "/path/to/vectors"]
```

---

#### 2.7 `IsDisplayedOnMap` e `IsScenario` en `task_details`

**Origen en EMDS 8:** `TaskDetails.IsDisplayedOnMap` (INTEGER 0/1),
`TaskDetails.IsScenario` (INTEGER 0/1).

**Estado actual del plugin:** `task_details` ya tiene `added_to_map INTEGER DEFAULT 1`.
Falta `is_scenario`.

**Adaptación:**
```sql
ALTER TABLE task_details ADD COLUMN is_scenario INTEGER DEFAULT 0;
```

**Uso:** Marcar análisis alternativos ("what-if") para distinguirlos de la corrida
principal en el TreeView.

---

#### 2.8 `ParentTaskID` ya implementado — verificar compatibilidad

**Origen en EMDS 8:** `TaskDetails.ParentTaskID` = UUID cero (`00000000-0000-0000-0000-000000000000`)
cuando no tiene padre (no usa NULL).

**Estado actual del plugin:** `task_details.parent_task_id = NULL` para tareas
top-level. Ya compatible — no requiere cambios.

---

#### 2.9 Tabla `AppSettings`

**Origen en EMDS 8:** Una sola fila con configuración global:
`GeneralSymbology`, `DefaultDataProjectDirectory`, `CurrentVersionNumber`,
`CurrentArcToolboxLocation`, `DownloadMajorEditionsOnly`.

**Adaptación para el plugin:**
```sql
CREATE TABLE IF NOT EXISTS app_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),  -- solo 1 fila
    plugin_version TEXT DEFAULT '',
    default_project_dir TEXT DEFAULT '',
    default_base_layers_group TEXT DEFAULT 'Base Layers',
    output_group_name TEXT DEFAULT 'Output Layers',
    symbology_defaults TEXT DEFAULT '',     -- JSON
    misc TEXT DEFAULT ''                    -- JSON para extensiones futuras
);
INSERT OR IGNORE INTO app_settings (id) VALUES (1);
```

**Beneficio:** Persistir las preferencias del usuario entre sesiones QGIS sin
editar archivos de configuración.

---

### PRIORIDAD BAJA (post-MVP)

#### 2.10 Tablas de metadatos por tipo de análisis

**Origen en EMDS 8:** Una tabla por tipo de motor de análisis:
`MetadataNws`, `MetadataCdps`, `MetadataLpas`, `MetadataBayesFusions`,
`MetadataScripts`, `MetdataWorkflows`.

**Adaptación:** En lugar de crear todas las tablas ahora, usar el campo
`task_details.parameters` (TEXT/JSON) para metadatos específicos del motor.
Cuando se integre NetWeaver o CDP, crear la tabla dedicada.

Ejemplo para cuando se integre NetWeaver:
```sql
CREATE TABLE IF NOT EXISTS metadata_nw (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    influence_table TEXT DEFAULT '',       -- {proj}__{prov}___results__IT
    influence_rank_table TEXT DEFAULT '',  -- {proj}__{prov}___results__IRST
    influence_rank_summary TEXT DEFAULT '',
    symbology TEXT DEFAULT '',
    FOREIGN KEY (task_id) REFERENCES task_details(id) ON DELETE CASCADE
);
```

---

#### 2.11 `Aliases` y `OutputAliases`

**Origen en EMDS 8:** 891 + 795 registros mapeando campos del datasource a campos
del modelo NW. Muy específico de NetWeaver.

**Adaptación:** Diferir hasta integrar NetWeaver. Por ahora, el campo
`task_details.parameters` puede almacenar el mapeo como JSON.

---

#### 2.12 Tabla `Reports`

**Origen en EMDS 8:** Standalone, sin FK. Campos: `ReportName`, `ReportType`,
`ReportDefinition`, `ReportAuthor`.

**Adaptación futura:**
```sql
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE NOT NULL,
    project_id INTEGER,
    assessment_id INTEGER,
    report_name TEXT NOT NULL,
    report_type TEXT DEFAULT '',    -- 'html', 'pdf', 'csv'
    report_definition TEXT DEFAULT '', -- JSON o path a template
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

---

## 3. Tabla de comparación: admin.sqlite vs emdsInfo.Sqlite

| Aspecto | Plugin actual | EMDS 8 | Acción |
|---------|--------------|--------|--------|
| IDs | INTEGER autoincrement | UUID (GUID texto) | Mantener INTEGER (más simple) |
| Soft delete | ❌ Hard delete | ✅ `IsDeleted/IsCurrent` | Añadir `is_deleted` (**P. Alta**) |
| Versioning | ❌ | ✅ `VersionID` | Diferir |
| SpatialReference | ❌ | ✅ Tabla propia | Añadir (**P. Alta**) |
| Base layers en project | Solo en SpatiaLite | ✅ `BaseLayerNames` CSV | Añadir `base_layer_names` (**P. Alta**) |
| Engine type | Parcial (`db_type`) | ✅ `EngineType` + `DatabaseType` | Añadir `engine_type` (**P. Alta**) |
| Map document | ❌ | ✅ `MapDocumentName` | Añadir `qgs_project_file` (**P. Media**) |
| DB type/connection | Solo path `.sqlite` | ✅ `GeoDatabaseType` + `ConnectionString` | Añadir (**P. Media**) |
| Is scenario | ❌ | ✅ `IsScenario` | Añadir `is_scenario` (**P. Media**) |
| App settings | ❌ | ✅ `AppSettings` | Añadir tabla (**P. Media**) |
| Metadata por engine | ❌ | ✅ MetadataNws, Cdps, etc. | Diferir (usar `parameters` JSON) |
| Aliases/OutputAliases | ❌ | ✅ 891+795 filas | Diferir (NetWeaver específico) |
| Reports | ❌ | ✅ Tabla propia | Diferir |
| WorkflowTaskList | ❌ | ✅ En Provenances | Diferir |

---

## 4. Plan de implementación sugerido

### Bloque A — Sin breaking changes (solo `ALTER TABLE`)
Implementar primero porque no rompen el schema existente:

1. `task_details` + `engine_type` column
2. `projects` + `is_deleted`, `base_layer_names`, `db_type`, `qgs_project_file`
3. `assessments` + `is_deleted`
4. `task_details` + `is_scenario`

```python
# En AdminManager.__init__ o en un método migrate_schema():
def _migrate_schema(self):
    """Apply incremental schema migrations safely."""
    migrations = [
        ("task_details",  "engine_type",     "TEXT DEFAULT 'spatialite'"),
        ("task_details",  "is_scenario",     "INTEGER DEFAULT 0"),
        ("projects",      "is_deleted",      "INTEGER DEFAULT 0"),
        ("projects",      "base_layer_names","TEXT DEFAULT ''"),
        ("projects",      "db_type",         "TEXT DEFAULT 'spatialite'"),
        ("projects",      "qgs_project_file","TEXT DEFAULT ''"),
        ("assessments",   "is_deleted",      "INTEGER DEFAULT 0"),
    ]
    cursor = self.connection.cursor()
    for table, column, definition in migrations:
        try:
            cursor.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
        except Exception:
            pass  # columna ya existe
    self.connection.commit()
    cursor.close()
```

### Bloque B — Nuevas tablas
Implementar después del Bloque A:

1. `spatial_references` (vinculada a `assessments`)
2. `app_settings` (fila única de configuración)

### Bloque C — Diferir hasta integrar motores de análisis
- `metadata_nw`, `metadata_cdp`, `metadata_lpa`
- `aliases`, `output_aliases`
- `reports`
- Versioning completo (`VersionID`, `IsCurrent`)

---

## 5. Convenciones de nombres observadas en EMDS 8

```
SpatialReference overlay:  {assessment}__{overlay_name}
Input/overlay table:       {assessment}__Overlay
Results table:             {assessment}__{provenance}___results   (triple __)
Influence table:           {assessment}__{provenance}___results__IT
Influence rank table:      {assessment}__{provenance}___results__IRST
Output alias field:        nw0__{field_name}
Output alias display:      nw0__{field_name}__dd
```

**Diferencia con el plugin:** El plugin usa `{project}__{assessment}` (doble `__`)
donde EMDS 8 usa `{assessment}__{provenance}___results` (triple `___` antes del sufijo).
No es necesario cambiar la convención del plugin — son sistemas distintos que pueden
coexistir.

---

*Documento generado: 2026-02-14*
*Fuente: análisis de emdsInfo.Sqlite (EMDS 8, Entity Framework Core, 12 proyectos reales)*
