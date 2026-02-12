# Implementation Roadmap — Hybrid Database Architecture

> "Si no puedo reproducirlo, no es GIS profesional."

---

## Arquitectura Objetivo

```
assessment_wizard/                          ← plugin directory
├── admin.sqlite                            ← metadatos centrales
├── projects/                               ← carpeta de proyectos
│   ├── project_001.sqlite                  ← datos espaciales (SpatiaLite)
│   ├── project_002.sqlite
│   └── project_003.sqlite
├── admin_manager.py                        ← gestiona admin.sqlite
├── project_manager.py                      ← gestiona project_XXX.sqlite
├── spatial_analysis_sketlite.py            ← analisis con SpatiaLite
├── main_form.py                            ← UI principal con TreeView
├── assessment_wizard.py                    ← entry point del plugin
├── assessment_wizard_dialog.py             ← wizard de 3 paginas
└── ...
```

---

## Estado actual vs Objetivo

| Componente | Actual | Objetivo |
|---|---|---|
| DB metadatos | `metadata.db` (1 global) | `admin.sqlite` (5 tablas) |
| DB espacial | PostgreSQL/PostGIS (`database_manager.py`) | SpatiaLite por proyecto (`project_manager.py`) |
| Analisis | `spatial_analysis.py` (PostGIS SQL) | SpatiaLite SQL (funciones equivalentes) |
| TreeView | Project → Assessment (2 niveles) | Project → Base Layers / Assessments → Provenance (4 niveles) |
| Visibilidad | En memoria (se pierde al cerrar) | Persistida en `layer_visibility_state` |
| Capas | Leidas directo de QGIS | Registradas en `assessment_layers` + `base_layers_registry` |

---

## FASE 1 — admin.sqlite (Evolucion de metadata_manager.py)

### Objetivo
Migrar `metadata_manager.py` → `admin_manager.py` con el esquema completo de `admin.sqlite`.

### Archivo: `admin_manager.py` (NUEVO, reemplaza `metadata_manager.py`)

### Schema completo

```sql
-- Tabla 1: projects
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL UNIQUE,
    description TEXT DEFAULT '',
    db_path TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Tabla 2: assessments
CREATE TABLE IF NOT EXISTS assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE NOT NULL,
    project_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    spatial_extent TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, name),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

-- Tabla 3: assessment_layers
CREATE TABLE IF NOT EXISTS assessment_layers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_id INTEGER NOT NULL,
    layer_name TEXT NOT NULL,
    layer_type TEXT NOT NULL CHECK(layer_type IN ('input', 'output', 'reference')),
    geometry_type TEXT DEFAULT '',
    FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE CASCADE
);

-- Tabla 4: layer_visibility_state
CREATE TABLE IF NOT EXISTS layer_visibility_state (
    assessment_id INTEGER NOT NULL,
    layer_name TEXT NOT NULL,
    visible INTEGER DEFAULT 1,
    PRIMARY KEY (assessment_id, layer_name),
    FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE CASCADE
);

-- Tabla 5: workflow_steps
CREATE TABLE IF NOT EXISTS workflow_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_id INTEGER NOT NULL,
    step_order INTEGER NOT NULL,
    operation TEXT NOT NULL,
    parameters TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE CASCADE
);
```

### Clase: `AdminManager`

