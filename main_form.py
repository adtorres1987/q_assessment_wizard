# -*- coding: utf-8 -*-
"""
Primary/Root form for the Assessment Wizard plugin.

EMDS Project Explorer — QDockWidget panel (like Layers/Browser).
The dock is created by assessment_wizard.py and persists for the session.

Tree structure:
  Project → [Base Layers | Assessments] → Assessment → Analyses → v1/v2/...

Action buttons (bottom panel):
  🗂 New Project · + New Assessment · ▶ Run Analysis
"""

import os

from qgis.PyQt.QtWidgets import (
    QDialog, QWidget, QVBoxLayout,
    QPushButton, QTextEdit, QInputDialog, QMessageBox,
    QTreeWidget, QMenu, QFrame, QStackedWidget,
)
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsProject

from .assessment_wizard_dialog import QassessmentWizardDialog
from .admin_manager import AdminManager
from .ui.panels import (
    AssessmentDetailPanel,
    AnalysisDetailPanel,
    EMDSTreeModel,
    ROLE_ID, ROLE_TYPE, ROLE_NAME,
    ROLE_OUTPUT_TABLES, ROLE_SCENARIO_NAME,
)


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

        # ── Contextual detail panel (stacked: assessment card | text area) ──
        self._detail_stack = QStackedWidget()
        self._detail_stack.setMaximumHeight(200)

        self._assessment_panel = AssessmentDetailPanel()
        self._assessment_panel.rebuild_clicked.connect(self._on_run_analysis)
        self._assessment_panel.weights_edit_clicked.connect(self._on_edit_weights)
        self._detail_stack.addWidget(self._assessment_panel)   # index 0

        self.results_text_edit = QTextEdit()
        self.results_text_edit.setReadOnly(True)
        self._detail_stack.addWidget(self.results_text_edit)   # index 1

        self._analysis_panel = AnalysisDetailPanel(self.admin_manager)
        self._analysis_panel.run_again_clicked.connect(self._on_run_mcda)
        self._detail_stack.addWidget(self._analysis_panel)     # index 2

        self._detail_stack.setCurrentIndex(1)
        layout.addWidget(self._detail_stack)

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
            self.tree, self.admin_manager,
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
            self._detail_stack.setCurrentIndex(1)
            self.results_text_edit.clear()
            return

        node_type = current.data(0, ROLE_TYPE)
        if node_type == 'project':
            self._show_project_details(current)
        elif node_type in ('assessment', 'weights'):
            self._show_assessment_details(current)
        elif node_type == 'analysis':
            self._show_analysis_details(current)
        else:
            self._detail_stack.setCurrentIndex(1)
            self.results_text_edit.clear()

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

    def _show_assessment_details(self, item):
        """Show assessment detail card in the contextual panel."""
        assessment_id   = item.data(0, ROLE_ID)
        assessment_name = item.data(0, ROLE_NAME) or item.text(0)

        assessment   = self.admin_manager.get_assessment(assessment_id)
        input_layers = self.admin_manager.get_assessment_layers(assessment_id, 'input')
        target_layer = assessment.get('target_layer', '') if assessment else ''
        created_at   = assessment.get('created_at', '')  if assessment else ''

        import json as _json
        config  = self.admin_manager.get_analysis_config(assessment_id)
        weights = {}
        if config:
            try:
                weights = _json.loads(config.get('weights_json') or '{}')
            except (ValueError, TypeError):
                weights = {}

        self._assessment_panel.show_assessment(
            name=assessment_name,
            input_layers=input_layers,
            target_layer=target_layer,
            created_at=created_at,
            assessment_id=assessment_id,
            weights=weights,
        )
        self._detail_stack.setCurrentIndex(0)

    def _show_project_details(self, item):
        """Show project summary in the details area."""
        project_id = item.data(0, ROLE_ID)
        project_name = item.data(0, ROLE_NAME) or item.text(0)
        assessments = self.admin_manager.get_assessments_for_project(project_id)
        text = (
            f"Project: {project_name}\n"
            f"Assessments: {len(assessments)}"
        )
        self._detail_stack.setCurrentIndex(1)
        self.results_text_edit.setPlainText(text)

    def _show_node_details(self, item):
        """Show details for a result (analysis) node."""
        tables = item.data(0, ROLE_OUTPUT_TABLES) or []
        scenario = item.data(0, ROLE_SCENARIO_NAME) or ''
        self._detail_stack.setCurrentIndex(1)
        self.results_text_edit.setPlainText(
            f"Result layer: {', '.join(tables)}\n"
            f"Scenario: {scenario}"
        )

    def _show_analysis_details(self, item):
        """Show the AnalysisDetailPanel for an analysis (📈 Model_v{n}) node."""
        assessment_id = item.data(0, ROLE_ID)
        model_name    = item.data(0, ROLE_NAME) or item.text(0)
        tables        = item.data(0, ROLE_OUTPUT_TABLES) or []
        table_name    = tables[0] if tables else ''
        self._analysis_panel.load(assessment_id, table_name, model_name)
        self._detail_stack.setCurrentIndex(2)

    # ------------------------------------------------------------------ #
    #  Version History panel
    # ------------------------------------------------------------------ #

    def _on_edit_weights(self, assessment_id):
        """Open WeightsEditDialog for the given assessment."""
        from .ui.panels.analysis_detail_panel import WeightsEditDialog
        dlg = WeightsEditDialog(assessment_id, self.admin_manager, parent=self)
        if dlg.exec_():
            self._populate_tree()
            current = self.tree.currentItem()
            if current:
                self._show_assessment_details(current)

    def _on_run_mcda(self, assessment_id, table_name):
        """Handle run_again_clicked signal from AnalysisDetailPanel."""
        project_id = self.selected_path.get('project_id')
        if not project_id:
            return
        project_name = self._get_project_name(project_id)
        from .assessment_executor import AssessmentExecutor
        executor = AssessmentExecutor(project_name, self.admin_manager, project_id)
        executor.apply_mcda_score(assessment_id, table_name, parent_widget=self)

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
        """Toggle layer visibility when an analysis checkbox changes and persist state."""
        if item.data(0, ROLE_TYPE) != 'analysis':
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
            elif node_type == 'project':
                act = menu.addAction("+ New Assessment")
                act.triggered.connect(self.on_create_assessment)
                menu.addSeparator()
                act = menu.addAction("🗑 Delete Project…")
                act.triggered.connect(lambda checked, i=item: self._on_delete_project(i))
            elif node_type == 'assessment':
                act = menu.addAction("🔄 Rebuild Assessment")
                act.triggered.connect(lambda checked, i=item: self._on_new_version(i))
                act = menu.addAction("✏ Rename…")
                act.triggered.connect(lambda checked, i=item: self._on_rename_assessment(i))
                menu.addSeparator()
                act = menu.addAction("🗑 Delete Assessment…")
                act.triggered.connect(lambda checked, i=item: self._on_delete_assessment(i))
            elif node_type == 'weights':
                act = menu.addAction("✏ Edit Weights…")
                act.triggered.connect(
                    lambda checked, i=item: self._on_edit_weights_from_tree(i)
                )
            elif node_type == 'analysis':
                act = menu.addAction("👁 Toggle Visibility")
                act.triggered.connect(
                    lambda checked, i=item: self._on_toggle_analysis_visibility(i)
                )

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


    # ------------------------------------------------------------------ #
    #  CRUD actions
    # ------------------------------------------------------------------ #

    def _on_new_project(self):
        """Create a new project via QInputDialog."""
        name, ok = QInputDialog.getText(self, "New Project", "Project Name:")
        if ok and name.strip():
            try:
                self.admin_manager.create_project(name.strip())
                self._populate_tree()
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not create project:\n{str(e)}")

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

    def _on_toggle_analysis_visibility(self, item):
        """Toggle the visibility checkbox of an analysis node."""
        self._toggle_result_visibility(item)

    def _on_edit_weights_from_tree(self, item):
        """Open the weights editor for the assessment linked to this weights node."""
        assessment_id = item.data(0, ROLE_ID)
        if assessment_id is not None:
            self._analysis_panel.load(assessment_id, '', '')
            self._analysis_panel._on_edit_weights()

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
            self._detail_stack.setCurrentIndex(1)
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
        self._detail_stack.setCurrentIndex(1)
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
