# Technical Adjustments — Assessment Wizard
> Documento de ajustes basado en revision tecnica con Steve (2026-02-14)
> Complementa `IMPLEMENTATION_ROADMAP.md` — No reemplaza las fases existentes.

---

## Estado actual implementado (Fases 1–3 + SOLID)

| Fase | Archivo | Estado |
|------|---------|--------|
| 1 | `admin_manager.py` | ✅ Completo |
| 2 | `project_manager.py` | ✅ Completo |
| 3 | `spatial_analysis_spatialite.py` | ✅ Completo |
| SOLID | `geometry_utils.py`, `map_tools.py`, `layer_migration.py`, `assessment_executor.py` | ✅ Completo |
| 4 | `main_form.py` (TreeView extendido) | ⏳ Pendiente |
| 5 | `assessment_wizard_dialog.py` (flujo completo) | ⏳ Pendiente |
| 6 | Limpieza legacy | ⏳ Pendiente |

---

## Ajuste 1 — Output del Assessment: 1 tabla final, no 2 temporales

### Problema actual
El wizard actualmente produce **2 capas de salida permanentes** por assessment:
- `project_x__assessment_name_intersection`
- `project_x__assessment_name_union`

### Comportamiento correcto (según conversacion)
La interseccion y la union son **pasos intermedios**. El output final es **UNA sola tabla base**:

```
Paso 1: Intersection(target, assessment_layer)  →  tabla temporal _tmp_intersect
Paso 2: Union(target, assessment_layer)         →  tabla temporal _tmp_union
Paso 3: La union ES la tabla base final         →  project_x__assessment_name  ✅
Paso 4: Eliminar tablas temporales              →  DROP _tmp_intersect, _tmp_union
```

La tabla base (`project_x__assessment_name`) es el **punto de partida para todos los análisis posteriores**. Todas las columnas adicionales se añaden sobre ella.

### Cambios requeridos en `assessment_executor.py`

```python
def execute_spatial_assessment(self, ...):
    # 1. Crear tablas temporales con sufijo _tmp
    tmp_intersect = pm.sanitize_table_name(f"{base_name}_tmp_intersect")
    tmp_union     = pm.sanitize_table_name(f"{base_name}_tmp_union")

    # 2. Ejecutar intersection → tabla temporal
    analyzer.analyze_and_create_layer(
        target_table, assessment_table, tmp_intersect,
        operation_type=OperationType.INTERSECT,
        add_to_qgis=False  # No agregar al mapa aún
    )

    # 3. Ejecutar union → tabla temporal
    analyzer.analyze_and_create_layer(
        target_table, assessment_table, tmp_union,
        operation_type=OperationType.UNION,
        add_to_qgis=False
    )

    # 4. Renombrar tabla union como tabla base final
    final_table = pm.sanitize_table_name(base_name)
    pm.rename_table(tmp_union, final_table)  # NUEVO método

    # 5. Eliminar tabla de intersección temporal
    pm.drop_table(tmp_intersect)

    # 6. Crear capa QGIS solo para la tabla final
    layer = analyzer._create_qgis_layer(final_table, base_name,
                                         group_name=self.OUTPUT_GROUP_NAME)

    return { 'output_tables': [final_table], ... }
```

### Nuevo método requerido en `project_manager.py`

```python
def rename_table(self, old_name, new_name):
    """Renombrar una tabla SpatiaLite y actualizar geometry_columns."""
    cursor = self.connection.cursor()

    # 1. Crear nueva tabla copiando estructura y datos
    cursor.execute(f"CREATE TABLE {new_name} AS SELECT * FROM {old_name}")

    # 2. Actualizar geometry_columns
    cursor.execute(
        "UPDATE geometry_columns SET f_table_name = ? WHERE f_table_name = ?",
        (new_name, old_name)
    )

    # 3. Eliminar tabla original
    self.drop_table(old_name)

    # 4. Recrear spatial index en nueva tabla
    cursor.execute(f"SELECT CreateSpatialIndex('{new_name}', 'geom')")
    self.connection.commit()
    cursor.close()
```

### Cambio en `spatial_analysis_spatialite.py`