```python
class AdminManager:
    def __init__(self, plugin_dir):
        self.db_path = os.path.join(plugin_dir, "admin.sqlite")
        self.projects_dir = os.path.join(plugin_dir, "projects")
        self.connection = None

    # -- Conexion --
    def connect(self)
    def disconnect(self)
    def _create_tables(self)

    # -- Projects CRUD --
    def create_project(self, name, description="")    → int (project_id)
        # 1. Generar UUID (uuid4)
        # 2. Crear carpeta projects/ si no existe
        # 3. Calcular db_path relativo: "projects/{sanitized_name}.sqlite"
        # 4. INSERT en projects
        # 5. Retornar project_id
    def get_all_projects(self)                         → [dict]
    def get_project(self, project_id)                  → dict | None
    def get_project_by_name(self, name)                → dict | None
    def delete_project(self, project_id)
        # 1. Obtener db_path del proyecto
        # 2. DELETE FROM projects (CASCADE borra assessments, layers, etc.)
        # 3. Eliminar archivo .sqlite del proyecto en disco

    # -- Assessments CRUD --
    def create_assessment(self, project_id, name, description="", spatial_extent="") → int
        # Generar UUID, INSERT
    def get_assessments_for_project(self, project_id)  → [dict]
    def assessment_name_exists(self, project_id, name) → bool
    def delete_assessment(self, assessment_id)

    # -- Assessment Layers --
    def add_assessment_layer(self, assessment_id, layer_name, layer_type, geometry_type="")
    def get_assessment_layers(self, assessment_id, layer_type=None) → [dict]
        # layer_type=None retorna todas, 'input'|'output'|'reference' filtra
    def remove_assessment_layers(self, assessment_id)

    # -- Layer Visibility State --
    def set_layer_visibility(self, assessment_id, layer_name, visible)
        # INSERT OR REPLACE
    def get_layer_visibility(self, assessment_id) → dict {layer_name: bool}
    def get_visible_layers(self, assessment_id) → [str]

    # -- Workflow Steps --
    def add_workflow_step(self, assessment_id, step_order, operation, parameters="")
    def get_workflow_steps(self, assessment_id) → [dict]

    # -- Utilidades --
    def get_project_db_path(self, project_id) → str (ruta absoluta al .sqlite)
```

### Cambios respecto a `metadata_manager.py`

| Antes (`metadata_manager.py`) | Despues (`admin_manager.py`) |
|---|---|
| `metadata.db` | `admin.sqlite` |
| `projects` sin UUID ni db_path | `projects` con UUID + db_path |
| `assessments` con JSON fields | `assessments` sin JSON, + UUID, + spatial_extent |
| JSON `assessment_layers` column | Tabla normalizada `assessment_layers` |
| JSON `output_tables` column | Registrado en `assessment_layers` con `layer_type='output'` |
| Sin visibilidad persistida | Tabla `layer_visibility_state` |
| Sin workflow | Tabla `workflow_steps` |

### Migracion de datos existentes

```python
def migrate_from_metadata_db(self, old_db_path):
    """Migrar datos de metadata.db al nuevo admin.sqlite."""
    # 1. Leer projects de metadata.db
    # 2. Para cada project: crear en admin.sqlite con UUID y db_path generados
    # 3. Leer assessments y re-insertar con UUID
    # 4. Parsear JSON assessment_layers/output_tables → insertar en assessment_layers
    # 5. Renombrar/eliminar metadata.db
```

### Verificacion Fase 1

- [ ] `admin.sqlite` se crea con 5 tablas al iniciar plugin
- [ ] Carpeta `projects/` se crea automaticamente
- [ ] Projects se crean con UUID y db_path
- [ ] Assessments se crean con UUID, sin campos JSON
- [ ] `assessment_layers` almacena input/output/reference correctamente
- [ ] `layer_visibility_state` persiste y recupera estado de checkboxes
- [ ] `metadata_manager.py` se puede eliminar sin romper nada
- [ ] Si existe `metadata.db`, se migran datos automaticamente

---

## FASE 2 — project_XXX.sqlite (SpatiaLite)

### Objetivo
Crear `project_manager.py` que gestione bases de datos SpatiaLite individuales por proyecto.

### Archivo: `project_manager.py` (NUEVO, reemplaza `database_manager.py`)

### Schema del project DB

