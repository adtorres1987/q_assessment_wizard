# Implementation Roadmap — Assessment Wizard (SpatiaLite)
> "Si no puedo reproducirlo, no es GIS profesional."
> Última actualización: 2026-02-14 — Integra ajustes técnicos de revisión con Steve.

---

## Arquitectura objetivo

```
assessment_wizard/
├── admin.sqlite                        ← metadatos centrales (proyectos, assessments, provenance)
├── projects/
│   ├── project_001.sqlite              ← datos espaciales por proyecto (SpatiaLite)
│   └── project_002.sqlite
├── admin_manager.py        ✅          ← gestiona admin.sqlite
├── project_manager.py      ✅          ← gestiona project_XXX.sqlite
├── spatial_analysis_spatialite.py ✅   ← análisis espacial SpatiaLite
├── geometry_utils.py       ✅          ← utilidades CRS/geometría (SOLID)
├── map_tools.py            ✅          ← herramientas de mapa (SOLID)
├── layer_migration.py      ✅          ← servicio de migración (SOLID)
├── assessment_executor.py  ✅          ← ejecutor de assessments (SOLID)
├── main_form.py            ⏳          ← UI principal con TreeView EMDS 3
├── assessment_wizard_dialog.py ⏳      ← wizard 3 páginas (flujo corregido)
├── assessment_wizard.py                ← entry point del plugin
└── [archivos legacy a eliminar]
```

---

## Estado general

| Fase | Descripción | Estado |
|------|-------------|--------|
| 1 | admin.sqlite + AdminManager | ✅ Completo |
| 2 | project_XXX.sqlite + ProjectManager | ✅ Completo |
| 3 | SpatialAnalyzerLite | ✅ Completo |
| SOLID | Refactor assessment_wizard_dialog.py | ✅ Completo |
| 2B | Ajustes a ProjectManager (nuevos métodos) | ✅ Completo |
| 3B | Output corregido: 1 tabla final | ✅ Completo |
| 4 | TreeView extendido + modelo Provenance | ✅ Completo |
| 5 | Wizard: flujo completo corregido | ✅ Completo |
| 6 | Limpieza legacy + metadatos enriquecidos | ✅ Completo |

---

## FASE 1 — admin.sqlite ✅ COMPLETO

### Schema implementado

```sql
projects          (id, uuid, name, description, db_path, created_at)
assessments       (id, uuid, project_id→FK, name, description, target_layer,
                   spatial_extent, created_at)
assessment_layers (id, assessment_id→FK, layer_name, layer_type, geometry_type)
layer_visibility_state (assessment_id→FK, layer_name, visible)
workflow_steps    (id, assessment_id→FK, step_order, operation, parameters, created_at)
```

### Pendiente en Fase 1: tablas Provenance (se implementan en Fase 4)

Las tablas `provenance` y `task_details` son parte del modelo EMDS 3 y se añaden
a `admin.sqlite` cuando se implemente el TreeView (Fase 4). Ver detalles allí.

---

## FASE 2 — project_XXX.sqlite ✅ COMPLETO

### Schema implementado

```sql
-- SpatiaLite inicializado con InitSpatialMetaData()
base_layers_registry       (id, layer_name, geometry_type, srid, source,
                            feature_count, created_at)
assessment_results_metadata (id, assessment_uuid, output_layer, operation,
                             source_target, source_assessment, feature_count, created_at)
-- Tablas espaciales dinámicas: migradas con AddGeometryColumn() + CreateSpatialIndex()
```

---

## FASE 2B — Ajustes a ProjectManager ⏳ PENDIENTE

### Objetivo
Añadir métodos necesarios para el flujo corregido (output 1 tabla final),
manejo de geometría 3D y limpieza de temporales.

### Método 1: `rename_table()`
Renombrar tabla SpatiaLite preservando registro en `geometry_columns`:

```python
def rename_table(self, old_name, new_name):
    """Renombrar tabla SpatiaLite y actualizar geometry_columns + spatial index."""
    cursor = self.connection.cursor()

    # 1. Copiar tabla con nuevo nombre
    cursor.execute(f"CREATE TABLE {new_name} AS SELECT * FROM {old_name}")

    # 2. Actualizar geometry_columns
    cursor.execute(
        "UPDATE geometry_columns SET f_table_name = ? WHERE f_table_name = ?",
        (new_name, old_name)
    )
    self.connection.commit()

    # 3. Eliminar tabla original (sin re-registrar geometry_columns)
    cursor.execute(f"DROP TABLE IF EXISTS {old_name}")

    # 4. Recrear spatial index en nueva tabla
    try:
        cursor.execute(f"SELECT CreateSpatialIndex('{new_name}', 'geom')")
        self.connection.commit()
    except Exception as e:
        print(f"Note: Could not recreate spatial index for {new_name}: {e}")

    cursor.close()
```