Añadir parámetro `add_to_qgis=True` a `analyze_and_create_layer()` para controlar si se crea la capa QGIS o solo la tabla SpatiaLite:

```python
def analyze_and_create_layer(self, ..., add_to_qgis=True, group_name=None):
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

---

## Ajuste 2 — Provenance: rediseño de `workflow_steps`

### Problema actual
La tabla `workflow_steps` en `admin.sqlite` es demasiado plana:
```sql
workflow_steps(id, assessment_id, step_order, operation, parameters, created_at)
```
No soporta jerarquía de pasos (padre/hijo), ni registra tablas de entrada/salida, ni metadatos de rendimiento.

### Modelo correcto (EMDS 3 — según Steve)

```
Assessment
└── Provenance  (punto de inicio del workflow, primer análisis)
    ├── Task A  (análisis independiente — top level, parent_task_id = NULL)
    │   └── Task A.1  (hijo de A — parent_task_id = A.id)
    │       └── Task A.1.1  (nieto)
    └── Task B  (otro análisis independiente — top level)
        └── Task B.1
```

**Regla clave**: Tareas directamente bajo Provenance son **independientes entre sí**. Todo lo demás es jerárquico (padre→hijo).

### Nuevo schema propuesto para `admin.sqlite`

```sql
-- Reemplazar o extender workflow_steps:

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
    parent_task_id INTEGER DEFAULT NULL,  -- NULL = top level
    step_order INTEGER NOT NULL,
    operation TEXT NOT NULL,              -- 'intersect', 'union', 'CDP', 'NetWeaver', 'LPA', etc.
    category TEXT DEFAULT '',             -- tipo de análisis
    input_tables TEXT DEFAULT '',         -- JSON: ["table_a", "table_b"]
    output_tables TEXT DEFAULT '',        -- JSON: ["result_table"]
    db_type TEXT DEFAULT 'spatialite',
    added_to_map INTEGER DEFAULT 1,       -- bool: se agregó como capa QGIS
    scenario TEXT DEFAULT '',
    symbology TEXT DEFAULT '',
    duration_ms INTEGER DEFAULT 0,        -- tiempo de ejecución en ms
    parameters TEXT DEFAULT '',           -- JSON: parámetros adicionales
    comments TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (provenance_id) REFERENCES provenance(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_task_id) REFERENCES task_details(id) ON DELETE SET NULL
);
```

### Impacto en `admin_manager.py`

Nuevos métodos a añadir:

```python
# -- Provenance CRUD --
def create_provenance(self, assessment_id, name, description="") -> int
def get_provenance_for_assessment(self, assessment_id) -> [dict]
def delete_provenance(self, provenance_id)

# -- Task Details CRUD --
def add_task(self, provenance_id, step_order, operation,
             parent_task_id=None, input_tables=None, output_tables=None,
             category="", db_type="spatialite", added_to_map=True,
             duration_ms=0, parameters="", comments="") -> int

def get_tasks_for_provenance(self, provenance_id) -> [dict]
    # Retorna árbol jerárquico traversando parent_task_id

def get_child_tasks(self, parent_task_id) -> [dict]
def update_task_duration(self, task_id, duration_ms)
```

### Traversal del árbol de tareas

```python
def build_task_tree(self, provenance_id) -> list:
    """Construir árbol jerárquico de tareas para una provenance."""
    all_tasks = self.get_tasks_for_provenance(provenance_id)
    task_map = {t['id']: t for t in all_tasks}

    # Inicializar 'children' en cada tarea
    for t in all_tasks:
        t['children'] = []

    roots = []
    for t in all_tasks:
        pid = t.get('parent_task_id')
        if pid and pid in task_map:
            task_map[pid]['children'].append(t)
        else:
            roots.append(t)  # top-level

    return roots
```

---

## Ajuste 3 — Tabla base: añadir columnas en análisis posteriores

### Concepto
La tabla base (`project_x__assessment_name`) NO es estática. Cada análisis posterior puede **añadir columnas** a ella:

```
Tabla base inicial:
  input_id | identity_id | geom | split_type | shape_area | shape_length

Después de análisis CDP (paso 1 de provenance):
  input_id | identity_id | geom | split_type | shape_area | shape_length | cdp_priority_score