```sql
-- Inicializar SpatiaLite
SELECT InitSpatialMetaData();

-- Tabla 1: base_layers_registry
CREATE TABLE IF NOT EXISTS base_layers_registry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    layer_name TEXT UNIQUE NOT NULL,
    geometry_type TEXT DEFAULT '',
    srid INTEGER DEFAULT 4326,
    source TEXT DEFAULT '',
    feature_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Tabla 2: assessment_results_metadata
CREATE TABLE IF NOT EXISTS assessment_results_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_uuid TEXT NOT NULL,
    output_layer TEXT NOT NULL,
    operation TEXT NOT NULL,
    source_target TEXT DEFAULT '',
    source_assessment TEXT DEFAULT '',
    feature_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

Las tablas espaciales (datos reales) se crean dinamicamente con `AddGeometryColumn()`.

### Clase: `ProjectManager`

```python
class ProjectManager:
    def __init__(self, db_path):
        self.db_path = db_path  # ruta absoluta al project_XXX.sqlite
        self.connection = None

    # -- Conexion --
    def connect(self)
        # 1. sqlite3.connect(db_path)
        # 2. connection.enable_load_extension(True)
        # 3. connection.load_extension("mod_spatialite")
        # 4. Si DB nueva: SELECT InitSpatialMetaData()
        # 5. _create_tables()
    def disconnect(self)
    def _create_tables(self)

    # -- Base Layers Registry --
    def register_base_layer(self, layer_name, geometry_type, srid, source, feature_count)
    def get_registered_layers(self) → [dict]
    def is_layer_registered(self, layer_name) → bool
    def unregister_layer(self, layer_name)

    # -- Migracion de capas QGIS → SpatiaLite --
    def migrate_layer(self, qgis_layer, table_name=None, progress_callback=None) → dict
        # Equivalente a DatabaseManager.migrate_layer() pero para SpatiaLite:
        # 1. sanitize_table_name()
        # 2. CREATE TABLE con columnas del layer
        # 3. AddGeometryColumn(table, 'geom', srid, geom_type, 'XY')
        # 4. INSERT features con GeomFromText()
        # 5. CreateSpatialIndex(table, 'geom')
        # 6. Registrar en base_layers_registry
        # Retorna stats: {inserted, errors, table_name}
    def migrate_layers(self, layers_dict, progress_callback=None) → [dict]

    # -- Consultas sobre tablas espaciales --
    def table_exists(self, table_name) → bool
    def drop_table(self, table_name)
    def get_table_srid(self, table_name) → int
    def get_table_geometry_type(self, table_name) → str

    # -- Assessment Results --
    def record_result(self, assessment_uuid, output_layer, operation,
                      source_target="", source_assessment="", feature_count=0)
    def get_results_for_assessment(self, assessment_uuid) → [dict]

    # -- Utilidades --
    def sanitize_table_name(self, layer_name) → str
        # Misma logica que database_manager.py (preservar __ separator)
    def get_spatialite_type(self, qgis_layer) → str
        # Mapeo QgsWkbTypes → SpatiaLite types
```

### Equivalencias PostGIS → SpatiaLite

| PostGIS (`database_manager.py`) | SpatiaLite (`project_manager.py`) |
|---|---|
| `CREATE EXTENSION IF NOT EXISTS postgis` | `SELECT InitSpatialMetaData()` |
| `GEOMETRY(type, srid)` inline en CREATE | `SELECT AddGeometryColumn(table, col, srid, type, dim)` |
| `ST_GeomFromText(wkt, srid)` | `GeomFromText(wkt, srid)` |
| `ST_AsText(geom)` | `AsText(geom)` |
| `CREATE INDEX ... USING GIST` | `SELECT CreateSpatialIndex(table, col)` |
| `information_schema.tables` | `sqlite_master WHERE type='table'` |
| `geometry_columns` system table | `geometry_columns` (creada por InitSpatialMetaData) |
| `psycopg2.connect(host, db, ...)` | `sqlite3.connect(path)` + `load_extension('mod_spatialite')` |

### SpatiaLite en macOS / QGIS

```python
# QGIS incluye SpatiaLite. La extension se carga asi:
import sqlite3

conn = sqlite3.connect(db_path)
conn.enable_load_extension(True)

# macOS con QGIS:
conn.load_extension("mod_spatialite")
# Si falla, intentar ruta completa:
# conn.load_extension("/Applications/QGIS.app/Contents/MacOS/lib/mod_spatialite")
```

### Verificacion Fase 2

- [ ] `projects/` contiene archivos `.sqlite` creados al crear proyecto
- [ ] SpatiaLite se inicializa correctamente (`InitSpatialMetaData`)
- [ ] Capas QGIS se migran a SpatiaLite con geometria intacta
- [ ] `base_layers_registry` registra cada capa migrada
- [ ] `assessment_results_metadata` registra outputs con `assessment_uuid`
- [ ] Indices espaciales se crean (`CreateSpatialIndex`)
- [ ] `database_manager.py` se puede eliminar sin romper nada
- [ ] Al borrar proyecto, el archivo `.sqlite` se elimina del disco

---

## FASE 3 — Analisis Espacial con SpatiaLite

### Objetivo
Adaptar `spatial_analysis.py` para usar SpatiaLite en vez de PostGIS.

### Archivo: `spatial_analysis_sketlite.py` (NUEVO, reemplaza `spatial_analysis.py`)

### Equivalencias SQL

```sql
-- INTERSECTION (PostGIS)
ST_Intersection(a.geom, b.geom)
a.geom && b.geom AND ST_Intersects(a.geom, b.geom)
ST_Area(geom)
ST_Perimeter(geom)
GeometryType(geom) IN ('POLYGON', 'MULTIPOLYGON')
ST_IsValid(geom)