### Método 2: `add_column_to_table()`
Para añadir columnas de resultados a la tabla base en análisis posteriores:

```python
def add_column_to_table(self, table_name, column_name, column_type="REAL",
                         default_value=None):
    """Añadir columna a tabla existente (análisis posteriores)."""
    cursor = self.connection.cursor()
    default_clause = f" DEFAULT {default_value}" if default_value is not None else ""
    cursor.execute(
        f'ALTER TABLE {table_name} ADD COLUMN "{column_name}" {column_type}{default_clause}'
    )
    self.connection.commit()
    cursor.close()
```

### Método 3: `update_column_values()`

```python
def update_column_values(self, table_name, column_name, id_value_pairs):
    """Actualizar valores de columna por id. id_value_pairs: {row_id: value}"""
    cursor = self.connection.cursor()
    for row_id, value in id_value_pairs.items():
        cursor.execute(
            f'UPDATE {table_name} SET "{column_name}" = ? WHERE id = ?',
            (value, row_id)
        )
    self.connection.commit()
    cursor.close()
```

### Método 4: `cleanup_temp_tables()`
Eliminar tablas `_tmp_` que quedaron de sesiones anteriores:

```python
def cleanup_temp_tables(self):
    """Eliminar tablas temporales de sesiones previas (patrón *_tmp_*)."""
    cursor = self.connection.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%_tmp_%'"
    )
    temp_tables = [row[0] for row in cursor.fetchall()]
    cursor.close()
    for table in temp_tables:
        self.drop_table(table)
        print(f"Cleanup: dropped temp table '{table}'")
```

Llamar en `connect()` después de `_create_tables()`:
```python
def connect(self):
    ...
    self._create_tables()
    self.cleanup_temp_tables()  # ← añadir aquí
```

### Fix 5: Geometría 3D en `migrate_layer()`
Manejo de PolygonZ / MultiPolygonZ con fallback a 2D:

```python
# En migrate_layer(), dentro del loop de features:
try:
    geom_wkt = geometry.asWkt()
    cursor.execute(insert_sql, python_attrs + [geom_wkt, srid])
    stats['inserted'] += 1
except Exception:
    # Fallback: reducir a 2D
    geom_2d = QgsGeometry(geometry)
    geom_2d.get().dropZValue()
    geom_wkt_2d = geom_2d.asWkt()
    try:
        cursor.execute(insert_sql, python_attrs + [geom_wkt_2d, srid])
        stats['inserted'] += 1
    except Exception as e2:
        print(f"Error inserting feature (2D fallback failed): {e2}")
        stats['errors'] += 1
```

### Verificación Fase 2B
- [ ] `rename_table()` renombra tabla y actualiza `geometry_columns`
- [ ] `add_column_to_table()` añade columna sin perder datos existentes
- [ ] `cleanup_temp_tables()` se ejecuta al conectar, elimina `*_tmp_*`
- [ ] Geometrías 3D (PolygonZ, MultiPolygonZ) se migran sin error (fallback 2D)

---

## FASE 3 — SpatialAnalyzerLite ✅ COMPLETO

### Implementado
- `analyze_and_create_layer()` con parámetros `operation_type` y `group_name`
- `_build_intersect_query()` optimizado (Intersection calculado 1 vez)
- `_build_union_query()` optimizado (GUnion calculado 1 vez)
- `_detect_geometry_info()` + fallback en `RecoverGeometryColumn`
- Capas añadidas al grupo "Output Layers" en el layer tree

---

## FASE 3B — Output corregido: 1 tabla final ⏳ PENDIENTE

### Contexto
Actualmente el wizard produce 2 capas permanentes (`_intersection` + `_union`).
El comportamiento correcto es: **1 sola tabla base** por assessment.
La intersección y union son pasos intermedios (temporales). La **union es la tabla base final**.

### Flujo correcto

