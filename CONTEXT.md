# Assessment Wizard — Documento de Contexto

> Generado: 2026-03-07
> Plugin QGIS 3 — Python 3.9 / PyQt5 / SpatiaLite

---

## 1. Propósito del Plugin

**Assessment Wizard** es un plugin de QGIS que permite crear, ejecutar y versionar *assessments* (evaluaciones espaciales) sobre capas vectoriales. El flujo principal es:

1. El usuario agrupa capas base en un grupo QGIS llamado `Base Layers`.
2. Define un *assessment*: selecciona una capa **Target** y una o más capas de **evaluación**.
3. El plugin realiza un análisis espacial (intersección + unión) y guarda el resultado como tabla SpatiaLite versionada.
4. Los pesos MCDA se pueden ajustar para ponderar el área de cada capa en la puntuación final.
5. Cada re-ejecución crea una nueva versión inmutable (`v1`, `v2`, `v3`, …).

---

## 2. Arquitectura General (Clean Architecture)

```
UI Layer
  assessment_wizard_dialog.py   ← Wizard de 3 páginas (QWizard)
  main_form.py                  ← Panel dock principal (QDockWidget content)
  ui/panels/
    emds_tree_model.py          ← Árbol EMDS (Project → Base Layers | Assessments)
    assessment_detail_panel.py  ← Tarjeta de resumen del assessment
    analysis_detail_panel.py    ← Panel MCDA + WeightsEditDialog

Application Layer (Façade)
  assessment_executor.py        ← Traduce eventos UI → comandos de use case

Use Cases (core/application/use_cases/)
  commands.py                   ← DTOs: CreateScenarioCommand, ApplyOverlayCommand,
                                         RollbackVersionCommand, CompareVersionsCommand
  create_scenario.py            ← Assessment simple (solo features seleccionadas)
  apply_overlay.py              ← Overlay espacial versionado
  rollback_version.py           ← Restaurar versión anterior
  compare_versions.py           ← Cargar dos versiones para comparar

Infrastructure
  admin_manager.py              ← CRUD metadata (admin.sqlite)
  project_manager.py            ← Gestión SpatiaLite por proyecto
  layer_migration.py            ← Migración de capas QGIS → SpatiaLite
  core/spatial_engine/
    engine.py                   ← SpatialEngine (façade)
    repository.py               ← SpatialRepository (SQL directo)
    operations.py               ← OperationRunner, OverlayOperation
```

### Flujo de llamadas

```
UI → AssessmentExecutor → Use Case → SpatialEngine → SpatialRepository
                                   → AdminManager
```

---

## 3. Bases de Datos

### 3.1 `admin.sqlite` (metadata global)

Tablas activas:

| Tabla | Propósito |
|---|---|
| `projects` | Registro de proyectos (id, name, db_path) |
| `assessments` | Assessments por proyecto |
| `assessment_layers` | Capas input/output por assessment |
| `layer_visibility_state` | Estado de visibilidad persistido |
| `analyses` | Configuración MCDA (`name='Default'` mutable; `name='v{n}'` inmutable) |
| `analysis_weights` | Pesos por capa en cada configuración |
| `analysis_results` | Resultados MCDA registrados |
| `provenance` | Registro de ejecuciones (runs) |
| `task_details` | Pasos/operaciones de cada run |
| `app_settings` | Configuración global del plugin |
| `assessment_criteria` | Criterios de evaluación |

### 3.2 `projects/{project_name}.sqlite` (SpatiaLite por proyecto)

- Contiene las capas migradas y los resultados del overlay.
- Tabla `spatial_versions`: historial de versiones HEAD.
- Cada overlay genera una tabla `{project}__{assessment}__v{n}`.

---

## 4. Convenciones de Nombres

| Elemento | Patrón |
|---|---|
| Base name de overlay | `{project_name}__{assessment_name}` |
| Tabla versionada | `{project_name}__{assessment_name}__v{n}` |
| Separador | `__` (doble guion bajo) |
| Sanitización | `sanitize_table_name()` → `re.sub(r'_{3,}', '__', ...)` |
| Grupo QGIS assessment | `{seq:02d}_{assessment_name}` |
| Display name primer run | `OUTPUT_{assessment_name}` |
| Display name re-run | `Result_v{n}` |

---

## 5. Ciclo de Vida de un Assessment

### 5.1 Primera ejecución (`v1`)