Después de análisis NetWeaver (hijo del CDP):
  ... | cdp_priority_score | netweaver_score | netweaver_category
```

### Nuevo método requerido en `project_manager.py`

```python
def add_column_to_table(self, table_name, column_name, column_type="REAL",
                         default_value=None):
    """Añadir columna a tabla existente para resultados de análisis adicionales."""
    cursor = self.connection.cursor()
    default_clause = f" DEFAULT {default_value}" if default_value is not None else ""
    cursor.execute(
        f'ALTER TABLE {table_name} ADD COLUMN "{column_name}" {column_type}{default_clause}'
    )
    self.connection.commit()
    cursor.close()

def update_column_values(self, table_name, column_name, id_value_pairs):
    """Actualizar valores de una columna por id.
    id_value_pairs: dict {row_id: value}
    """
    cursor = self.connection.cursor()
    for row_id, value in id_value_pairs.items():
        cursor.execute(
            f'UPDATE {table_name} SET "{column_name}" = ? WHERE id = ?',
            (value, row_id)
        )
    self.connection.commit()
    cursor.close()
```

---

## Ajuste 4 — Manejo de geometría 3D en migración

### Problema actual
Geometrías 3D (`PolygonZ`, `MultiPolygonZ`) causan errores durante la migración en `project_manager.py`.

### Causa probable
`AddGeometryColumn` con tipo `POLYGONZ` falla si SpatiaLite no puede manejar las coordenadas Z en `GeomFromText()`.

### Corrección en `project_manager.migrate_layer()`

```python
def migrate_layer(self, layer, table_name=None, progress_callback=None):
    ...
    # Al insertar features, forzar 2D si hay problemas con Z:
    try:
        geom_wkt = geometry.asWkt()
        cursor.execute(insert_sql, python_attrs + [geom_wkt, srid])
    except Exception:
        # Fallback: reducir a 2D
        geom_2d = geometry.get()
        geom_2d.dropZValue()  # QgsGeometry method
        geom_wkt_2d = geom_2d.asWkt() if hasattr(geom_2d, 'asWkt') else geometry.asWkt()
        cursor.execute(insert_sql, python_attrs + [geom_wkt_2d, srid])
        stats['errors'] += 1  # contar como advertencia, no error fatal
```

Alternativamente, forzar 2D para toda la migración si el tipo es `*Z`:

```python
# En migrate_layer, después de detectar geometry_type:
force_2d = 'Z' in geometry_type
if force_2d:
    geom_type_clean = geometry_type.replace('Z', '')
    dimension = 'XY'
```

---

## Ajuste 5 — Enriquecimiento de metadatos

### Campos adicionales sugeridos por Steve para futuras fases

#### En `projects` (`admin.sqlite`):
```sql
ALTER TABLE projects ADD COLUMN modified_at TEXT DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE projects ADD COLUMN map_document TEXT DEFAULT '';  -- nombre del .qgs
ALTER TABLE projects ADD COLUMN workspace_path TEXT DEFAULT '';
ALTER TABLE projects ADD COLUMN raster_sources TEXT DEFAULT '';  -- JSON: rutas de rasters
```

#### En `assessment_layers` (`admin.sqlite`):
```sql
ALTER TABLE assessment_layers ADD COLUMN source_path TEXT DEFAULT '';
ALTER TABLE assessment_layers ADD COLUMN symbology TEXT DEFAULT '';  -- JSON o path
ALTER TABLE assessment_layers ADD COLUMN comments TEXT DEFAULT '';
ALTER TABLE assessment_layers ADD COLUMN is_raster INTEGER DEFAULT 0;
ALTER TABLE assessment_layers ADD COLUMN raster_path TEXT DEFAULT '';
```

#### En `base_layers_registry` (`project_XXX.sqlite`):
```sql
ALTER TABLE base_layers_registry ADD COLUMN symbology TEXT DEFAULT '';
ALTER TABLE base_layers_registry ADD COLUMN comments TEXT DEFAULT '';
```

> **Nota**: Estos campos son opcionales para la implementación actual. Añadir cuando se llegue a Fase 4 o 5.

---

## Ajuste 6 — Limpieza automática de tablas temporales

### Problema
Acumulación de tablas temporales (`_tmp_intersect`, `_tmp_union`) en el archivo `.sqlite` del proyecto.

### Solución
`ProjectManager` debe rastrear y limpiar tablas temporales al iniciar:

```python
def cleanup_temp_tables(self):
    """Eliminar tablas temporales que quedaron de sesiones previas."""
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