```
Intersect(target, assessment_layer) → tabla TEMPORAL: {base_name}_tmp_intersect
Union(target, assessment_layer)     → tabla TEMPORAL: {base_name}_tmp_union
rename(_tmp_union → {base_name})    → tabla FINAL:    project_x__assessment_name ✅
DROP _tmp_intersect
DROP _tmp_union
Crear capa QGIS solo de la tabla final
```

### Cambio 1: parámetro `add_to_qgis` en `spatial_analysis_spatialite.py`

```python
def analyze_and_create_layer(self, target_table, assessment_table, output_table,
                             layer_name=None, operation_type=OperationType.BOTH,
                             group_name=None, add_to_qgis=True):   # ← nuevo parámetro
    ...
    layer = None
    if add_to_qgis:
        layer = self._create_qgis_layer(output_table, layer_name, group_name)

    return {
        'total_count': total_count,
        'output_table': output_table,
        'layer': layer,
        'success': True
    }
```

### Cambio 2: reescribir `execute_spatial_assessment()` en `assessment_executor.py`

```python
def execute_spatial_assessment(self, assessment_name, target_layer,
                                assessment_layers, description,
                                parent_widget=None):
    project_db_path = self.admin_manager.get_project_db_path(self.project_db_id)
    pm = ProjectManager(project_db_path)
    pm.connect()

    target_table = pm.sanitize_table_name(target_layer.name())
    if not pm.table_exists(target_table):
        pm.migrate_layer(target_layer, target_table)

    for al in assessment_layers:
        at = pm.sanitize_table_name(al.name())
        if not pm.table_exists(at):
            pm.migrate_layer(al, at)

    analyzer = SpatialAnalyzerLite(pm)
    output_tables = []

    for assessment_layer in assessment_layers:
        assessment_table = pm.sanitize_table_name(assessment_layer.name())

        if len(assessment_layers) == 1:
            base_name = f"{self.project_id}__{assessment_name}"
        else:
            safe = assessment_layer.name().replace(' ', '_')
            base_name = f"{self.project_id}__{assessment_name}_{safe}"

        tmp_intersect = pm.sanitize_table_name(f"{base_name}_tmp_intersect")
        tmp_union     = pm.sanitize_table_name(f"{base_name}_tmp_union")
        final_table   = pm.sanitize_table_name(base_name)

        # Paso 1: Intersection → tabla temporal (sin capa QGIS)
        analyzer.analyze_and_create_layer(
            target_table, assessment_table, tmp_intersect,
            operation_type=OperationType.INTERSECT,
            add_to_qgis=False
        )

        # Paso 2: Union → tabla temporal (sin capa QGIS)
        analyzer.analyze_and_create_layer(
            target_table, assessment_table, tmp_union,
            operation_type=OperationType.UNION,
            add_to_qgis=False
        )

        # Paso 3: Renombrar union como tabla base final
        pm.rename_table(tmp_union, final_table)

        # Paso 4: Eliminar temporales
        pm.drop_table(tmp_intersect)

        # Paso 5: Crear capa QGIS solo de la tabla final
        layer = analyzer._create_qgis_layer(
            final_table, base_name, group_name=self.OUTPUT_GROUP_NAME
        )
        output_tables.append({'table': final_table, 'layer': layer})

    pm.disconnect()

    if output_tables:
        names = "\n• ".join(o['layer'].name() for o in output_tables)
        QMessageBox.information(
            parent_widget, "Analysis Complete",
            f"Assessment created successfully!\n\nBase layer(s):\n• {names}"
        )

    return {
        'assessment_name': assessment_name,
        'target_layer': target_layer.name(),
        'assessment_layers': [l.name() for l in assessment_layers],
        'output_tables': [o['table'] for o in output_tables],
        'description': description
    }
```

### Verificación Fase 3B
- [ ] Solo se crea 1 capa QGIS por assessment (la tabla base final)
- [ ] Tablas `_tmp_intersect` y `_tmp_union` no aparecen en el `.sqlite` al terminar
- [ ] La tabla final se llama `project_x__assessment_name` (sin sufijo)
- [ ] Grupo "Output Layers" contiene solo la capa final
- [ ] El `base_layers_registry` y `assessment_results_metadata` registran correctamente

---

## FASE 4 — TreeView extendido + modelo Provenance ⏳ PENDIENTE

