# Assessment Wizard

A QGIS plugin for building structured spatial assessments. You organise work into
**projects**, run a step-by-step **wizard** that overlays a target layer with one or
more assessment layers, keep every run as an immutable **version**, score results
with **MCDA** weights, and inspect them in a **results grid**, a **comparison
histogram** and a **portfolio** configuration wizard.

All data is stored in SQLite/SpatiaLite next to the plugin, so no database server
is required.

## Requirements

- **QGIS 4.x** (Qt 6), the primary target, tested with QGIS 4.0.3 on macOS.
  QGIS 3.22 or newer (Qt 5.15) is also supported by the code.
- SpatiaLite (`mod_spatialite`), which ships with the QGIS installers.
- Optional:
  - `matplotlib` for the charts. It is bundled with QGIS.
  - `openpyxl` for `.xlsx` export. Without it, the results grid exports CSV.
    QGIS 4.0.3 does not bundle it.

## Installation

1. Get the code, either by cloning the repository or by downloading it:

   ```bash
   git clone https://github.com/adtorres1987/q_assessment_wizard.git
   ```

2. Put the `q_assessment_wizard` folder in your QGIS profile's plugins directory:

   | OS | Plugins directory |
   |---|---|
   | macOS | `~/Library/Application Support/QGIS/QGIS4/profiles/default/python/plugins` |
   | Windows | `%APPDATA%\QGIS\QGIS4\profiles\default\python\plugins` |
   | Linux | `~/.local/share/QGIS/QGIS4/profiles/default/python/plugins` |

   For QGIS 3, use `QGIS3` instead of `QGIS4` in the path.

3. Restart QGIS, open **Plugins → Manage and Install Plugins → Installed** and enable
   **Assessment Wizard**.

To install from a ZIP instead, create one from the repository and use
**Plugins → Manage and Install Plugins → Install from ZIP**:

```bash
git archive --format=zip --prefix=q_assessment_wizard/ HEAD -o q_assessment_wizard.zip
```

## Usage

Click the **EMDS Explorer** toolbar button to show the **EMDS – Project Explorer**
panel. It is a dock widget, so you can move it to any side of the QGIS window.

### 1. Prepare the QGIS project

Put the input layers in a layer-tree group named exactly **`Base Layers`**. The
wizard only lists vector layers from that group. Make sure every layer has the
correct CRS assigned.

### 2. Create a project and an assessment

1. **🗂 New Project** creates a project, each with its own SpatiaLite database.
2. Select the project and click **+ New Assessment** to open the wizard:
   - **Page 1, configuration.** Set a name and description, then choose a status
     for each layer:
     - *Include as Target*: exactly one layer.
     - *Include in assessment*: the layers to overlay with the target.
     - *Spatial Marker* or *Do not include*.

     The target and assessment layers must have the same geometry type.
   - **Page 2, feature selection.** Select the target features to assess on the
     map (click, rectangle select, or select all). An OpenStreetMap basemap is
     shown when the layer's CRS can be reprojected to Web Mercator.
   - **Page 3, summary.** Review and finish. The layers are migrated to SpatiaLite
     and the overlay runs.

If there are no assessment layers, the wizard creates a *simple* assessment, which
is a memory layer of the selected features.

### 3. Work with the results

Each assessment shows its ⚙ weights and one **🔁 Analysis vN** node per version.
The output layers are added under the **Output Layers** group.

| Action | How |
|---|---|
| New version (re-run the overlay with the same layers) | Select the assessment, then **▶ Run Analysis** |
| Edit MCDA weights (they must sum to 100 %) | Right-click **⚙ Weights**, then **Edit Weights…** |
| Apply the MCDA score to a version | Select an analysis node, then **▶ Run Again** |
| Show or hide an output layer | The analysis node's checkbox |
| **Results grid** | Right-click an analysis, then **📋 View Results Grid…** |
| **Compare versions/assessments** | **📊 Compare Outputs**, or right-click the project |
| **Portfolio configuration** | Right-click an analysis, then **💼 Portfolio Wizard…** |
| Delete a project, assessment or portfolio | Right-click the node |

- **Results grid.** One row per target feature, with fragments, total area,
  intersected area, non-overlapping area, coverage % and coverage class, plus
  `mcda_score` once MCDA has been applied. You can filter, group and sort the rows,
  chart any column, and export to Excel/CSV or PDF (grid, chart or both). For
  simple assessments the grid shows the layer's attributes instead.
- **Compare outputs.** A paired ("butterfly") histogram of a chosen field, for two
  or more analysis results of the project. Bins can be equal range or equal
  distribution.
- **Portfolio wizard.** Maps the Benefits, Cost and Prioritization variables to
  result columns, sets a budget and optional budget buckets (A/B/C), and saves the
  configuration as a **💼** node.

### Language

The panel has a language selector: **English, Español, Português, Deutsch**. The
choice is remembered between sessions. Without a choice, the QGIS interface
language is used.

## Data storage

The plugin creates its data inside its own folder (excluded from git):

- `admin.sqlite` holds the metadata: projects, assessments, layers, provenance,
  MCDA weights and portfolios.
- `projects/<project>.sqlite` is one SpatiaLite database per project, with the
  migrated layers and every overlay output, named
  `<project>__<assessment>__v<n>`.

Versions are immutable. The engine supports rollback and version comparison by
moving a "current" pointer, but the panel has no button for them yet.
[`docs/sql_schemas.md`](docs/sql_schemas.md) documents the schemas and the
processing flows.

## Known limitations

- **Coverage per feature is all-or-nothing.** In an overlay, a target feature that
  touches an assessment layer keeps only its intersecting part. As a result, its
  coverage % is either 100 % or 0 %. See the note in `docs/sql_schemas.md`.
- **Overlay outputs do not keep the source layers' attributes.** The portfolio
  wizard can therefore only map the geometry-derived columns (`shape_area`,
  `shape_length`, `MCDA_SCORE`, …).
- **No portfolio optimisation.** Portfolios are saved with status *pending*.
- **Dock animations are turned off while the plugin is loaded.** QGIS 4.0.3
  (Qt 6.9) can crash when a dock panel is dragged with animations on. The setting
  is restored when the plugin is unloaded.
- **Layers without a valid CRS** are drawn in their own CRS, without the
  OpenStreetMap basemap.

## Development

- The plugin folder is the working copy. Reload the plugin after editing, for
  example with *Plugin Reloader* or by restarting QGIS.
- **Architecture.** UI (`main_form.py`, `assessment_wizard_dialog.py`, `ui/`)
  calls `AssessmentExecutor`, which calls the use cases in
  `core/application/use_cases/`. These go through the ports to `AdminManager`
  and `SpatialEngine`. See [`CLAUDE.md`](CLAUDE.md) for the conventions:
  Qt 5/6-compatible code, i18n keys and the layer-status keys.
- **Translations** live in `translations/{en,es,pt,de}.json`. Add every new key to
  all four files.
- **Debugging.** `.vscode/launch.json` attaches to a debugpy listener on
  `127.0.0.1:5678`.
- The `Makefile` and `pb_tool.cfg` come from the Plugin Builder template. Their
  file lists are outdated, so don't use `make deploy` or `make zip` for packaging.

## License

This program is free software; you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation; either version 2 of the License, or (at your option) any later version.

## Author

David Torres (davidt1987@gmail.com)