-- INTERSECTION (SpatiaLite)
Intersection(a.geom, b.geom)
Intersects(a.geom, b.geom)        -- usa R-Tree si existe spatial index
Area(geom)
Perimeter(geom)
GeometryType(geom) IN ('POLYGON', 'MULTIPOLYGON')  -- igual
IsValid(geom)                      -- disponible desde SpatiaLite 4.0+
```

### Clase: `SpatialAnalyzerLite`

```python
class SpatialAnalyzerLite:
    def __init__(self, project_manager):
        self.pm = project_manager  # ProjectManager con conexion activa

    def analyze_and_create_layer(self, target_table, assessment_table, output_table,
                                 layer_name=None, operation_type=OperationType.INTERSECT)
        # 1. Validar tablas existen
        # 2. Validar compatibilidad de geometria (SRID, tipo)
        # 3. DROP TABLE IF EXISTS output
        # 4. Ejecutar query (intersect/union)
        # 5. Registrar resultado en assessment_results_metadata
        # 6. Crear QGIS layer desde SpatiaLite
        # 7. Retornar dict con total_count, layer, success

    def _create_qgis_layer(self, table_name, layer_name=None)
        # URI para SpatiaLite:
        # uri = f"dbname='{db_path}' table='{table_name}' (geom)"
        # layer = QgsVectorLayer(uri, layer_name, "spatialite")

    def _build_intersect_query(self, target, assessment, output) → str
    def _build_union_query(self, target, assessment, output) → str
    def validate_geometry_compatibility(self, target, assessment) → dict
```

### Diferencia clave: creacion de QGIS layer

```python
# Antes (PostGIS):
uri = QgsDataSourceUri()
uri.setConnection("localhost", "5432", "wizard_db", "postgres", "user123")
uri.setDataSource("public", table_name, "geom")
layer = QgsVectorLayer(uri.uri(), name, "postgres")

# Despues (SpatiaLite):
uri = f"dbname='{self.pm.db_path}' table='{table_name}' (geom)"
layer = QgsVectorLayer(uri, name, "spatialite")
```

### Verificacion Fase 3

- [ ] Intersection genera resultados identicos a PostGIS
- [ ] Union genera resultados identicos a PostGIS
- [ ] Layers de salida se cargan correctamente en QGIS como `spatialite` provider
- [ ] `assessment_results_metadata` se llena con cada operacion
- [ ] `spatial_analysis.py` original se puede eliminar
- [ ] No se requiere PostgreSQL para ejecutar el plugin

---

## FASE 4 — Adaptar main_form.py (TreeView extendido)

### Objetivo
Conectar el TreeView a `admin_manager.py` y persistir visibilidad en `layer_visibility_state`.

### Cambios en `main_form.py`

```python
# Antes:
from .metadata_manager import MetadataManager

# Despues:
from .admin_manager import AdminManager
```

### TreeView extendido (4 niveles)

```
Project A  (bold, tipo "project")
├── Base Layers  (italic, tipo "group", no seleccionable)
│   ├── buildings_osm
│   └── roads_primary
└── Assessments  (italic, tipo "group", no seleccionable)
    └── Flood_Risk  (checkable, tipo "assessment")
        ├── ☑ CityPlan__Flood_intersect  (tipo "output_layer")
        └── ☑ CityPlan__Flood_union      (tipo "output_layer")
```

### Visibilidad persistida

```python
# Al cargar TreeView:
visibility = self.admin_manager.get_layer_visibility(assessment_id)
for layer_name, visible in visibility.items():
    item.setCheckState(0, Qt.Checked if visible else Qt.Unchecked)