### Objetivo
Conectar `main_form.py` a `admin_manager.py` e implementar el modelo EMDS 3 completo:
Project → Base Layers / Assessments → Provenance → Task

### 4A — Tablas Provenance en admin.sqlite

Añadir a `admin_manager.py` (`_create_tables()`):

```sql
CREATE TABLE IF NOT EXISTS provenance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE NOT NULL,
    assessment_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS task_details (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE NOT NULL,
    provenance_id INTEGER NOT NULL,
    parent_task_id INTEGER DEFAULT NULL,   -- NULL = top level, otra id = hijo
    step_order INTEGER NOT NULL,
    operation TEXT NOT NULL,               -- 'union', 'intersect', 'CDP', 'NetWeaver', 'LPA'
    category TEXT DEFAULT '',
    input_tables TEXT DEFAULT '',          -- JSON: ["tabla_a", "tabla_b"]
    output_tables TEXT DEFAULT '',         -- JSON: ["tabla_resultado"]
    db_type TEXT DEFAULT 'spatialite',
    added_to_map INTEGER DEFAULT 1,        -- bool
    scenario TEXT DEFAULT '',
    symbology TEXT DEFAULT '',
    duration_ms INTEGER DEFAULT 0,
    parameters TEXT DEFAULT '',            -- JSON: parámetros adicionales
    comments TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (provenance_id) REFERENCES provenance(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_task_id) REFERENCES task_details(id) ON DELETE SET NULL
);
```

**Jerarquía de tareas:**
```
Provenance (punto de inicio del workflow)
├── Task A  [parent_task_id = NULL]  ← análisis independiente
│   └── Task A.1  [parent_task_id = A.id]  ← hijo de A
│       └── Task A.1.1  [parent_task_id = A.1.id]
└── Task B  [parent_task_id = NULL]  ← otro análisis independiente
    └── Task B.1  [parent_task_id = B.id]
```

Nuevos métodos en `AdminManager`:

```python
# -- Provenance --
def create_provenance(self, assessment_id, name, description="") -> int
def get_provenance_for_assessment(self, assessment_id) -> [dict]
def delete_provenance(self, provenance_id)

# -- Task Details --
def add_task(self, provenance_id, step_order, operation,
             parent_task_id=None, input_tables=None, output_tables=None,
             category="", duration_ms=0, parameters="", comments="") -> int
def get_tasks_for_provenance(self, provenance_id) -> [dict]
def get_child_tasks(self, parent_task_id) -> [dict]
def update_task_duration(self, task_id, duration_ms)

def build_task_tree(self, provenance_id) -> list:
    """Retorna lista de tareas top-level con 'children' anidados."""
    all_tasks = self.get_tasks_for_provenance(provenance_id)
    task_map = {t['id']: dict(t, children=[]) for t in all_tasks}
    roots = []
    for t in task_map.values():
        pid = t.get('parent_task_id')
        if pid and pid in task_map:
            task_map[pid]['children'].append(t)
        else:
            roots.append(t)
    return roots
```

### 4B — TreeView 5 niveles (main_form.py)

```
Project A  [bold, tipo "project"]
├── Base Layers  [italic, grupo no seleccionable]
│   ├── landuse
│   └── cities
└── Assessments  [italic, grupo no seleccionable]
    └── Flood_Risk  [tipo "assessment"]
        └── Initial Analysis  [tipo "provenance"]
            └── Union+Intersect  [tipo "task", top-level]
                └── project_a__flood  [tipo "result", checkable ☑]
```

#### `selected_path` dict (reemplaza `self.current_project_id`):

```python
self.selected_path = {
    "project_id": None,
    "assessment_id": None,
    "provenance_id": None,
    "task_id": None
}
```

#### Clase separada `EMDSTreeModel`:

```python
class EMDSTreeModel:
    @staticmethod
    def populate_tree(tree_widget, admin_manager, project_db_id=None):
        """Poblar TreeWidget con jerarquía EMDS 3."""
        tree_widget.clear()
        projects = admin_manager.get_all_projects()
        for project in projects:
            project_item = QTreeWidgetItem([project['name']])
            project_item.setData(0, Qt.UserRole, {'type': 'project', **project})
            # Base Layers, Assessments → Provenance → Tasks → Results
            ...
```

#### Context menu por nivel:

```
Project      → "New Assessment", "Delete Project"
Assessment   → "Create Provenance", "Run Analysis Step", "Delete Assessment"
Provenance   → "Add Task", "Edit", "Delete"
Task         → "Add Sub-Task", "View Result", "Edit", "Delete"
Result       → "Toggle Visibility"
Base Layers  → "Register Layer"
[vacío]      → "New Project"
```

#### Dialogs especializados:

```python
dialog = CreateProjectDialog(self.available_layers, self)
dialog = CreateAssessmentDialog(available_layers=..., parent=self)
dialog = CreateProvenanceDialog(parent=self)
dialog = AddTaskDialog(provenance_id=..., parent_tasks=..., parent=self)
```

### Verificación Fase 4
- [ ] TreeView muestra 5 niveles: Project → Assessment → Provenance → Task → Result
- [ ] Base Layers se leen de `base_layers_registry` del project DB
- [ ] Output layers se leen de `assessment_layers` del admin DB
- [ ] Checkboxes persisten en `layer_visibility_state`
- [ ] Context menu funciona en cada nivel
- [ ] `selected_path` trackea la selección completa
- [ ] `EMDSTreeModel` separado del formulario
- [ ] Tablas `provenance` y `task_details` creadas en `admin.sqlite`
- [ ] `build_task_tree()` retorna árbol jerárquico correcto

---

## FASE 5 — Wizard: flujo completo corregido ✅ COMPLETO

### Objetivo
Conectar el wizard al flujo correcto: 1 tabla base final, registro de provenance,
y columnas extensibles para análisis posteriores.

### Flujo en `accept()` post-ajustes

```
Usuario completa wizard
│
├── project_XXX.sqlite:
│   ├── Migrar target_layer         → tabla 'landuse'
│   ├── Migrar assessment_layer     → tabla 'cities'
│   ├── Intersection(landuse,cities) → TEMPORAL: project_a__flood_tmp_intersect
│   ├── Union(landuse,cities)        → TEMPORAL: project_a__flood_tmp_union
│   ├── rename(_tmp_union)           → FINAL: project_a__flood  ✅
│   ├── DROP _tmp_intersect
│   └── INSERT base_layers_registry (landuse, cities)
│
├── admin.sqlite:
│   ├── INSERT assessments   (uuid, project_id, 'flood', ...)
│   ├── INSERT assessment_layers (landuse → input, cities → input)
│   ├── INSERT assessment_layers (project_a__flood → output)  ← 1 sola entrada
│   ├── INSERT layer_visibility_state (project_a__flood, visible=1)
│   ├── INSERT provenance    (assessment_id, 'Initial Analysis')
│   └── INSERT task_details  (provenance_id, 'union+intersect',
│                             input=['landuse','cities'],
│                             output=['project_a__flood'])
│
└── QGIS:
    └── Grupo "Output Layers"
        └── Layer project_a__flood  (spatialite provider) ✅ — 1 sola capa
```

### Cambios en `assessment_executor.py`

Después de ejecutar el análisis, registrar en provenance:

```python
def execute_spatial_assessment(self, ...):
    ...
    # Registrar provenance + task
    self._record_provenance(assessment_id, output_tables, target_layer, assessment_layers)
    ...

def _record_provenance(self, assessment_id, output_tables,
                        target_layer, assessment_layers):
    if not self.admin_manager:
        return
    provenance_id = self.admin_manager.create_provenance(
        assessment_id=assessment_id,
        name="Initial Assessment",
        description="Base spatial analysis: union + intersection"
    )
    import json
    self.admin_manager.add_task(
        provenance_id=provenance_id,
        step_order=1,
        operation="union+intersect",
        category="spatial_analysis",
        input_tables=json.dumps([target_layer.name()] +
                                [al.name() for al in assessment_layers]),
        output_tables=json.dumps(output_tables),
        added_to_map=True
    )
```

### Tabla base extensible — análisis posteriores

Al ejecutar un análisis posterior (CDP, NetWeaver, LPA), añadir columnas a la tabla base:

```python
# Ejemplo de uso (análisis posterior, fuera del wizard):
pm.add_column_to_table('project_a__flood', 'cdp_priority_score', 'REAL')
pm.update_column_values('project_a__flood', 'cdp_priority_score', {1: 0.8, 2: 0.5, ...})

# Registrar en task_details como hijo del task anterior:
admin_manager.add_task(
    provenance_id=provenance_id,
    step_order=2,
    operation="CDP",
    parent_task_id=initial_task_id,  # hijo del task de intersect/union
    input_tables=json.dumps(['project_a__flood']),
    output_tables=json.dumps(['project_a__flood']),  # misma tabla, nueva columna
)
```