Llamar `cleanup_temp_tables()` en `connect()` después de `_create_tables()`.

---

## Impacto en archivos existentes

| Archivo | Cambio | Prioridad |
|---------|--------|-----------|
| `assessment_executor.py` | Lógica de 1 tabla final + limpieza de temporales | **Alta** |
| `project_manager.py` | `rename_table()`, `add_column_to_table()`, `cleanup_temp_tables()`, fix 3D | **Alta** |
| `spatial_analysis_spatialite.py` | Parámetro `add_to_qgis=True` | **Alta** |
| `admin_manager.py` | Tablas `provenance` + `task_details`, nuevos métodos | **Media** (Fase 4) |
| `main_form.py` | TreeView con niveles Provenance → Task | **Media** (Fase 4) |

---

## Orden de implementación recomendado

```
AJUSTE 1 ── 1 tabla final (executor + project_manager + analyzer)
    │         [ANTES de Fase 4]
    │
AJUSTE 6 ── Limpieza automática de tablas temporales
    │         [Junto con Ajuste 1]
    │
AJUSTE 4 ── Fix geometría 3D en migración
    │         [Junto con Ajuste 1]
    │
FASE 4   ── TreeView extendido (main_form.py)
    │
AJUSTE 2 ── Provenance + task_details en admin_manager.py
    │         [Durante Fase 4, para mostrar en TreeView]
    │
AJUSTE 3 ── Añadir columnas a tabla base (análisis posteriores)
    │         [Durante Fase 5]
    │
AJUSTE 5 ── Enriquecimiento de metadatos (campos opcionales)
            [Durante Fase 5 o posterior]
```

---

## Flujo completo corregido (post-ajustes)

```
Usuario crea Assessment
│
├── project_XXX.sqlite:
│   ├── Migrar target_layer  →  tabla base (ej: landuse)
│   ├── Migrar assessment_layer  →  tabla (ej: cities)
│   ├── Intersection(landuse, cities)  →  TEMPORAL: project1__flood_tmp_intersect
│   ├── Union(landuse, cities)  →  TEMPORAL: project1__flood_tmp_union
│   ├── Renombrar union  →  FINAL: project1__flood  ✅ (tabla base)
│   ├── DROP project1__flood_tmp_intersect
│   ├── DROP project1__flood_tmp_union
│   └── INSERT base_layers_registry (landuse, cities)
│
├── admin.sqlite:
│   ├── INSERT assessments (uuid, project_id, 'flood', ...)
│   ├── INSERT assessment_layers (landuse → input, cities → input)
│   ├── INSERT assessment_layers (project1__flood → output)
│   └── INSERT provenance (assessment_id, 'Initial Analysis')
│       └── INSERT task_details (provenance_id, 'union+intersect', ...)
│
└── QGIS:
    └── Grupo "Output Layers"
        └── Layer project1__flood  (spatialite provider) ✅
```

---

## Notas adicionales de la conversacion

1. **Tabla base = overlay**: Steve usa el término "overlay name" para la tabla de salida del assessment. Es equivalente a `project_x__assessment_name`.

2. **Rasters**: Los rasters pueden estar embebidos en la BD o solo referenciados. Hay que registrar la ubicación en disco. Esto aplica principalmente cuando se llegue a la integración con Net Weaver y CDP.

3. **Jerarquía plana actual es suficiente**: Steve indicó que TCA (el cliente actual) solo usa Net Weaver models, por lo que la jerarquía de tasks no será muy profunda. Un nivel de Provenance + Tasks directos cubre el caso de uso actual.

4. **Comparación entre outputs**: En el futuro se podrán comparar outputs de diferentes análisis independientes (ramas del árbol de provenance). Esto no requiere implementación ahora, pero el schema de `task_details` con `parent_task_id` lo soporta.