# Al cambiar checkbox (itemChanged signal):
self.admin_manager.set_layer_visibility(assessment_id, layer_name, checked)
# + toggle en QGIS layer tree
```

### Context menu extendido (modelo EMDS 3)

```
Click derecho en Project     → "New Assessment", "Delete Project"
Click derecho en Assessment  → "Create Provenance", "Run Analysis", "Delete Assessment"
Click derecho en Provenance  → "Create Workflow Step", "Edit Provenance", "Delete Provenance"
Click derecho en Workflow    → "Create Sub-Workflow Step", "View Result", "Edit Step", "Delete Step"
Click derecho en Results     → "View in Engine Viewer", "Toggle Visibility"
Click derecho en Base Layers → "Register Layer"
Click derecho en vacio       → "New Project"
```

### Recomendaciones de refactor (basadas en prototipo EMDS 3)

Adoptar los siguientes patrones del prototipo EMDS 3 para escalar el TreeView:

1. **`selected_path` dict** — Reemplazar `self.current_project_id` (escalar) por un dict
   que trackee la seleccion completa del arbol:
   ```python
   self.selected_path = {
       "project_id": None,
       "assessment_id": None,
       "provenance_id": None,
       "workflow_id": None
   }
   ```

2. **`EMDSTreeModel` separado** — Extraer la logica de poblacion del tree en su propia clase:
   ```python
   class EMDSTreeModel:
       @staticmethod
       def populate_tree(tree_widget, project_manager):
           # Logica de poblacion separada del formulario
   ```

3. **Dialogs especializados** — Reemplazar `QInputDialog` con dialogs que reciban
   `available_layers` y capturen mas datos:
   ```python
   dialog = CreateProjectDialog(self.available_layers, self)
   project = dialog.get_project()

   dialog = CreateAssessmentDialog(self.available_layers, self)
   assessment = dialog.get_assessment()

   dialog = CreateProvenanceDialog(self)
   provenance = dialog.get_provenance()
   ```

4. **Senales Qt** — Emitir senales al crear/eliminar entidades para desacoplar componentes:
   ```python
   self.project_created.emit(project)
   self.assessment_created.emit(assessment)
   ```

5. **TreeView completo EMDS 3** (5+ niveles):
   ```
   Project A  (bold, tipo "project")
   ├── Base Layers  (italic, grupo)
   │   ├── buildings_osm
   │   └── roads_primary
   └── Assessments  (italic, grupo)
       └── Flood_Risk  (tipo "assessment")
           └── Water_Analysis  (tipo "provenance")
               ├── Step 1: Buffer  (tipo "workflow")
               │   └── buffer_result  (tipo "results", checkable)
               └── Step 2: Intersect  (tipo "workflow")
                   └── intersect_result  (tipo "results", checkable)
   ```

### Verificacion Fase 4

- [ ] TreeView muestra niveles EMDS 3 (Project → Assessment → Provenance → Workflow → Results)
- [ ] Base Layers se leen de `base_layers_registry` del project DB
- [ ] Output layers se leen de `assessment_layers` del admin DB
- [ ] Checkboxes persisten al cerrar y reabrir el formulario
- [ ] Context menu funciona en cada nivel del arbol
- [ ] Seleccionar assessment muestra sus detalles (layers, workflow steps)
- [ ] `selected_path` dict trackea la seleccion completa
- [ ] `EMDSTreeModel` separado de `main_form.py`
- [ ] Dialogs especializados para Project, Assessment, Provenance

---

## FASE 5 — Adaptar assessment_wizard_dialog.py

### Objetivo
Conectar el wizard al nuevo flujo de datos (admin + project DBs).

### Cambios principales

```python
# Constructor — recibe ambos managers
def __init__(self, parent=None, iface=None, project_id="",
             admin_manager=None, project_manager=None,
             project_db_id=None, assessment_uuid=None):