### Verificación Fase 5
- [ ] Wizard produce exactamente 1 capa QGIS por assessment
- [ ] La tabla base se llama `project_x__assessment_name` (sin sufijos)
- [ ] Tablas temporales `_tmp_*` no persisten en `.sqlite`
- [ ] Provenance + task_details se registran en admin.sqlite al finalizar wizard
- [ ] TreeView se actualiza al cerrar wizard (mostrar nuevo assessment + provenance)
- [ ] Tabla base acepta columnas adicionales sin perder datos existentes

---

## FASE 6 — Limpieza legacy + metadatos enriquecidos ✅ COMPLETO

### Archivos a eliminar

| Archivo | Reemplazado por |
|---------|----------------|
| `metadata_manager.py` | `admin_manager.py` |
| `database_manager.py` | `project_manager.py` |
| `spatial_analysis.py` | `spatial_analysis_spatialite.py` |
| `SPATIAL_ANALYSIS_README.md` | Este roadmap |
| `projects/project_1.sqlite` (legacy) | Migrar o eliminar |

### Campos de metadatos adicionales (opcionales, post-MVP)

Añadir cuando se requiera trazabilidad completa:

```sql
-- En projects:
ALTER TABLE projects ADD COLUMN modified_at TEXT DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE projects ADD COLUMN map_document TEXT DEFAULT '';   -- nombre del .qgs
ALTER TABLE projects ADD COLUMN raster_sources TEXT DEFAULT ''; -- JSON: rutas rasters

-- En assessment_layers:
ALTER TABLE assessment_layers ADD COLUMN source_path TEXT DEFAULT '';
ALTER TABLE assessment_layers ADD COLUMN symbology TEXT DEFAULT '';  -- JSON o path
ALTER TABLE assessment_layers ADD COLUMN comments TEXT DEFAULT '';
ALTER TABLE assessment_layers ADD COLUMN is_raster INTEGER DEFAULT 0;
ALTER TABLE assessment_layers ADD COLUMN raster_path TEXT DEFAULT '';

-- En base_layers_registry (project DB):
ALTER TABLE base_layers_registry ADD COLUMN symbology TEXT DEFAULT '';
ALTER TABLE base_layers_registry ADD COLUMN comments TEXT DEFAULT '';
```

### Verificación Fase 6
- [ ] Plugin funciona sin PostgreSQL
- [ ] Sin imports a archivos eliminados
- [ ] Sin credenciales hardcoded
- [ ] `metadata.db` migrada o respaldada
- [ ] Tests de integración pasan (creación proyecto → assessment → análisis → TreeView)

---

## Orden de implementación

```
FASE 2B ── rename_table(), add_column(), cleanup_temp(), fix 3D
    │       [Prerequisito para Fase 3B]
    │
FASE 3B ── Output: 1 tabla final (executor + analyzer)
    │       [Prerequisito para Fase 4 — corrige el flujo antes de TreeView]
    │
FASE 4  ── TreeView EMDS 3 + tablas provenance/task_details
    │       [Depende de 2B + 3B]
    │
FASE 5  ── Wizard flujo completo + registro provenance
    │       [Depende de Fase 4]
    │
FASE 6  ── Limpieza legacy + campos opcionales
            [Al final, cuando todo funciona]
```

---

## Resumen de archivos

| Archivo | Acción | Fase |
|---------|--------|------|
| `admin_manager.py` | MODIFICAR: tablas provenance + task_details | 4 |
| `project_manager.py` | MODIFICAR: rename_table, add_column, cleanup_temp, 3D fix | 2B |
| `spatial_analysis_spatialite.py` | MODIFICAR: parámetro add_to_qgis | 3B |
| `assessment_executor.py` | MODIFICAR: flujo 1 tabla final + provenance | 3B, 5 |
| `main_form.py` | MODIFICAR: TreeView EMDS 3, EMDSTreeModel, selected_path | 4 |
| `assessment_wizard_dialog.py` | MODIFICAR: flujo corregido | 5 |
| `metadata_manager.py` | ELIMINAR | 6 |
| `database_manager.py` | ELIMINAR | 6 |
| `spatial_analysis.py` | ELIMINAR | 6 |
