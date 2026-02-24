# -*- coding: utf-8 -*-
"""
Primary/Root form for the Assessment Wizard plugin.

EMDS Project Explorer — QDockWidget panel (like Layers/Browser).
The dock is created by assessment_wizard.py and persists for the session.

Tree structure:
  Project → [Base Layers | Assessments] → Assessment → Analyses → v1/v2/...

Action buttons (bottom panel):
  🗂 New Project · + New Assessment · ▶ Run Analysis · 📊 Compare · ⚙ Settings
"""

import json
import os
import re
import sqlite3

from qgis.PyQt.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QInputDialog, QMessageBox,
    QTreeWidget, QTreeWidgetItem, QMenu, QLabel,
    QGroupBox, QListWidget, QListWidgetItem, QFrame
)
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QFont
from qgis.core import QgsProject

from .assessment_wizard_dialog import QassessmentWizardDialog
from .admin_manager import AdminManager

# Custom data roles
ROLE_ID             = Qt.UserRole
ROLE_TYPE           = Qt.UserRole + 1
ROLE_OUTPUT_TABLES  = Qt.UserRole + 2
ROLE_SCENARIO_NAME  = Qt.UserRole + 3   # base scenario name (without __v{n})
ROLE_NAME           = Qt.UserRole + 4   # raw name (separate from display text)


# ---------------------------------------------------------------------------
#  VersionHistoryPanel — Git-like timeline widget
# ---------------------------------------------------------------------------

class VersionHistoryPanel(QGroupBox):
    """Displays the immutable version chain for a selected spatial scenario.

    Shows each overlay snapshot as a list entry with:
      ★ HEAD marker on the current (active) version
      table name and creation timestamp
      "Rollback" and "Compare vs HEAD" action buttons

    Emits:
        rollback_requested(scenario_name, version_id)
        compare_requested(scenario_name, version_id_a, version_id_b)
    """

    rollback_requested = pyqtSignal(str, int)      # scenario_name, version_id
    compare_requested  = pyqtSignal(str, int, int)  # scenario_name, vid_a, vid_b

    def __init__(self, parent=None):
        super().__init__("Version History", parent)
        self._scenario_name   = None
        self._head_version_id = None

        layout = QVBoxLayout(self)

        self._placeholder = QLabel("Select an analysis node to view version history.")
        self._placeholder.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._placeholder)

        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SingleSelection)
        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._list)
        self._list.hide()

        btn_layout = QHBoxLayout()

        self._btn_rollback = QPushButton("\u21ba Rollback to selected")
        self._btn_rollback.setEnabled(False)
        self._btn_rollback.setToolTip(
            "Move HEAD to the selected version — O(1), no spatial recalculation."
        )
        self._btn_rollback.clicked.connect(self._on_rollback)
        btn_layout.addWidget(self._btn_rollback)

        self._btn_compare = QPushButton("\u21c4 Compare with HEAD")
        self._btn_compare.setEnabled(False)
        self._btn_compare.setToolTip(
            "Load the selected version and HEAD as separate QGIS layers for visual comparison."
        )
        self._btn_compare.clicked.connect(self._on_compare)
        btn_layout.addWidget(self._btn_compare)

        layout.addLayout(btn_layout)

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def load_versions(self, scenario_name, db_path):
        """Populate the list from SpatiaLite spatial_versions.

        Args:
            scenario_name: str — base name without __v{n} suffix
            db_path:       str — absolute path to the project SpatiaLite file
        """
        self._scenario_name   = scenario_name
        self._head_version_id = None
        self._list.clear()

        try:
            from .core.spatial_engine import SpatialEngine
            with SpatialEngine(db_path) as engine:
                versions = engine.get_versions(scenario_name)
        except Exception as e:
            self._show_placeholder(f"Could not load versions: {e}")
            return

        if not versions:
            self._show_placeholder("No versions found for this scenario.")
            return

        self._placeholder.hide()
        self._list.show()

        bold_font = QFont()
        bold_font.setBold(True)

        for v in versions:
            is_head = bool(v.get('is_current'))
            if is_head:
                self._head_version_id = v['id']

            timestamp = (v.get('created_at') or '')[:19]
            head_mark = '\u2605 HEAD  ' if is_head else '         '
            label = (
                f"{head_mark}"
                f"  v{v['id']}"
                f"  \u2502  {v.get('table_name', '')}"
                f"  \u2502  {timestamp}"
            )

            item = QListWidgetItem(label)
            item.setData(Qt.UserRole,     v['id'])
            item.setData(Qt.UserRole + 1, is_head)
            if is_head:
                item.setFont(bold_font)
            self._list.addItem(item)

    def clear_panel(self):
        """Reset to empty state (no selection)."""
        self._scenario_name   = None
        self._head_version_id = None
        self._list.clear()
        self._list.hide()
        self._show_placeholder("Select an analysis node to view version history.")
        self._btn_rollback.setEnabled(False)
        self._btn_compare.setEnabled(False)

    # ------------------------------------------------------------------ #
    #  Private helpers
    # ------------------------------------------------------------------ #

    def _show_placeholder(self, text):
        self._placeholder.setText(text)
        self._placeholder.show()
        self._list.hide()

    def _on_selection_changed(self):
        selected = self._list.selectedItems()
        if not selected:
            self._btn_rollback.setEnabled(False)
            self._btn_compare.setEnabled(False)
            return

        item = selected[0]
        is_head = item.data(Qt.UserRole + 1)
        self._btn_rollback.setEnabled(not is_head)
        self._btn_compare.setEnabled(
            not is_head and self._head_version_id is not None
        )

    def _on_rollback(self):
        selected = self._list.selectedItems()
        if not selected or not self._scenario_name:
            return
        version_id = selected[0].data(Qt.UserRole)
        self.rollback_requested.emit(self._scenario_name, version_id)

    def _on_compare(self):
        selected = self._list.selectedItems()
        if not selected or not self._scenario_name or self._head_version_id is None:
            return
        version_id = selected[0].data(Qt.UserRole)
        self.compare_requested.emit(self._scenario_name, version_id, self._head_version_id)


