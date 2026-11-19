# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A QGIS Python plugin ("Assessment Wizard" / EMDS Project Explorer) for building spatial assessments: users create projects, migrate QGIS vector layers into a per-project SpatiaLite DB, run versioned overlay analyses (target layer × assessment layers), and apply MCDA weighted scoring. Scaffolded with QGIS Plugin Builder; most build tooling (Makefile, pb_tool.cfg, `scripts/`, `test/`) is the unmodified generated boilerplate.

## Running / developing

- There is no standalone build step. The repo *is* the installed plugin directory (it lives inside the QGIS4 profile's `python/plugins/`). Reload it inside QGIS (e.g. Plugin Reloader) after edits.
- Debugging: `.vscode/launch.json` attaches debugpy to QGIS on `127.0.0.1:5678` (QGIS must already be running a debugpy listener on that port).
- `resources.py` is compiled from `resources.qrc` (`make compile` → `pyrcc5`). Only regenerate if `resources.qrc`/`icon.png` changes.
- Tests: `make test` runs `nosetests` with `PYTHONPATH` set to the repo, and needs `qgis.core` importable (source `scripts/run-env-linux.sh <qgis prefix>` first). Single test: `PYTHONPATH=. python -m pytest test/test_init.py` (or `nosetests test/test_init.py`). The tests in `test/` are only Plugin Builder boilerplate and do not cover the domain/use-case code.
- Lint: `make pylint` (uses `pylintrc`), `make pep8`.
- Makefile / pb_tool.cfg file lists (`PY_FILES`, `python_files`) are stale — they only list the original 3 files, so `make deploy`/`pb_tool deploy`/`make zip` would ship a broken plugin. Update them before packaging.

## Architecture

Entry: `__init__.py:classFactory` → `assessment_wizard.py:QassessmentWizard`, which creates a persistent `QDockWidget` hosting `main_form.py:AssessmentMainForm` (project/assessment tree + detail panels in `ui/panels/`). The toolbar action just toggles the dock. From the main form, `assessment_wizard_dialog.py:QassessmentWizardDialog` (a `QWizard` loaded at runtime from `assessment_wizard_dialog_base.ui` via `uic.loadUiType`) runs the create-assessment flow, using `map_tools.py`/`geometry_utils.py` for on-canvas feature selection.

Layered ("clean architecture") call path — keep this direction:

```
UI (main_form, wizard dialog, ui/panels)
  → AssessmentExecutor (assessment_executor.py) — thin facade; builds Command DTOs, owns all QMessageBox handling
    → Use cases (core/application/use_cases/*) — one class per operation, execute(cmd) → dict; raise ValueError/RuntimeError, never touch UI
      → Ports (core/application/ports/) — typing.Protocols
        → MetadataRepositoryPort  ← satisfied structurally by AdminManager (admin_manager.py)
        → SpatialEnginePort       ← core/infrastructure/spatial/SpatialEngine (context manager, opened per DB path)
              → SpatialRepository / OperationRunner → ProjectManager (project_manager.py)
```

- `core/domain/` must stay pure Python: no QGIS and no DB imports.
- Use cases receive `SpatialEngine` as a *factory* (`with self._engine_factory(db_path) as engine:`), not an instance.
- Command dataclasses (`use_cases/commands.py`) are the boundary where `QgsVectorLayer` objects are allowed in.
- Adding a new operation = new Command + use case, export it from `core/application/__init__.py`, wire it in `AssessmentExecutor`, and extend the port Protocol if the use case needs new repository/engine methods (AdminManager satisfies it by duck typing, so just add the method there).

## Data storage

Two-tier SQLite, both created in the plugin directory at runtime (gitignored):

- `admin.sqlite` — central metadata (`AdminManager`): projects, assessments, assessment layers/visibility, provenance + task tree, criteria, analyses/weights/results, app settings. Schema created and migrated in-place in `AdminManager._create_tables()` / `_migrate_schema()` / `_drop_unused_tables()` on every `connect()` — schema changes go there, idempotently.
- `projects/{name}.sqlite` — one SpatiaLite DB per project (`ProjectManager`): migrated base layers (`base_layers_registry`), output tracking, and `spatial_versions` (git-like immutable version chain with `parent_version_id` and an `is_current` HEAD flag; rollback moves HEAD, never mutates tables).
- Overlay output tables are named `{project}__{assessment}__v{n}`; the double-underscore separator is significant and preserved by `sanitize_table_name()`.
- Cross-DB links (`projects.db_path`, `assessments.uuid` ↔ `assessment_results_metadata.assessment_uuid`) are not enforced by FKs — application code keeps them consistent; deletes have soft (`is_deleted`) and purge variants.

- `portfolios` (admin.sqlite) stores Portfolio (LPA) configurations built on an overlay table. There is no solver, so rows stay `status='pending'`. They appear as `💼` nodes under the assessment.

## Results viewers (ported from the sibling `../plugin_wizard`)

- `ui/dialogs/`: `ResultsGridDialog` (filter/group/sort, chart, CSV/xlsx + PDF export), `CompareHistogramDialog` (paired "butterfly" histogram) and `PortfolioWizard`. They are launched from the tree context menu in `main_form.py`: `🔁 Analysis` nodes open the grid and the portfolio wizard, the project node opens the comparison.
- Dialogs never touch a DB. Data comes through `AssessmentExecutor.get_results_grid / get_result_columns / get_comparison_series / create_portfolio`, which call the use cases in `core/application/use_cases/query_results.py` and `create_portfolio.py`. Those reach the SQL in `core/infrastructure/spatial/result_queries.py` via `SpatialEngine.results_*`.
- The query use cases raise `LookupError` when a table isn't in SpatiaLite. Simple (memory) assessments hit this, and `main_form` then falls back to the loaded QGIS layer's attributes.
- matplotlib must be imported from `matplotlib.backends.backend_qtagg` (the Qt5 backend fails on QGIS 4). openpyxl isn't bundled with QGIS 4.0.3, so Excel export writes CSV.
- The NetWeaver/CDP engines from plugin_wizard were deliberately **not** ported.

## i18n

- All user-facing text goes through `translator.tr('section.key', **fmt)`, backed by `translations/{en,es,pt,de}.json`. Keep the four files key-identical with the same `{placeholders}`. Missing keys render as the raw key; they don't crash.
- The language is picked in the panel's selector and persisted in QgsSettings `q_assessment_wizard/language`, falling back to the QGIS locale and then English. Widgets re-apply their texts in `retranslateUi()`, and `AssessmentMainForm.language_changed` updates the dock title and toolbar action. The plugin menu name is fixed at load time, because `unload()` must remove it under the same name.
- Wizard layer-status combos show translated labels but store the language-independent `STATUS_*` key as item data. Always read them with `_status_of(combo)` / `currentData()`, never `currentText()`, and set them with `_set_status()`.
- Messages raised by use cases (`ValueError` text in `core/`) are intentionally English: the core layer doesn't depend on the UI translator.

`docs/sql_schemas.md` is the detailed reference for full schemas, ER diagrams, and step-by-step flows (ApplyOverlay, CreateScenario, rollback, compare, project creation, metadata recording). Keep it updated when schemas change.

## Gotchas

- Target runtime is QGIS 4 (Qt 6 / PyQt6); `metadata.txt` declares `supportsQt6=True` and min 3.22 so it still runs on QGIS 3 (PyQt 5.15). To keep both working:
  - Import only from `qgis.PyQt.*`, never `PyQt5`/`PyQt6` directly.
  - Always use fully scoped Qt enums (`Qt.CheckState.Checked`, `Qt.ItemDataRole.UserRole`, `QMessageBox.StandardButton.Yes`, `QDialog.DialogCode.Accepted`). Short forms like `Qt.Checked` raise `AttributeError` on PyQt6.
  - Use `.exec()`, not `.exec_()`.
  - QGIS enums (`QgsWkbTypes.*`, `Qgis.GeometryType`) are `IntEnum`s in QGIS 4, so comparing them to ints still works.
- Dragging any dock widget in QGIS 4.0.3 (Qt 6.9.3) segfaults inside Qt (`QWidgetAnimator::animate`, null `QVariantAnimation`) while `QMainWindow` dock animations are on. This reproduces with a plain `QDockWidget`, so it is not plugin code. `QassessmentWizard.initGui` works around it by calling `iface.mainWindow().setAnimated(False)` on Qt 6, and `unload()` restores it. Setting a no-animation style only on the plugin's dock does *not* prevent it, because Qt animates every dock in the area.
- SpatiaLite loading (`ProjectManager._load_spatialite`): QGIS 4 macOS bundles ship `Contents/Frameworks/mod_spatialite.so`, and a bare `"mod_spatialite"` fails there (macOS looks for `.dylib`). Keep the explicit `"mod_spatialite.so"` attempt.
- Headless testing against QGIS 4 works with the bundled interpreter: `PYTHONHOME=/Applications/QGIS-final-4_0_3.app/Contents/Resources`, `PYTHONPATH` = that `Resources/python3.11` + its `lib-dynload` + `site-packages`, `QT_QPA_PLATFORM=offscreen`, then run `Contents/MacOS/python3.12`. `AdminManager` writes `admin.sqlite`/`projects/` into the plugin dir it's given, so test on a copy. `test/qgis_interface.py` is QGIS 2-era (imports `QgsMapLayerRegistry`) and doesn't work; mock `iface` instead.
- Overlay semantics (`OperationRunner._build_cumulative_step_query`): a target feature that touches the assessment layer keeps **only** its intersection fragments. Only features that don't touch it at all get a `no_overlap` row. So per-feature `coverage_pct` is always 100 % or 0 %. This diverges from the original design (which kept the `ST_Difference` remainder; see the note in `docs/sql_schemas.md`). Overlay tables also don't carry source-layer attributes.
- `RecoverGeometryColumn()` signals failure by returning 0, not by raising. Check its result.
- `__pycache__/` directories are tracked in git (including stale `.pyc` for deleted modules like `database_manager`); don't treat those as live source.
- Some commit messages are in Spanish.
