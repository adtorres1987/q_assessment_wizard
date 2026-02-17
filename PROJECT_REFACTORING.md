# Refactorización del proyecto `q_assessment_wizard`

Este documento describe **cómo adaptar y refactorizar progresivamente** el repositorio existente `q_assessment_wizard` hacia un **motor espacial robusto, versionado y consistente**, usando **Python + QGIS + Spatialite**, sin que el proyecto se salga de control.

El enfoque es **iterativo por fases**, con **Clean Architecture**, control de riesgos y compatibilidad gradual con el código actual.

---

## 1. Objetivo de la refactorización

Transformar el plugin desde:

* lógica acoplada a UI
* operaciones espaciales ad‑hoc
* estados implícitos

hacia:

* un **motor espacial centralizado**
* **escenarios versionados** (tipo Git)
* **reproducibilidad** de resultados
* separación clara de responsabilidades

---

## 2. Principios arquitectónicos que se aplican

### 2.1 Clean Architecture (adaptada a QGIS)

Capas:

1. **UI (QGIS / Qt)**
2. **Application / Use Cases**
3. **Domain (modelo puro)**
4. **Infrastructure (Spatialite, QGIS API)**

Regla clave:

> Las capas internas **no conocen** a las externas.

---

### 2.2 Motor espacial como fuente de verdad

* Ninguna operación espacial vive en la UI
* Todo pasa por un **Spatial Engine**
* Spatialite es el backend determinista

---

### 2.3 Versionado de escenarios (mentalidad Git)

Conceptos:

* *Scenario* = branch
* *Version* = commit
* *Pointer* = HEAD

Nunca se sobrescriben resultados.

---

## 3. Problemas actuales del repositorio (diagnóstico)

Del análisis del repo `q_assessment_wizard`:

* UI controla flujo y lógica
* Operaciones espaciales acopladas
* No hay versionado explícito
* Tablas temporales sin trazabilidad
* No existe rollback real

⚠️ Refactorizar todo de golpe sería riesgoso.

---

## 4. Estrategia general de refactorización

### Regla de oro

> **Primero encapsular, luego refactorizar, después rediseñar.**

Cada fase deja el sistema **funcional**.

---

## 5. FASE 1 – Encapsulación sin cambiar comportamiento

### Objetivo

Crear un **núcleo mínimo** sin romper nada.

---

### 5.1 Crear módulo `spatial_engine`

Nueva carpeta (sin tocar UI):

```
core/
  spatial_engine/
    engine.py
    repository.py
    operations.py
```

---

### 5.2 Engine mínimo

Responsabilidad:

* recibir capas
* copiarlas a Spatialite
* ejecutar SQL espacial

Nada de UI.

---

### 5.3 Repository (infraestructura)

Encapsula:

* conexión SQLite/Spatialite
* creación de tablas
* copias completas de capas

---

### Resultado Fase 1

✔️ Código sigue funcionando
✔️ UI ya no ejecuta SQL
✔️ Base para evolucionar

---

## 6. FASE 2 – Modelo de dominio explícito

### Objetivo

Dejar de pasar `QgsVectorLayer` por todo el sistema.

---

### 6.1 Entidades de dominio

```
domain/
  models/
    project.py
    scenario.py
    layer_role.py
    spatial_version.py
```

Ejemplos:

* `Scenario`
* `SpatialVersion`
* `LayerRole (TARGET | ASSESSMENT | MARKER)`

---

### 6.2 Reglas claras

* El dominio **no sabe** qué es QGIS
* Solo maneja IDs, nombres y estados

---

### Resultado Fase 2

✔️ Flujo entendible
✔️ Estados explícitos
✔️ Código testeable

---

## 7. FASE 3 – Versionado real de overlays

### Objetivo

Nunca perder consistencia al crear `overlay_<assessment>`

---

### 7.1 Tablas versionadas

En Spatialite:

```
spatial_versions
- id
- scenario_id
- created_at
- parent_version_id
- description
```

```
overlay_results
- version_id
- geom
- attributes...
```

---

### 7.2 Regla crítica

> Cada overlay pertenece a **una versión inmutable**

---

### 7.3 Volver atrás = mover puntero

No se recalcula nada.

```
HEAD -> version_id
```

✔️ Tu respuesta previa fue correcta: *solo mover el puntero*.

---

## 8. FASE 4 – Use Cases (Application Layer)

### Objetivo

Eliminar lógica procedural dispersa.

---

### 8.1 Casos de uso

```
application/
  use_cases/
    create_scenario.py
    apply_overlay.py
    rollback_version.py
    compare_versions.py
```

Cada uno:

* recibe comandos
* valida reglas
* llama al engine

---

### Resultado Fase 4

✔️ Flujo claro
✔️ Fácil mantenimiento
✔️ Lógica centralizada

---

## 9. FASE 5 – UI conceptual tipo Git

### Objetivo

Que el usuario *entienda* el estado del sistema.

---

### 9.1 Conceptos visibles

* Lista de escenarios
* Timeline de versiones
* HEAD activo
* Comparación visual

---

### 9.2 UI como cliente

La UI:

* no calcula
* no versiona
* solo ejecuta comandos

---

## 10. Consistencia y Spatialite

### Pregunta clave

> ¿Se pierde consistencia al crear `overlay_<assessment>`?

### Respuesta

❌ Sí, **si se hace desde capas temporales sin versionado**.

✔️ No, **si se crean desde tablas versionadas en Spatialite**.

La solución implementada en este plan **elimina ese riesgo**.

---

## 11. Control de riesgo del proyecto

* Fases cortas
* Código funcional siempre
* Refactor incremental
* Sin reescrituras masivas

---

## 12. Estado final esperado

Al finalizar:

* Motor espacial desacoplado
* Versionado reproducible
* Rollback O(1)
* UI simple
* Proyecto escalable

---

## 13. Siguiente paso recomendado

👉 Implementar **FASE 1** únicamente.

Cuando esté estable:

* avanzamos a FASE 2
* revisamos el repo real línea por línea

Si quieres, en el próximo mensaje puedo:

* mapear archivos actuales → nuevas capas
* o escribir el `SpatialEngine` inicial en código