# ---------------------------------------------------------------------------
#  EMDSTreeModel
# ---------------------------------------------------------------------------

class EMDSTreeModel:
    """Builds the EMDS tree:
    Project → [Base Layers | Assessments] → Assessment → Analyses → result
    """

    @staticmethod
    def populate_tree(tree_widget, admin_manager, plugin_dir,
                      expanded_project_ids=None, selected_type=None, selected_id=None):
        """Populate tree_widget from admin_manager data.

        Returns:
            QTreeWidgetItem or None: item to re-select after rebuild.
        """
        if expanded_project_ids is None:
            expanded_project_ids = set()

        bold_font = QFont()
        bold_font.setBold(True)
        italic_font = QFont()
        italic_font.setItalic(True)

        item_to_select = None

        projects = admin_manager.get_all_projects()
        for project in projects:
            proj_item = QTreeWidgetItem(tree_widget)
            proj_item.setText(0, f"📁 Project: {project['name']}")
            proj_item.setFont(0, bold_font)
            proj_item.setData(0, ROLE_ID,   project['id'])
            proj_item.setData(0, ROLE_TYPE, 'project')
            proj_item.setData(0, ROLE_NAME, project['name'])
            proj_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)

            if selected_type == 'project' and selected_id == project['id']:
                item_to_select = proj_item

            should_expand = project['id'] in expanded_project_ids

            # Base Layers group (read from project SpatiaLite DB)
            base_layers = EMDSTreeModel._get_base_layers(project, plugin_dir)
            if base_layers:
                bl_group = QTreeWidgetItem(proj_item)
                bl_group.setText(0, "🗂 Base Layers")
                bl_group.setFont(0, italic_font)
                bl_group.setData(0, ROLE_TYPE, 'base_layers_group')
                bl_group.setFlags(Qt.ItemIsEnabled)
                bl_group.setToolTip(0, "🛈 Base layers are immutable inputs — "
                                       "select them in the wizard to use in an assessment.")
                if should_expand:
                    bl_group.setExpanded(True)
                for layer in base_layers:
                    icon = EMDSTreeModel._geometry_icon(layer['layer_name'])
                    l_item = QTreeWidgetItem(bl_group)
                    l_item.setText(0, f"{icon} {layer['layer_name']}")
                    l_item.setData(0, ROLE_TYPE, 'base_layer')
                    l_item.setData(0, ROLE_NAME, layer['layer_name'])
                    l_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    l_item.setToolTip(0, f"Immutable base layer — not modified by assessments.")

            # Assessments group
            assessments = admin_manager.get_assessments_for_project(project['id'])
            if assessments:
                ass_group = QTreeWidgetItem(proj_item)
                ass_group.setText(0, "📋 Assessments")
                ass_group.setFont(0, italic_font)
                ass_group.setData(0, ROLE_TYPE, 'assessments_group')
                ass_group.setFlags(Qt.ItemIsEnabled)
                if should_expand:
                    ass_group.setExpanded(True)

                for i, assessment in enumerate(assessments, 1):
                    status = EMDSTreeModel._assessment_status(assessment)
                    a_item = QTreeWidgetItem(ass_group)
                    a_item.setText(0, f"{status} {i:02d}_{assessment['name']}")
                    a_item.setData(0, ROLE_ID,   assessment['id'])
                    a_item.setData(0, ROLE_TYPE, 'assessment')
                    a_item.setData(0, ROLE_NAME, assessment['name'])
                    a_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)

                    if selected_type == 'assessment' and selected_id == assessment['id']:
                        item_to_select = a_item

                    # ── 🧩 Input Layers ──────────────────────────────────
                    input_layers = admin_manager.get_assessment_layers(
                        assessment['id'], 'input'
                    )
                    target_name = assessment.get('target_layer', '')
                    if target_name or input_layers:
                        inp_group = QTreeWidgetItem(a_item)
                        inp_group.setText(0, "🧩 Input Layers")
                        inp_group.setFont(0, italic_font)
                        inp_group.setData(0, ROLE_TYPE, 'input_layers_group')
                        inp_group.setFlags(Qt.ItemIsEnabled)

                        if target_name:
                            icon = EMDSTreeModel._geometry_icon(target_name)
                            t_item = QTreeWidgetItem(inp_group)
                            t_item.setText(0, f"{icon} {target_name}  [Target]")
                            t_item.setData(0, ROLE_TYPE, 'input_layer')
                            t_item.setData(0, ROLE_NAME, target_name)
                            t_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                            t_item.setToolTip(
                                0, "Target layer — defines the spatial extent."
                            )
                        for il in input_layers:
                            icon = EMDSTreeModel._geometry_icon(il['layer_name'])
                            il_item = QTreeWidgetItem(inp_group)
                            il_item.setText(0, f"{icon} {il['layer_name']}")
                            il_item.setData(0, ROLE_TYPE, 'input_layer')
                            il_item.setData(0, ROLE_NAME, il['layer_name'])
                            il_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                            il_item.setToolTip(
                                0, "Assessment layer — overlaid with the target."
                            )

                    # ── 📦 Assessment Output ──────────────────────────────
                    out_group = QTreeWidgetItem(a_item)
                    out_group.setText(0, "📦 Assessment Output")
                    out_group.setFont(0, italic_font)
                    out_group.setData(0, ROLE_TYPE, 'output_group')
                    out_group.setFlags(Qt.ItemIsEnabled)
                    out_group.setToolTip(
                        0, "Canonical output — always reproducible, not manually editable."
                    )

                    output_tables = assessment.get('output_tables', [])
                    if not output_tables:
                        placeholder = QTreeWidgetItem(out_group)
                        placeholder.setText(0, "  (no output — run assessment)")
                        placeholder.setFlags(Qt.ItemIsEnabled)
                    else:
                        visibility_cache = admin_manager.get_layer_visibility(
                            assessment['id']
                        )
                        all_tables = EMDSTreeModel._collect_analysis_items(
                            admin_manager, assessment
                        )
                        display_tables = all_tables or output_tables
                        for table_name in display_tables:
                            scenario_name = re.sub(r'__v\d+$', '', table_name)
                            v_match = re.search(r'__v(\d+)$', table_name)
                            label = (
                                f"📦 v{v_match.group(1)}" if v_match
                                else f"📦 {table_name}"
                            )
                            r_item = QTreeWidgetItem(out_group)
                            r_item.setText(0, label)
                            r_item.setData(0, ROLE_ID,            assessment['id'])
                            r_item.setData(0, ROLE_TYPE,          'result')
                            r_item.setData(0, ROLE_OUTPUT_TABLES,  [table_name])
                            r_item.setData(0, ROLE_SCENARIO_NAME,  scenario_name)
                            r_item.setFlags(
                                Qt.ItemIsEnabled | Qt.ItemIsSelectable
                                | Qt.ItemIsUserCheckable
                            )
                            is_visible = visibility_cache.get(table_name, True)
                            r_item.setCheckState(
                                0, Qt.Checked if is_visible else Qt.Unchecked
                            )
                            if selected_type == 'result' and selected_id == assessment['id']:
                                item_to_select = r_item

                    # ── 📊 Analyses (Level 4 placeholder) ─────────────────
                    an_group = QTreeWidgetItem(a_item)
                    an_group.setText(0, "📊 Analyses")
                    an_group.setFont(0, italic_font)
                    an_group.setData(0, ROLE_TYPE, 'analyses_group')
                    an_group.setFlags(Qt.ItemIsEnabled)
                    an_group.setToolTip(0, "Versioned weighted models — Level 4.")

            if should_expand:
                proj_item.setExpanded(True)

        return item_to_select

    @staticmethod
    def _collect_analysis_items(admin_manager, assessment):
        """Return flat list of all output table names for this assessment (all versions)."""
        tables = []
        provenances = admin_manager.get_provenance_for_assessment(assessment['id'])
        for prov in provenances:
            task_tree = admin_manager.build_task_tree(prov['id'])
            EMDSTreeModel._collect_tables_from_tasks(task_tree, tables)
        return tables

    @staticmethod
    def _collect_tables_from_tasks(task_list, tables):
        """Recursively collect output_tables values from a nested task tree."""
        for task in task_list:
            try:
                output_tables = json.loads(task.get('output_tables') or '[]')
            except (json.JSONDecodeError, TypeError):
                output_tables = []
            tables.extend(output_tables)
            if task.get('children'):
                EMDSTreeModel._collect_tables_from_tasks(task['children'], tables)

    @staticmethod
    def _geometry_icon(layer_name):
        """Return a geometry-type emoji by looking up the layer in the active QGIS project.

        Point  → 🔴   Line → 🟦   Polygon → 🟩   Unknown → 🗺
        """
        _icons = {0: "🔴", 1: "🟦", 2: "🟩"}
        layers = QgsProject.instance().mapLayersByName(layer_name)
        if layers:
            return _icons.get(int(layers[0].geometryType()), "🗺")
        return "🗺"

    @staticmethod
    def _assessment_status(assessment) -> str:
        """Return a status emoji for the assessment node.

        🟢 Valid        — overlay completed (has output tables)
        🟡 Needs rebuild — no output tables yet
        🔴 Broken input — target layer not found in the current QGIS project
        """
        output_tables = assessment.get('output_tables', [])
        target_name   = assessment.get('target_layer', '')

        if not output_tables:
            if target_name and not QgsProject.instance().mapLayersByName(target_name):
                return '🔴'
            return '🟡'
        return '🟢'

    @staticmethod
    def _get_base_layers(project, plugin_dir):
        """Read base layer names from project SpatiaLite (plain sqlite3, no extension)."""
        try:
            db_path = os.path.join(plugin_dir, project['db_path'])
            if not os.path.exists(db_path):
                return []
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT layer_name FROM base_layers_registry ORDER BY layer_name"
            )
            layers = [{'layer_name': row[0]} for row in cursor.fetchall()]
            cursor.close()
            conn.close()
            return layers
        except Exception:
            return []