```
QassessmentWizardDialog.accept()
  → AssessmentExecutor.execute_spatial_assessment()
      → ApplyOverlay.execute(ApplyOverlayCommand)
          → SpatialEngine.prepare_layer()     # migra capas a SpatiaLite
          → [merge multi-layer → _merged_{name}]
          → SpatialEngine.overlay()            # genera tabla __v1
              → OverlayOperation.INTERSECT
              → OverlayOperation.UNION
              → rename tmp → final table
              → spatial_versions INSERT (HEAD)
              → load QGIS layer
  → AssessmentExecutor.record_assessment()
      → AdminManager.create_assessment()
      → AdminManager.create_provenance()
      → AdminManager.add_task()
      → AdminManager.create_analysis_config()  # pesos iguales por defecto
      → AdminManager.snapshot_analysis_for_version()
```

### 5.2 Nueva versión (`v2`, `v3`, …)

```
AssessmentMainForm._on_new_version()
  → AssessmentExecutor.rerun_spatial_assessment()
      → SpatialEngine.overlay()  # genera __v{n+1}
  → AdminManager.add_assessment_layer()
  → AdminManager.snapshot_analysis_for_version()
```

### 5.3 MCDA Score

```
AnalysisDetailPanel._on_run_again()
  → AssessmentMainForm._on_run_mcda()
      → AssessmentExecutor.apply_mcda_score()
          → AdminManager.get_analysis_config()
          → UPDATE table SET MCDA_SCORE = weight * (ST_Area(geom) / SUM(ST_Area(geom)))
```

---

## 6. Archivos Clave

### Entrada del plugin

| Archivo | Rol |
|---|---|
| `__init__.py` | Entry point QGIS |
| `assessment_wizard.py` | Plugin class, crea el dock |
| `main_form.py` | Contenido del dock (panel principal) |
| `assessment_wizard_dialog.py` | Wizard de 3 páginas |

### Lógica de negocio

| Archivo | Rol |
|---|---|
| `admin_manager.py` | Todo el CRUD de metadata |
| `assessment_executor.py` | Façade UI → use cases |
| `core/application/use_cases/apply_overlay.py` | Overlay espacial |
| `core/application/use_cases/commands.py` | DTOs de comandos |
| `core/spatial_engine/engine.py` | SpatialEngine façade |
| `core/spatial_engine/repository.py` | SQL directo SpatiaLite |
| `core/spatial_engine/operations.py` | Operaciones de overlay |
| `layer_migration.py` | Migración QGIS → SpatiaLite |
| `project_manager.py` | Gestión conexión SpatiaLite |

### UI

| Archivo | Rol |
|---|---|
| `ui/panels/emds_tree_model.py` | Árbol Project Explorer |
| `ui/panels/analysis_detail_panel.py` | Panel MCDA + WeightsEditDialog |
| `ui/panels/assessment_detail_panel.py` | Tarjeta resumen assessment |
| `ui/panels/version_history_panel.py` | Historial de versiones |
| `map_tools.py` | FeatureSelectionTool, RectangleSelectTool |
| `geometry_utils.py` | transform_extent_to_canvas_crs, get_assessment_summary |

---

## 7. Árbol EMDS (UI)

```
📁 Project
  ├── 📁 Base Layers         (inmutable, solo lectura)
  │     ├── 🔴 Layer A
  │     └── 🟩 Layer B
  └── 🟢 📁 Assessment Name  (status: 🟢=ok, 🟡=sin output, 🔴=target no encontrado)
        ├── ⚙ Weights
        │     ├── LayerA: 50%
        │     └── LayerB: 50%
        ├── 🔁 Analysis v1   [checkbox visibilidad]
        └── 🔁 Analysis v2   [checkbox visibilidad]
```

**Roles de datos del árbol:**

| Constante | Qt Role | Contenido |
|---|---|---|
| `ROLE_ID` | UserRole | PK del nodo |
| `ROLE_TYPE` | UserRole+1 | `'project'`, `'assessment'`, `'analysis'`, `'weights'`, `'base_layers_group'` |
| `ROLE_OUTPUT_TABLES` | UserRole+2 | `list[str]` — tablas de salida |
| `ROLE_SCENARIO_NAME` | UserRole+3 | Base name sin `__v{n}` |
| `ROLE_NAME` | UserRole+4 | Nombre raw (sin display text) |

---

## 8. Wizard de 3 Páginas

**Página 1 — Configuración:**
- `lineEdit_name` — nombre del assessment (spaces → `_`)
- `tableWidget_layers` — capas del grupo "Base Layers"
- Cada capa tiene un combo: `Do not include` / `Include in assessment` / `Include as Target` / `Spatial Marker`
- Solo una capa puede ser Target
- Al salir del campo nombre, detecta duplicados y ofrece crear `v2+`

**Página 2 — Selección de features:**
- Mapa interactivo con OSM como basemap
- Tools: Zoom In/Out, Pan, Rectangle Select, Feature Click Select
- Validación: ≥1 feature seleccionada