# En accept():
# 1. Validar duplicados via admin_manager.assessment_name_exists()
# 2. Crear assessment en admin_manager.create_assessment() → obtener uuid
# 3. Registrar input layers en admin_manager.add_assessment_layer(type='input')
# 4. Migrar capas a SpatiaLite via project_manager.migrate_layer()
# 5. Ejecutar analisis via SpatialAnalyzerLite
# 6. Registrar output layers en admin_manager.add_assessment_layer(type='output')
# 7. Registrar workflow_steps en admin_manager
# 8. Registrar results en project_manager.record_result()
```

### Flujo de datos en accept()

```
Usuario completa wizard
│
├── admin.sqlite:
│   ├── INSERT assessment (uuid, project_id, name, description, spatial_extent)
│   ├── INSERT assessment_layers (assessment_id, 'buildings', 'input')
│   ├── INSERT assessment_layers (assessment_id, 'CityPlan__Flood_intersect', 'output')
│   ├── INSERT assessment_layers (assessment_id, 'CityPlan__Flood_union', 'output')
│   ├── INSERT layer_visibility_state (assessment_id, layer, visible=1)
│   └── INSERT workflow_steps (assessment_id, 1, 'intersect', params)
│
├── project_XXX.sqlite:
│   ├── Tabla buildings (migrada con geometria)
│   ├── Tabla CityPlan__Flood_intersect (resultado)
│   ├── Tabla CityPlan__Flood_union (resultado)
│   ├── INSERT base_layers_registry (buildings, POLYGON, 4326, source)
│   └── INSERT assessment_results_metadata (uuid, output, operation)
│
└── QGIS:
    ├── Layer CityPlan__Flood_intersect (spatialite provider)
    └── Layer CityPlan__Flood_union (spatialite provider)
```

### Verificacion Fase 5

- [ ] Wizard crea assessment con UUID en admin.sqlite
- [ ] Capas se migran a SpatiaLite (no PostgreSQL)
- [ ] Resultados se registran en ambas DBs
- [ ] Layers de salida se cargan en QGIS como spatialite
- [ ] TreeView se actualiza automaticamente al cerrar wizard
- [ ] Credenciales PostgreSQL hardcoded ya no se usan
- [ ] `database_manager.py` y `spatial_analysis.py` se eliminan

---

## FASE 6 — Limpieza y eliminacion de legacy

### Archivos a eliminar

| Archivo | Razon |
|---|---|
| `metadata_manager.py` | Reemplazado por `admin_manager.py` |
| `metadata.db` | Migrado a `admin.sqlite` (con script de migracion) |
| `database_manager.py` | Reemplazado por `project_manager.py` |
| `spatial_analysis.py` | Reemplazado por `spatial_analysis_sketlite.py` |

### Imports a actualizar

| Archivo | Import viejo | Import nuevo |
|---|---|---|
| `main_form.py` | `from .metadata_manager import MetadataManager` | `from .admin_manager import AdminManager` |
| `assessment_wizard_dialog.py` | `from .database_manager import DatabaseManager` | `from .project_manager import ProjectManager` |
| `assessment_wizard_dialog.py` | `from .spatial_analysis import SpatialAnalyzer` | `from .spatial_analysis_sketlite import SpatialAnalyzerLite` |
| `assessment_wizard.py` | (sin cambios directos) | Pasa `plugin_dir` como antes |

### Verificacion Fase 6

- [ ] Plugin funciona sin PostgreSQL instalado
- [ ] No quedan imports a archivos eliminados
- [ ] No quedan credenciales hardcoded en el codigo
- [ ] `metadata.db` migrada o respaldada
- [ ] Tests pasan (si existen)

---

## Orden de implementacion

```
FASE 1 ─── admin_manager.py ──────────────────────── Base de todo
   │
FASE 2 ─── project_manager.py ────────────────────── Datos espaciales
   │
FASE 3 ─── spatial_analysis_sketlite.py ──────────── Motor de analisis
   │
FASE 4 ─── main_form.py (TreeView) ───────────────── UI conectada
   │
FASE 5 ─── assessment_wizard_dialog.py ───────────── Flujo completo
   │
FASE 6 ─── Limpieza legacy ───────────────────────── Produccion
```

Cada fase es **testeable de forma independiente** antes de avanzar a la siguiente.

---

## Resumen de archivos

| Archivo | Accion | Fase |
|---|---|---|
| `admin_manager.py` | CREAR | 1 |
| `project_manager.py` | CREAR | 2 |
| `spatial_analysis_sketlite.py` | CREAR | 3 |
| `main_form.py` | MODIFICAR | 4 |
| `assessment_wizard_dialog.py` | MODIFICAR | 5 |
| `assessment_wizard.py` | MODIFICAR (menor) | 5 |
| `metadata_manager.py` | ELIMINAR | 6 |
| `database_manager.py` | ELIMINAR | 6 |
| `spatial_analysis.py` | ELIMINAR | 6 |
