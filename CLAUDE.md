# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A QGIS Python plugin ("Assessment Wizard" / EMDS Project Explorer) for building spatial assessments: users create projects, migrate QGIS vector layers into a per-project SpatiaLite DB, run versioned overlay analyses (target layer × assessment layers), and apply MCDA weighted scoring. Scaffolded with QGIS Plugin Builder; the generated boilerplate (Makefile, pb_tool.cfg, Qt resources, `help/`, `scripts/`, `test/`, Qt `.ts` translations) has been removed.

## Running / developing

- There is no standalone build step. The repo *is* the installed plugin directory (it lives inside the QGIS4 profile's `python/plugins/`). Reload it inside QGIS (e.g. Plugin Reloader) after edits.
- Debugging: `.vscode/launch.json` attaches debugpy to QGIS on `127.0.0.1:5678` (QGIS must already be running a debugpy listener on that port).
- No Qt resource file: the toolbar icon is loaded from `icon.png` by path (`pyrcc5` does not exist for Qt 6).
- Tests: `tools/run_tests.sh` runs everything: unit tests, the architecture check, and, when a QGIS Python is found, the Qt6 enum scan plus the integration tests. Use `tools/run_tests.sh --unit` for the parts that need no QGIS.
  - Unit tests (`tests/unit/`, stdlib `unittest`, fakes in `tests/fakes.py`) run with plain `python3`, no QGIS. Single test: `python3 -m unittest tests.unit.test_use_cases.CatalogTest.test_update_weights_sum_rule` from the plugin root.
  - Integration tests (`tests/integration/qgis_*.py`) are scripts run by the QGIS 4 Python on a scratch copy of the plugin. They end with `os._exit()` after printing the result: normal interpreter teardown of Qt/QGIS objects intermittently segfaults (rc 134/139). On macOS, QGIS is auto-detected (override with `QGIS_APP`). Elsewhere, set `QGIS_PYTHON` to a QGIS-enabled interpreter.
  - `python3 tools/check_architecture.py` enforces the layer rules below. Run it (or the whole runner) before committing structural changes.
- Lint: `pylint --rcfile tools/pylintrc <files>`. `tools/plugin_upload.py` uploads a ZIP to plugins.qgis.org.
- Packaging: `git archive --format=zip --prefix=q_assessment_wizard/ HEAD -o q_assessment_wizard.zip` (`.gitattributes` keeps `tests/`, `tools/`, `.vscode/` and CLAUDE.md out of the ZIP).

## Architecture

Entry: `__init__.py:classFactory` → `plugin.py:QassessmentWizard`, which creates a persistent `QDockWidget` hosting `ui/main_panel/panel.py:AssessmentMainForm` (project/assessment tree + detail panels in `ui/panels/`). The toolbar action just toggles the dock. From the main panel, `ui/wizard/assessment_wizard_dialog.py:QassessmentWizardDialog` (a `QWizard` loaded at runtime from `ui/wizard/assessment_wizard_dialog_base.ui` via `uic.loadUiType`) runs the create-assessment flow, using `ui/wizard/map_tools.py` + `canvas_crs.py` for on-canvas feature selection and `assessment_summary.py` for the page-3 summary.

Folder layout (each folder is one layer; only `__init__.py`, `plugin.py`, `metadata.txt` and `icon.png` live in the root, as QGIS requires):

```
plugin.py                       QGIS entry + composition root: creates/connects AdminManager, builds ExplorerFacade, dock, Qt6 workaround
core/domain/models/             pure Python entities (Scenario, LayerRef, LayerRole)
core/domain/rules/              pure business rules: naming (__v{n}, sanitizing), complexity, coverage
core/application/ports/         Protocols the use cases depend on (metadata repo, spatial engine, map layers)
core/application/errors.py      OperationCancelled
core/application/use_cases/     one class per operation + commands.py (input DTOs)
core/infrastructure/persistence/ admin.sqlite access: AdminManager (connection) + one mixin module per
                                responsibility (schema, projects, assessments, analysis, provenance,
                                portfolios, legacy_import)
core/infrastructure/spatial/    SpatiaLite access: SpatialEngine, OperationRunner, result_queries, ProjectManager
                                (connection/schema) + project_db/ mixins (spatialite, layer_migrator, tables, versions)
core/infrastructure/qgis/       live QGIS project adapters (QgisMapLayers → MapLayersPort)
ui/                             explorer_facade.py (catalog/reads), assessment_executor.py (per-project analysis ops)
ui/main_panel/                  panel.py (dock content: layout, i18n, lifecycle) + tree_view / detail_views /
                                context_menu / catalog_actions / results_actions mixins
ui/wizard/                      assessment_wizard_dialog.py (lifecycle) + layer_table / page_configuration /
                                page_selection / page_summary mixins, map_tools, canvas_crs, layer_migration
ui/panels/  ui/dialogs/  ui/i18n/ (translator + translations/*.json)
tests/unit/  tests/integration/  unit tests with fakes (no QGIS) / QGIS 4 integration scripts
tools/                          run_tests.sh, check_architecture.py, check_qt6_enums.py, pylintrc, plugin_upload.py
```

Layered ("clean architecture") call path — keep this direction:

```
UI (ui/main_panel, ui/wizard, ui/panels, ui/dialogs)
  → ExplorerFacade (ui/explorer_facade.py) — projects/assessments/portfolios CRUD, weights, tree read model; raises, no dialogs
  → AssessmentExecutor (ui/assessment_executor.py) — per-project analysis ops; builds Command DTOs, owns their QMessageBox handling
    → Use cases (core/application/use_cases/*) — one class per operation, execute(cmd) → dict; raise ValueError/RuntimeError, never touch UI
      → Ports (core/application/ports/) — typing.Protocols
        → MetadataRepositoryPort  ← satisfied structurally by AdminManager (core/infrastructure/persistence/admin_manager.py)
        → SpatialEnginePort       ← core/infrastructure/spatial/SpatialEngine (context manager, opened per DB path)
              → SpatialRepository / OperationRunner → ProjectManager (core/infrastructure/spatial/project_manager.py)
```

- `core/domain/` must stay pure Python: no QGIS and no DB imports.
- Business rules live once, in `core/domain/rules/`; don't re-implement them inline. In particular, use `naming.version_of / strip_version / versioned_name` instead of `__v(\d+)` regexes, and `naming.sanitize_table_name` for SpatiaLite tables. `naming.sanitize_file_name` is a *different* rule for project DB files: existing `projects/*.sqlite` paths depend on it, so don't merge the two. Coverage thresholds/labels come from `rules/coverage.py`, and the results-grid SQL is built from them.
- Only `plugin.py` knows `AdminManager`. Widgets get an `ExplorerFacade` (the panel, tree, detail panels and weights editor) or an `AssessmentExecutor` (the wizard and its migration service). Never pass the repository into a widget. The only place in `ui/` allowed to import `core/infrastructure` is `assessment_executor.py`, which wires `SpatialEngine` and `QgisMapLayers` into the use cases.
- Use cases never import QGIS; anything they need from the live map goes through `MapLayersPort`. Writes take a Command dataclass. Reads (`explorer_queries.py`, `query_results.py`) take plain arguments and return dicts/lists (read models).
- Long operations stop by raising `OperationCancelled` from the progress callback. Adapters must re-raise it instead of recording it as an item error (see `ProjectManager.migrate_layers`).
- Large classes are split into **mixin modules by responsibility** (`AdminManager`, `ProjectManager`, the wizard, the main panel). The public API stays on the main class. Mixins share `self` state, define no `__init__`, and in the wizard and the main panel they must precede the Qt bases. A new tree action = a menu entry in `main_panel/context_menu.py` + a handler in `catalog_actions.py` or `results_actions.py`. Add new behaviour as a new mixin module instead of growing one past ~300 lines.
- Use cases receive `SpatialEngine` as a *factory* (`with self._engine_factory(db_path) as engine:`), not an instance.
- Command dataclasses (`use_cases/commands.py`) are the boundary where `QgsVectorLayer` objects are allowed in.
- Adding a new operation = new Command + use case, export it from `core/application/use_cases/__init__.py` and `core/application/__init__.py`, wire it in `AssessmentExecutor` or `ExplorerFacade`, and extend the port Protocol if the use case needs new repository/engine methods (AdminManager satisfies it by duck typing, so just add the method there).

## Data storage

Two-tier SQLite, both created in the plugin directory at runtime (gitignored):

- `admin.sqlite` — central metadata (`AdminManager`): projects, assessments, assessment layers/visibility, provenance + task tree, criteria, analyses/weights/results, app settings. Schema created and migrated in-place in `AdminManager._create_tables()` / `_migrate_schema()` / `_drop_unused_tables()` on every `connect()` — schema changes go there, idempotently.
- `projects/{name}.sqlite` — one SpatiaLite DB per project (`ProjectManager`): migrated base layers (`base_layers_registry`), output tracking, and `spatial_versions` (git-like immutable version chain with `parent_version_id` and an `is_current` HEAD flag; rollback moves HEAD, never mutates tables).
- Overlay output tables are named `{project}__{assessment}__v{n}`; the double-underscore separator is significant and preserved by `sanitize_table_name()`.
- Cross-DB links (`projects.db_path`, `assessments.uuid` ↔ `assessment_results_metadata.assessment_uuid`) are not enforced by FKs — application code keeps them consistent; deletes have soft (`is_deleted`) and purge variants.

- `portfolios` (admin.sqlite) stores Portfolio (LPA) configurations built on an overlay table. There is no solver, so rows stay `status='pending'`. They appear as `💼` nodes under the assessment.

## Results viewers (ported from the sibling `../plugin_wizard`)

- `ui/dialogs/`: `ResultsGridDialog` (filter/group/sort, chart, CSV/xlsx + PDF export), `CompareHistogramDialog` (paired "butterfly" histogram) and `PortfolioWizard`. They are launched from the tree context menu (`ui/main_panel/context_menu.py`, handlers in `results_actions.py`): `🔁 Analysis` nodes open the grid and the portfolio wizard, the project node opens the comparison.
- Dialogs never touch a DB. Data comes through `AssessmentExecutor.get_results_grid / get_result_columns / get_comparison_series / create_portfolio`, which call the use cases in `core/application/use_cases/query_results.py` and `create_portfolio.py`. Those reach the SQL in `core/infrastructure/spatial/result_queries.py` via `SpatialEngine.results_*`.
- The query use cases raise `LookupError` when a table isn't in SpatiaLite. Simple (memory) assessments hit this, and `main_panel` then falls back to the loaded QGIS layer's attributes.
- matplotlib must be imported from `matplotlib.backends.backend_qtagg` (the Qt5 backend fails on QGIS 4). openpyxl isn't bundled with QGIS 4.0.3, so Excel export writes CSV.
- The NetWeaver/CDP engines from plugin_wizard were deliberately **not** ported.

## i18n

- All user-facing text goes through `ui/i18n/translator.tr('section.key', **fmt)`, backed by `ui/i18n/translations/{en,es,pt,de}.json`. Keep the four files key-identical with the same `{placeholders}`. Missing keys render as the raw key; they don't crash.
- The language is picked in the panel's selector and persisted in QgsSettings `q_assessment_wizard/language`, falling back to the QGIS locale and then English. Widgets re-apply their texts in `retranslateUi()`, and `AssessmentMainForm.language_changed` updates the dock title and toolbar action. The plugin menu name is fixed at load time, because `unload()` must remove it under the same name.
- Wizard layer-status combos show translated labels but store the language-independent `STATUS_*` key as item data. Always read them with `_status_of(combo)` / `currentData()`, never `currentText()`, and set them with `_set_status()`.
- Messages raised by use cases (`ValueError` text in `core/`) are intentionally English: the core layer doesn't depend on the UI translator.

`docs/sql_schemas.md` is the detailed reference for full schemas, ER diagrams, and step-by-step flows (ApplyOverlay, CreateScenario, rollback, compare, project creation, metadata recording). Keep it updated when schemas change.

`docs/ROADMAP.md` (Spanish) lists proposed features with value/effort/priority. They are proposals awaiting the user's decision, so don't implement one unless asked. Update its status when one is done.

## Gotchas

- Target runtime is QGIS 4 (Qt 6 / PyQt6); `metadata.txt` declares `supportsQt6=True` and min 3.22 so it still runs on QGIS 3 (PyQt 5.15). To keep both working:
  - Import only from `qgis.PyQt.*`, never `PyQt5`/`PyQt6` directly.
  - Always use fully scoped Qt enums (`Qt.CheckState.Checked`, `Qt.ItemDataRole.UserRole`, `QMessageBox.StandardButton.Yes`, `QDialog.DialogCode.Accepted`). Short forms like `Qt.Checked` raise `AttributeError` on PyQt6.
  - Use `.exec()`, not `.exec_()`.
  - QGIS enums (`QgsWkbTypes.*`, `Qgis.GeometryType`) are `IntEnum`s in QGIS 4, so comparing them to ints still works.
- Dragging any dock widget in QGIS 4.0.3 (Qt 6.9.3) segfaults inside Qt (`QWidgetAnimator::animate`, null `QVariantAnimation`) while `QMainWindow` dock animations are on. This reproduces with a plain `QDockWidget`, so it is not plugin code. `QassessmentWizard.initGui` works around it by calling `iface.mainWindow().setAnimated(False)` on Qt 6, and `unload()` restores it. Setting a no-animation style only on the plugin's dock does *not* prevent it, because Qt animates every dock in the area.
- SpatiaLite loading (`ProjectManager._load_spatialite`): QGIS 4 macOS bundles ship `Contents/Frameworks/mod_spatialite.so`, and a bare `"mod_spatialite"` fails there (macOS looks for `.dylib`). Keep the explicit `"mod_spatialite.so"` attempt.
- Headless testing against QGIS 4 works with the bundled interpreter: `PYTHONHOME=/Applications/QGIS-final-4_0_3.app/Contents/Resources`, `PYTHONPATH` = that `Resources/python3.11` + its `lib-dynload` + `site-packages`, `QT_QPA_PLATFORM=offscreen`, then run `Contents/MacOS/python3.12`. `AdminManager` writes `admin.sqlite`/`projects/` into the plugin dir it's given, so test on a copy, and mock `iface`.
- Overlay semantics (`OperationRunner._build_cumulative_step_query`): only intersection fragments are stored as geometry, plus one `no_overlap` row for each feature with no positive-area intersection. Both branches share the `_OVERLAPS` condition, so every feature appears. The remainder is kept as an area instead: every row has `source_area` (area of the original target feature, carried through the cumulative steps), and `result_queries.py` computes `total_area = MAX(source_area)` and `intersect_area` = the union of the intersect fragments (`GUnion`, which needs SpatiaLite loaded on the connection). Tables written before 2026-11-26 lack `source_area` and fall back to the old sum formulas (0 %/100 %), so keep that fallback. `tests/integration/qgis_overlay_semantics.py` pins all of this. Overlay tables don't carry source-layer attributes.
- `RecoverGeometryColumn()` signals failure by returning 0, not by raising. Check its result.
- `__pycache__/`, `*.pyc` and `metadata.db*` are gitignored. A local `__pycache__/` may still hold stale `.pyc` files for modules that were deleted (e.g. `database_manager`); they are not live source.
- Some commit messages are in Spanish.