**Página 3 — Resumen:**
- Tabla resumen de capas, mapa de features seleccionadas
- Al aceptar → ejecuta el assessment

---

## 9. MCDA (Multi-Criteria Decision Analysis)

- Los pesos se guardan en `analyses` (tabla admin.sqlite) como JSON: `{"LayerA": 0.5, "LayerB": 0.5}`.
- `Default` = pesos actuales mutables; `v{n}` = snapshot inmutable por versión.
- Fórmula de puntuación aplicada por `apply_mcda_score()`:

  ```sql
  MCDA_SCORE = weight * (ST_Area(geom) / SUM(ST_Area(geom)))
  ```

- `WeightsEditDialog` valida que los pesos sumen exactamente 100%.
- `AnalysisDetailPanel.load()` prefiere el snapshot de la versión; si no existe, usa `Default`.

---

## 10. Versioning Espacial

- Cada `engine.overlay()` crea una nueva tabla `{base}__v{n}` — **nunca sobreescribe**.
- `spatial_versions` registra el historial con puntero `is_current` (HEAD).
- Rollback = mover el puntero `is_current` → O(1), sin recalculo espacial.
- `get_versions(base_name)` retorna versiones ordenadas de más reciente a más antigua.

---

## 11. Patrones y Reglas Importantes

### Sanitización de nombres
```python
sanitize_table_name(name):
    # spaces → _  |  non-alphanumeric → _  |  3+ underscores → __
    re.sub(r'_{3,}', '__', ...)
```
Esto preserva el separador `__` del patrón de nombres.

### Acceso a la conexión SpatiaLite
```python
engine._repo.project_manager.connection  # CORRECTO
engine._repo._conn                        # INCORRECTO (privado)
```

### SpatiaLite — Geometría
```python
ST_Area(geom)      # CORRECTO
ST_Area(geometry)  # INCORRECTO
```

### Registro de geometría tras CREATE TABLE AS
```python
cursor.execute(
    f"SELECT RecoverGeometryColumn('{table}', 'geom', {srid}, 'MULTIPOLYGON', 'XY')"
)
```

### Multi-layer merge
Cuando hay más de una capa de evaluación, se fusionan en una tabla temporal antes del overlay:
```python
merged_temp = sanitize_name(f"_merged_{assessment_name}")
union_sql = " UNION ALL ".join(f"SELECT geom FROM {t}" for t in assessment_tables)
```
Esto garantiza un único output por assessment (no uno por capa).

### showEvent en main_form
`showEvent` siempre llama `_populate_tree()`. Primero reconecta si `connection is None`.

---

## 12. Dependencias Externas

- **QGIS 3** + **PyQt5** — UI y acceso a capas
- **SpatiaLite** — almacenamiento espacial por proyecto
- **SQLite** — `admin.sqlite` (metadata)
- Python stdlib: `sqlite3`, `json`, `re`, `os`, `uuid`

---

## 13. Tests

Ubicados en `test/`:
- `test_init.py` — carga del plugin
- `test_qgis_environment.py` — entorno QGIS
- `test_translations.py` — traducciones i18n
- `test_assessment_wizard_dialog.py` — diálogo wizard
- `test_resources.py` — recursos Qt

Los tests requieren un entorno QGIS completo (no se ejecutan fuera de QGIS).

---

## 14. Estado Actual del Proyecto (2026-03-07)

- Clean Architecture **completada** con capa de Ports (2026-03-07).
- MCDA con pesos configurables y snapshots por versión.
- Versioning inmutable con rollback O(1).
- Árbol EMDS completamente funcional con persistencia de estado.

### Ports (`core/application/ports/`)
- `MetadataRepositoryPort` — Protocol que abstrae `AdminManager`
- `SpatialEnginePort` — Protocol que abstrae `SpatialEngine`
- `AdminManager` satisface `MetadataRepositoryPort` via structural typing (sin cambios al AdminManager)

### Use cases completos
| Use case | Archivo |
|---|---|
| `CreateScenario` | create_scenario.py |
| `ApplyOverlay` | apply_overlay.py (usa `Scenario` domain model) |
| `RollbackVersion` | rollback_version.py |
| `CompareVersions` | compare_versions.py |
| `RerunSpatialAssessment` | rerun_spatial_assessment.py |
| `ApplyMcdaScore` | apply_mcda_score.py |
| `RecordAssessment` | record_assessment.py (unifica first-run y re-run) |

### `SpatialEngine` — métodos públicos añadidos (2026-03-07)
- `merge_layers(tables, merged_name) -> str`
- `sanitize_name(raw) -> str`
- `drop_table(name)`

### `AssessmentExecutor` — thin façade
- Constructor instancia todos los use cases con DI
- Métodos: build Command → call use case → QMessageBox
- Sin lógica de negocio residual
