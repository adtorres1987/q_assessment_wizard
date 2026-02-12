# QGIS Assessment Framework Plugin

Plugin de QGIS para crear **proyectos GIS reproducibles y auditables**, basados en:
- Base Layers controlados
- Assessments estructurados
- Provenance (trazabilidad)
- Work Steps (ejecución)

Arquitectura pensada para escalar de **desktop (SpatiaLite)** a **web (PostGIS)**.

---

## 1. Objetivo del Plugin

Este plugin permite:

- Crear **Projects** como unidades raíz
- Registrar **Base Layers** de forma controlada
- Ejecutar **Assessments** espaciales (union / intersection)
- Guardar **Provenance** y **Work Steps**
- Garantizar reproducibilidad y trazabilidad de resultados

---

## 2. Conceptos Clave

### 2.1 Modelo Conceptual

Project
└── Assessment(s)
└── Provenance(s)
└── Work Step(s)

### 2.2 Definiciones

- **Project**: Contenedor lógico y físico (1 Project = 1 DB)
- **Base Layer**: Capa de entrada registrada y versionada
- **Assessment**: Intención de análisis
- **Provenance**: Contexto congelado del análisis
- **Work Step**: Ejecución técnica del análisis

---

## 3. Arquitectura General

### 3.1 Principios

- QGIS es solo visualización
- La verdad vive en SQLite
- Ningún análisis se ejecuta sin Provenance
- Ninguna capa se usa sin estar registrada

---

## 4. Estructura de Carpetas (Plugin)

my_gis_plugin/
│
├── plugin.py
├── metadata.txt
├── init.py
│
├── core/
│ ├── project/
│ ├── base_layers/
│ ├── assessment/
│ ├── provenance/
│ ├── work_steps/
│ └── database/
│
├── ui/
│ ├── dialogs/
│ └── dock/
│
├── resources/
│
└── utils/

---

## 5. Estructura de Carpetas (Project en Disco)

/Projects/
└── Project_Name/
├── project.sqlite
├── input/
├── output/
├── logs/
└── cache/

---

## 6. Base de Datos (SQLite / SpatiaLite)

### 6.1 project.sqlite

Contiene solo **metadata y control**, no geometrías pesadas.

#### Tablas principales:

- project
- base_layer
- assessment
- provenance
- work_step
- layer_registry

---

## 7. Paso 1 — Project

### 7.1 Responsabilidad

- Crear carpeta del proyecto
- Inicializar `project.sqlite`
- Registrar metadata básica

### 7.2 Reglas

- Un solo Project por DB
- No se edita, se crea uno nuevo

---

## 8. Paso 2 — Base Layers

### 8.1 Flujo

1. Usuario selecciona capas desde QGIS
2. Plugin copia archivos a `/input`
3. Se registra metadata en DB
4. TreeView se actualiza

### 8.2 Restricciones

- Solo capas registradas pueden usarse
- No se usan rutas externas

---

## 9. Paso 3 — Assessment & Provenance

### 9.1 Assessment

Define:
- nombre
- descripción
- tipo de análisis esperado

### 9.2 Provenance

Congela:
- target layer
- assessment layers
- CRS
- extensión
- timestamp

> Cada ejecución = nuevo provenance

---

## 10. Paso 4 — Work Steps

### 10.1 Qué registra

- operación (union / intersect)
- engine (spatialite / postgis)
- SQL ejecutado
- tiempos
- estado

---

## 11. TreeView (UI)

### 11.1 Estructura

Project
├── Base Layers
└── Assessments
└── Assessment Name
└── Provenance

### 11.2 Función

- Navegación
- Contexto activo
- Activar / desactivar capas

---

## 12. Flujo General del Usuario

1. Crear Project
2. Registrar Base Layers
3. Crear Assessment
4. Generar Provenance
5. Ejecutar Work Steps
6. Visualizar resultados

---

## 13. Roadmap Técnico

- [ ] Paso 1: Project
- [ ] Paso 2: Base Layers
- [ ] Paso 3: Provenance
- [ ] Paso 4: Work Steps
- [ ] UI Dock principal
- [ ] Migración PostGIS

---

## 14. Principios No Negociables

- No análisis sin provenance
- No capas sin registro
- No sobrescritura silenciosa
- Metadata primero, geometría después

---

## 15. Frase Guía del Proyecto

> “Si no puedo reproducirlo, no es GIS profesional.”