# ---------------------------------------------------------------------------
#  AssessmentMainForm
# ---------------------------------------------------------------------------

class AssessmentMainForm(QWidget):
    """Main form — EMDS Project Explorer (content widget for the dock panel)."""

    def __init__(self, iface, plugin_dir, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.plugin_dir = plugin_dir
        self.selected_path = {
            "project_id": None,
            "assessment_id": None,
        }

        # Initialize admin manager
        self.admin_manager = AdminManager(plugin_dir)
        self.admin_manager.connect()

        # Auto-migrate from old metadata.db if it exists
        old_metadata_path = os.path.join(plugin_dir, "metadata.db")
        if os.path.exists(old_metadata_path):
            try:
                stats = self.admin_manager.migrate_from_metadata_db(old_metadata_path)
                if stats['projects_migrated'] > 0 or stats['assessments_migrated'] > 0:
                    print(f"Migrated {stats['projects_migrated']} projects and "
                          f"{stats['assessments_migrated']} assessments from metadata.db")
                os.rename(old_metadata_path, old_metadata_path + ".bak")
            except Exception as e:
                print(f"Warning: Migration from metadata.db failed: {e}")

        layout = QVBoxLayout(self)

        # ── Tree widget ──────────────────────────────────────────────────
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["EMDS – Project Explorer"])
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self.tree.currentItemChanged.connect(self._on_tree_selection_changed)
        self.tree.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.tree, 1)

        # ── Details text area ────────────────────────────────────────────
        self.results_text_edit = QTextEdit()
        self.results_text_edit.setReadOnly(True)
        self.results_text_edit.setMaximumHeight(100)
        layout.addWidget(self.results_text_edit)

        # ── Version History panel ────────────────────────────────────────
        self._version_panel = VersionHistoryPanel()
        self._version_panel.setMaximumHeight(160)
        self._version_panel.rollback_requested.connect(self._on_rollback_version)
        self._version_panel.compare_requested.connect(self._on_compare_versions)
        layout.addWidget(self._version_panel)

        # ── Separator ────────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep)

        # ── Action buttons (vertical stack) ──────────────────────────────
        self.btn_new_project = QPushButton("🗂 New Project")
        self.btn_new_project.clicked.connect(self._on_new_project)
        layout.addWidget(self.btn_new_project)

        self.btn_new_assessment = QPushButton("+ New Assessment")
        self.btn_new_assessment.setEnabled(False)
        self.btn_new_assessment.clicked.connect(self.on_create_assessment)
        layout.addWidget(self.btn_new_assessment)

        self.btn_run_analysis = QPushButton("▶ Run Analysis")
        self.btn_run_analysis.setEnabled(False)
        self.btn_run_analysis.setToolTip(
            "Re-run the spatial overlay for the selected assessment (creates a new version)."
        )
        self.btn_run_analysis.clicked.connect(self._on_run_analysis)
        layout.addWidget(self.btn_run_analysis)

        self.btn_compare = QPushButton("📊 Compare")
        self.btn_compare.setEnabled(False)
        self.btn_compare.setToolTip(
            "Load version history for the selected analysis and compare with HEAD."
        )
        self.btn_compare.clicked.connect(self._on_compare_clicked)
        layout.addWidget(self.btn_compare)

        self.btn_settings = QPushButton("⚙ Settings")
        self.btn_settings.setEnabled(False)  # placeholder
        self.btn_settings.clicked.connect(self._on_settings)
        layout.addWidget(self.btn_settings)

        # Populate tree
        self._populate_tree()

    # ------------------------------------------------------------------ #
    #  Tree population
    # ------------------------------------------------------------------ #

    def _populate_tree(self):
        """Populate the tree from SQLite, preserving expansion and selection."""
        # Save state
        expanded_project_ids = set()
        current = self.tree.currentItem()
        selected_type = current.data(0, ROLE_TYPE) if current else None
        selected_id = current.data(0, ROLE_ID) if current else None
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.isExpanded():
                expanded_project_ids.add(item.data(0, ROLE_ID))

        # Rebuild tree
        self.tree.blockSignals(True)
        self.tree.clear()

        item_to_select = EMDSTreeModel.populate_tree(
            self.tree, self.admin_manager, self.plugin_dir,
            expanded_project_ids=expanded_project_ids,
            selected_type=selected_type,
            selected_id=selected_id
        )

        self.tree.blockSignals(False)

        # Restore selection
        if item_to_select:
            self.tree.setCurrentItem(item_to_select)
        else:
            self._update_button_state(None)

    # ------------------------------------------------------------------ #
    #  Selection handling
    # ------------------------------------------------------------------ #

    def _on_tree_selection_changed(self, current, previous):
        """Handle tree selection changes."""
        self._update_button_state(current)
        if not current:
            self.results_text_edit.clear()
            self._version_panel.clear_panel()
            return

        node_type = current.data(0, ROLE_TYPE)
        if node_type == 'project':
            self._show_project_details(current)
            self._version_panel.clear_panel()
        elif node_type == 'assessment':
            self._show_assessment_details(current)
            self._version_panel.clear_panel()
        elif node_type == 'result':
            self._show_node_details(current)
            self._load_version_history(current)
        else:
            self.results_text_edit.clear()
            self._version_panel.clear_panel()

    def _update_button_state(self, current):
        """Update selected_path and bottom button states based on the selected node."""
        path = {"project_id": None, "assessment_id": None}

        if current:
            node = current
            while node:
                ntype = node.data(0, ROLE_TYPE) or ''
                if ntype == 'project' and path['project_id'] is None:
                    path['project_id'] = node.data(0, ROLE_ID)
                elif ntype == 'assessment' and path['assessment_id'] is None:
                    path['assessment_id'] = node.data(0, ROLE_ID)
                node = node.parent()

        self.selected_path = path
        node_type = current.data(0, ROLE_TYPE) if current else None

        self.btn_new_assessment.setEnabled(path['project_id'] is not None)
        self.btn_run_analysis.setEnabled(path['assessment_id'] is not None)
        self.btn_compare.setEnabled(
            node_type == 'result' and path['assessment_id'] is not None
        )

    def _show_assessment_details(self, item):
        """Show assessment summary in the details area."""
        assessment_id   = item.data(0, ROLE_ID)
        assessment_name = item.data(0, ROLE_NAME) or item.text(0)

        project_name = "?"
        parent = item.parent()
        while parent:
            if parent.data(0, ROLE_TYPE) == 'project':
                project_name = parent.data(0, ROLE_NAME) or parent.text(0)
                break
            parent = parent.parent()

        input_layers  = self.admin_manager.get_assessment_layers(assessment_id, 'input')
        output_layers = self.admin_manager.get_assessment_layers(assessment_id, 'output')
        input_str  = "\n  - ".join(l['layer_name'] for l in input_layers)  or "None"
        output_str = "\n  - ".join(l['layer_name'] for l in output_layers) or "None"
        text = (
            f"Project:    {project_name}\n"
            f"Assessment: {assessment_name}\n"
            f"Inputs:\n  - {input_str}\n"
            f"Output(s):\n  - {output_str}"
        )
        self.results_text_edit.setPlainText(text)

    def _show_project_details(self, item):
        """Show project summary in the details area."""
        project_id = item.data(0, ROLE_ID)
        project_name = item.data(0, ROLE_NAME) or item.text(0)
        assessments = self.admin_manager.get_assessments_for_project(project_id)
        text = (
            f"Project: {project_name}\n"
            f"Assessments: {len(assessments)}"
        )
        self.results_text_edit.setPlainText(text)

    def _show_node_details(self, item):
        """Show details for a result (analysis) node."""
        tables = item.data(0, ROLE_OUTPUT_TABLES) or []
        scenario = item.data(0, ROLE_SCENARIO_NAME) or ''
        self.results_text_edit.setPlainText(
            f"Result layer: {', '.join(tables)}\n"
            f"Scenario: {scenario}"
        )

    # ------------------------------------------------------------------ #
    #  Version History panel
    # ------------------------------------------------------------------ #

    def _load_version_history(self, result_item):
        """Populate the VersionHistoryPanel for the given result node."""
        scenario_name = result_item.data(0, ROLE_SCENARIO_NAME)
        if not scenario_name:
            self._version_panel.clear_panel()
            return

        project_id = self.selected_path.get('project_id')
        if not project_id:
            self._version_panel.clear_panel()
            return

        db_path = self.admin_manager.get_project_db_path(project_id)
        if not db_path:
            self._version_panel.clear_panel()
            return

        self._version_panel.load_versions(scenario_name, db_path)

    def _on_rollback_version(self, scenario_name, version_id):
        """Handle rollback signal from VersionHistoryPanel."""
        project_id = self.selected_path.get('project_id')
        if not project_id:
            return

        project_name = self._get_project_name(project_id)
        from .assessment_executor import AssessmentExecutor
        executor = AssessmentExecutor(project_name, self.admin_manager, project_id)
        result = executor.rollback_to_version(scenario_name, version_id, parent_widget=self)

        if result:
            current = self.tree.currentItem()
            if current and current.data(0, ROLE_TYPE) == 'result':
                self._load_version_history(current)

    def _on_compare_versions(self, scenario_name, version_id_a, version_id_b):
        """Handle compare signal from VersionHistoryPanel."""
        project_id = self.selected_path.get('project_id')
        if not project_id:
            return

        project_name = self._get_project_name(project_id)
        from .assessment_executor import AssessmentExecutor
        executor = AssessmentExecutor(project_name, self.admin_manager, project_id)
        executor.compare_versions(
            scenario_name, version_id_a, version_id_b, parent_widget=self
        )

    def _get_project_name(self, project_id):
        """Return the raw project name from the tree (ROLE_NAME, not display text)."""
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.data(0, ROLE_ID) == project_id:
                return item.data(0, ROLE_NAME) or item.text(0)
        return ''

    # ------------------------------------------------------------------ #
    #  Layer visibility toggle
    # ------------------------------------------------------------------ #

    def _on_item_changed(self, item, column):
        """Toggle layer visibility when a result checkbox changes and persist state."""
        if item.data(0, ROLE_TYPE) != 'result':
            return

        checked = item.checkState(0) == Qt.Checked
        assessment_id = item.data(0, ROLE_ID)
        output_tables = item.data(0, ROLE_OUTPUT_TABLES) or []

        root = QgsProject.instance().layerTreeRoot()
        for table_name in output_tables:
            self.admin_manager.set_layer_visibility(assessment_id, table_name, checked)
            layers = QgsProject.instance().mapLayersByName(table_name)
            for layer in layers:
                node = root.findLayer(layer.id())
                if node:
                    node.setItemVisibilityChecked(checked)

    # ------------------------------------------------------------------ #
    #  Context menu
    # ------------------------------------------------------------------ #

    def _on_context_menu(self, position):
        """Show right-click context menu based on node type."""
        item = self.tree.itemAt(position)
        menu = QMenu(self)

        if item is None:
            act = menu.addAction("New Project")
            act.triggered.connect(self._on_new_project)
        else:
            node_type = item.data(0, ROLE_TYPE) or ''
            if node_type == 'base_layers_group':
                lbl = menu.addAction("🛈 Base layers are immutable inputs")
                lbl.setEnabled(False)
            elif node_type == 'base_layer':
                act = menu.addAction("🔍 Zoom to Layer")
                act.triggered.connect(lambda checked, i=item: self._on_zoom_to_base_layer(i))
                act = menu.addAction("📋 Layer Info")
                act.triggered.connect(lambda checked, i=item: self._on_base_layer_info(i))
            elif node_type == 'project':
                act = menu.addAction("+ New Assessment")
                act.triggered.connect(self.on_create_assessment)
                menu.addSeparator()
                act = menu.addAction("⚙ Project Settings…")
                act.triggered.connect(lambda checked, i=item: self._on_project_settings(i))
                act = menu.addAction("📤 Export Metadata…")
                act.triggered.connect(lambda checked, i=item: self._on_export_project_metadata(i))
                act = menu.addAction("✓ Validate Project")
                act.triggered.connect(lambda checked, i=item: self._on_validate_project(i))
                menu.addSeparator()
                act = menu.addAction("🗑 Delete Project…")
                act.triggered.connect(lambda checked, i=item: self._on_delete_project(i))
            elif node_type == 'assessment':
                act = menu.addAction("🔄 Rebuild Assessment")
                act.triggered.connect(lambda checked, i=item: self._on_new_version(i))
                act = menu.addAction("✏ Rename…")
                act.triggered.connect(lambda checked, i=item: self._on_rename_assessment(i))
                act = menu.addAction("📋 Duplicate (New Scenario)…")
                act.triggered.connect(
                    lambda checked, i=item: self._on_duplicate_assessment(i)
                )
                menu.addSeparator()
                act = menu.addAction("🗑 Delete Assessment…")
                act.triggered.connect(lambda checked, i=item: self._on_delete_assessment(i))
            elif node_type == 'input_layers_group':
                lbl = menu.addAction("🛈 Input layers define the spatial overlay")
                lbl.setEnabled(False)
            elif node_type == 'input_layer':
                act = menu.addAction("🔍 Zoom to Layer")
                act.triggered.connect(
                    lambda checked, i=item: self._on_zoom_to_base_layer(i)
                )
                act = menu.addAction("📋 Layer Info")
                act.triggered.connect(
                    lambda checked, i=item: self._on_base_layer_info(i)
                )
            elif node_type == 'output_group':
                lbl = menu.addAction("🛈 Canonical output — always reproducible")
                lbl.setEnabled(False)
            elif node_type == 'analyses_group':
                lbl = menu.addAction("📊 Versioned models — coming in Level 4")
                lbl.setEnabled(False)
            elif node_type == 'result':
                act = menu.addAction("Toggle Visibility")
                act.triggered.connect(lambda: self._toggle_result_visibility(item))
                menu.addSeparator()
                act = menu.addAction("View Version History")
                act.triggered.connect(lambda: self._load_version_history(item))

        menu.exec_(self.tree.viewport().mapToGlobal(position))

    # ------------------------------------------------------------------ #
    #  Action button handlers
    # ------------------------------------------------------------------ #

    def _on_run_analysis(self):
        """Re-run spatial overlay for the selected assessment (new version)."""
        node = self.tree.currentItem()
        while node:
            if node.data(0, ROLE_TYPE) == 'assessment':
                self._on_new_version(node)
                return
            node = node.parent()

    def _on_compare_clicked(self):
        """Load version history for the selected analysis node (use panel to compare)."""
        current = self.tree.currentItem()
        if current and current.data(0, ROLE_TYPE) == 'result':
            self._load_version_history(current)

    def _on_settings(self):
        """Open settings dialog (placeholder)."""
        QMessageBox.information(self, "Settings", "Settings not yet implemented.")

    # ------------------------------------------------------------------ #
    #  CRUD actions
    # ------------------------------------------------------------------ #

    def _on_zoom_to_base_layer(self, item):
        """Zoom the QGIS canvas to the selected base layer."""
        layer_name = item.data(0, ROLE_NAME) or item.text(0)
        layers = QgsProject.instance().mapLayersByName(layer_name)
        if layers:
            self.iface.setActiveLayer(layers[0])
            self.iface.zoomToActiveLayer()
        else:
            QMessageBox.information(
                self, "Layer Not Found",
                f"'{layer_name}' is not currently loaded in the QGIS project."
            )

    def _on_base_layer_info(self, item):
        """Show basic info about the selected base layer."""
        layer_name = item.data(0, ROLE_NAME) or item.text(0)
        layers = QgsProject.instance().mapLayersByName(layer_name)
        if layers:
            layer = layers[0]
            gt_labels = {0: "Point", 1: "Line", 2: "Polygon"}
            gt = gt_labels.get(int(layer.geometryType()), "Unknown")
            feat_count = layer.featureCount()
            crs = layer.crs().authid()
            QMessageBox.information(
                self, f"Layer Info — {layer_name}",
                f"Name:         {layer_name}\n"
                f"Geometry:     {gt}\n"
                f"Features:     {feat_count}\n"
                f"CRS:          {crs}\n\n"
                f"🛈 This is an immutable base layer."
            )
        else:
            QMessageBox.information(
                self, "Layer Not Found",
                f"'{layer_name}' is not currently loaded in the QGIS project."
            )

    def _on_new_project(self):
        """Create a new project via QInputDialog."""
        name, ok = QInputDialog.getText(self, "New Project", "Project Name:")
        if ok and name.strip():
            try:
                self.admin_manager.create_project(name.strip())
                self._populate_tree()
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not create project:\n{str(e)}")

    def _on_project_settings(self, item):
        """Open project settings (placeholder)."""
        project_name = item.data(0, ROLE_NAME) or item.text(0)
        QMessageBox.information(
            self, "Project Settings",
            f"Project settings for '{project_name}' — not yet implemented."
        )

    def _on_export_project_metadata(self, item):
        """Export project metadata to JSON (placeholder)."""
        project_name = item.data(0, ROLE_NAME) or item.text(0)
        QMessageBox.information(
            self, "Export Metadata",
            f"Export metadata for '{project_name}' — not yet implemented."
        )

    def _on_validate_project(self, item):
        """Validate project integrity (placeholder)."""
        project_name = item.data(0, ROLE_NAME) or item.text(0)
        QMessageBox.information(
            self, "Validate Project",
            f"Validation for '{project_name}' — not yet implemented."
        )

    def _on_delete_project(self, item):
        """Delete a project — requires typing the project name to confirm."""
        project_name = item.data(0, ROLE_NAME) or item.text(0)
        project_id = item.data(0, ROLE_ID)

        typed, ok = QInputDialog.getText(
            self, "Delete Project",
            f"This will permanently delete '{project_name}' and ALL its assessments.\n\n"
            f"Type the project name to confirm:"
        )
        if ok and typed.strip() == project_name:
            self.admin_manager.delete_project(project_id)
            self._populate_tree()
        elif ok:
            QMessageBox.warning(
                self, "Delete Cancelled",
                "Project name did not match. No changes were made."
            )

    def _on_delete_assessment(self, item):
        """Delete an assessment after confirmation."""
        assessment_name = item.data(0, ROLE_NAME) or item.text(0)
        assessment_id = item.data(0, ROLE_ID)
        reply = QMessageBox.question(
            self, "Delete Assessment",
            f"Delete assessment '{assessment_name}'?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.admin_manager.delete_assessment(assessment_id)
            self._populate_tree()

    def _on_rename_assessment(self, item):
        """Rename an assessment via QInputDialog."""
        assessment_name = item.data(0, ROLE_NAME) or item.text(0)
        assessment_id = item.data(0, ROLE_ID)
        new_name, ok = QInputDialog.getText(
            self, "Rename Assessment",
            f"New name for '{assessment_name}':",
            text=assessment_name
        )
        if ok and new_name.strip() and new_name.strip() != assessment_name:
            try:
                self.admin_manager.rename_assessment(assessment_id, new_name.strip())
                self._populate_tree()
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not rename:\n{str(e)}")

    def _on_duplicate_assessment(self, item):
        """Duplicate an assessment as a new scenario (placeholder)."""
        assessment_name = item.data(0, ROLE_NAME) or item.text(0)
        QMessageBox.information(
            self, "Duplicate Assessment",
            f"Duplicate '{assessment_name}' — not yet implemented."
        )

    def _toggle_result_visibility(self, item):
        """Toggle the checkbox state of a result (analysis) item."""
        current_state = item.checkState(0)
        new_state = Qt.Unchecked if current_state == Qt.Checked else Qt.Checked
        item.setCheckState(0, new_state)

    def _on_new_version(self, item):
        """Re-run spatial overlay for this assessment, creating a new version."""
        assessment_id = item.data(0, ROLE_ID)
        project_id = self.selected_path.get('project_id')
        if not project_id:
            return

        assessment_name = item.data(0, ROLE_NAME) or item.text(0)
        input_layers = self.admin_manager.get_assessment_layers(
            assessment_id, layer_type='input'
        )
        if not input_layers:
            QMessageBox.warning(
                self, "Not Supported",
                f"Assessment '{assessment_name}' is a simple (memory) assessment.\n"
                "Only spatial assessments support versioning."
            )
            return

        reply = QMessageBox.question(
            self, "New Version",
            f"Create a new version of assessment '{assessment_name}'?\n\n"
            "This will re-run the spatial overlay with the same layers.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        project_name = self._get_project_name(project_id)
        from .assessment_executor import AssessmentExecutor
        executor = AssessmentExecutor(project_name, self.admin_manager, project_id)
        result = executor.rerun_spatial_assessment(assessment_id, parent_widget=self)

        if result:
            self._populate_tree()

    def on_create_assessment(self):
        """Launch the assessment wizard dialog and display results."""
        project_id = self.selected_path["project_id"]
        if project_id is None:
            QMessageBox.warning(self, "No Project", "Please select or create a project first.")
            return

        project_name = self._get_project_name(project_id)
        if not project_name:
            QMessageBox.warning(self, "Error", "Could not resolve project name.")
            return

        dlg = QassessmentWizardDialog(
            parent=self,
            iface=self.iface,
            project_id=project_name,
            admin_manager=self.admin_manager,
            project_db_id=project_id
        )
        result = dlg.exec_()

        if result == QDialog.Accepted:
            results = dlg.get_results()
            if results:
                self.display_results(results)
            self._populate_tree()
        else:
            self.results_text_edit.setPlainText("Assessment cancelled.")

    def display_results(self, results):
        """Format and display the wizard results in the details area."""
        assessment_layers_str = ", ".join(results.get("assessment_layers", [])) or "None"
        output_tables_str = "\n  - ".join(results.get("output_tables", [])) or "None"
        text = (
            f"Assessment Name: {results.get('assessment_name', '')}\n"
            f"Target Layer: {results.get('target_layer', '')}\n"
            f"Assessment Layers: {assessment_layers_str}\n"
            f"Output Table(s):\n  - {output_tables_str}\n"
            f"Description: {results.get('description', '')}"
        )
        self.results_text_edit.setPlainText(text)

    # ------------------------------------------------------------------ #
    #  Lifecycle
    # ------------------------------------------------------------------ #

    def showEvent(self, event):
        """Reconnect admin manager when panel is shown again."""
        if self.admin_manager.connection is None:
            self.admin_manager.connect()
            self._populate_tree()
        super().showEvent(event)
