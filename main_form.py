# -*- coding: utf-8 -*-
"""
Primary/Root form for the Assessment Wizard plugin.
Provides a main interface with a tree view for project/assessment navigation,
a button to launch the assessment wizard, and a text area to display details.
"""

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QInputDialog, QMessageBox,
    QTreeWidget, QTreeWidgetItem, QMenu, QAction, QLabel
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QFont
from qgis.core import QgsProject

import os

from .assessment_wizard_dialog import QassessmentWizardDialog
from .admin_manager import AdminManager

# Custom data roles
ROLE_ID = Qt.UserRole
ROLE_TYPE = Qt.UserRole + 1
ROLE_OUTPUT_TABLES = Qt.UserRole + 2


class AssessmentMainForm(QDialog):
    """Main form that acts as the parent container for assessment operations."""

    def __init__(self, iface, plugin_dir, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.plugin_dir = plugin_dir
        self.current_project_id = None

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
                # Rename old file so migration doesn't run again
                os.rename(old_metadata_path, old_metadata_path + ".bak")
            except Exception as e:
                print(f"Warning: Migration from metadata.db failed: {e}")

        self.setWindowTitle("Assessment Wizard")
        self.resize(700, 600)

        # Build UI
        layout = QVBoxLayout(self)

        # Buttons row
        btn_layout = QHBoxLayout()

        self.btn_new_project = QPushButton("New Project")
        self.btn_new_project.clicked.connect(self._on_new_project)
        btn_layout.addWidget(self.btn_new_project)

        self.btn_create_assessment = QPushButton("Create Assessment")
        self.btn_create_assessment.setEnabled(False)
        self.btn_create_assessment.clicked.connect(self.on_create_assessment)
        btn_layout.addWidget(self.btn_create_assessment)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Tree widget
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Projects & Assessments"])
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self.tree.currentItemChanged.connect(self._on_tree_selection_changed)
        self.tree.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.tree, 1)

        # Details area
        layout.addWidget(QLabel("Details:"))
        self.results_text_edit = QTextEdit()
        self.results_text_edit.setReadOnly(True)
        self.results_text_edit.setMaximumHeight(150)
        layout.addWidget(self.results_text_edit)

        # Populate tree from SQLite
        self._populate_tree()

    # ------------------------------------------------------------------ #
    #  Tree population
    # ------------------------------------------------------------------ #

    def _populate_tree(self):
        """Populate the tree from SQLite, preserving expansion and selection."""
        # Save state
        expanded_projects = set()
        selected_type = None
        selected_id = None
        current = self.tree.currentItem()
        if current:
            selected_type = current.data(0, ROLE_TYPE)
            selected_id = current.data(0, ROLE_ID)
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.isExpanded():
                expanded_projects.add(item.data(0, ROLE_ID))

        # Block signals while rebuilding
        self.tree.blockSignals(True)
        self.tree.clear()

        bold_font = QFont()
        bold_font.setBold(True)

        item_to_select = None

        projects = self.admin_manager.get_all_projects()
        for project in projects:
            proj_item = QTreeWidgetItem(self.tree)
            proj_item.setText(0, project['name'])
            proj_item.setFont(0, bold_font)
            proj_item.setData(0, ROLE_ID, project['id'])
            proj_item.setData(0, ROLE_TYPE, "project")
            proj_item.setFlags(
                Qt.ItemIsEnabled | Qt.ItemIsSelectable
            )

            # Restore expansion
            if project['id'] in expanded_projects:
                proj_item.setExpanded(True)

            # Check if this was selected
            if selected_type == "project" and selected_id == project['id']:
                item_to_select = proj_item

            # Add assessment children
            assessments = self.admin_manager.get_assessments_for_project(project['id'])
            for assessment in assessments:
                a_item = QTreeWidgetItem(proj_item)
                a_item.setText(0, assessment['name'])
                a_item.setData(0, ROLE_ID, assessment['id'])
                a_item.setData(0, ROLE_TYPE, "assessment")
                a_item.setData(0, ROLE_OUTPUT_TABLES, assessment.get('output_tables', []))
                a_item.setFlags(
                    Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable
                )

                # Restore persisted visibility state
                visibility = self.admin_manager.get_layer_visibility(assessment['id'])
                any_visible = any(visibility.values()) if visibility else False
                a_item.setCheckState(0, Qt.Checked if any_visible else Qt.Unchecked)

                if selected_type == "assessment" and selected_id == assessment['id']:
                    item_to_select = a_item

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
        if current:
            node_type = current.data(0, ROLE_TYPE)
            if node_type == "assessment":
                self._show_assessment_details(current)
            elif node_type == "project":
                self._show_project_details(current)
        else:
            self.results_text_edit.clear()

    def _update_button_state(self, current):
        """Enable/disable Create Assessment based on selection."""
        if current:
            node_type = current.data(0, ROLE_TYPE)
            if node_type == "project":
                self.current_project_id = current.data(0, ROLE_ID)
                self.btn_create_assessment.setEnabled(True)
            elif node_type == "assessment":
                # Use parent project
                parent = current.parent()
                if parent:
                    self.current_project_id = parent.data(0, ROLE_ID)
                    self.btn_create_assessment.setEnabled(True)
            else:
                self.current_project_id = None
                self.btn_create_assessment.setEnabled(False)
        else:
            self.current_project_id = None
            self.btn_create_assessment.setEnabled(False)

    def _show_assessment_details(self, item):
        """Show assessment info in the details area."""
        output_tables = item.data(0, ROLE_OUTPUT_TABLES) or []
        output_str = "\n  - ".join(output_tables) if output_tables else "None"
        project_name = item.parent().text(0) if item.parent() else "?"
        text = (
            f"Project: {project_name}\n"
            f"Assessment: {item.text(0)}\n"
            f"Output layers:\n  - {output_str}"
        )
        self.results_text_edit.setPlainText(text)

    def _show_project_details(self, item):
        """Show project info in the details area."""
        project_id = item.data(0, ROLE_ID)
        assessments = self.admin_manager.get_assessments_for_project(project_id)
        text = (
            f"Project: {item.text(0)}\n"
            f"Assessments: {len(assessments)}"
        )
        self.results_text_edit.setPlainText(text)

    # ------------------------------------------------------------------ #
    #  Layer visibility toggle
    # ------------------------------------------------------------------ #

    def _on_item_changed(self, item, column):
        """Toggle layer visibility when assessment checkbox changes and persist state."""
        if item.data(0, ROLE_TYPE) != "assessment":
            return

        checked = item.checkState(0) == Qt.Checked
        assessment_id = item.data(0, ROLE_ID)
        output_tables = item.data(0, ROLE_OUTPUT_TABLES) or []

        root = QgsProject.instance().layerTreeRoot()
        for table_name in output_tables:
            # Persist visibility state
            self.admin_manager.set_layer_visibility(assessment_id, table_name, checked)
            # Toggle in QGIS layer tree
            layers = QgsProject.instance().mapLayersByName(table_name)
            for layer in layers:
                node = root.findLayer(layer.id())
                if node:
                    node.setItemVisibilityChecked(checked)

    # ------------------------------------------------------------------ #
    #  Context menu
    # ------------------------------------------------------------------ #

    def _on_context_menu(self, position):
        """Show right-click context menu."""
        item = self.tree.itemAt(position)
        menu = QMenu(self)

        if item is None:
            # Empty space
            action_new_project = menu.addAction("New Project")
            action_new_project.triggered.connect(self._on_new_project)
        else:
            node_type = item.data(0, ROLE_TYPE)
            if node_type == "project":
                action_new_assessment = menu.addAction("New Assessment")
                action_new_assessment.triggered.connect(self.on_create_assessment)
                menu.addSeparator()
                action_delete = menu.addAction("Delete Project")
                action_delete.triggered.connect(lambda: self._on_delete_project(item))
            elif node_type == "assessment":
                action_delete = menu.addAction("Delete Assessment")
                action_delete.triggered.connect(lambda: self._on_delete_assessment(item))

        menu.exec_(self.tree.viewport().mapToGlobal(position))

    # ------------------------------------------------------------------ #
    #  CRUD actions
    # ------------------------------------------------------------------ #

    def _on_new_project(self):
        """Open a QInputDialog to create a new project."""
        name, ok = QInputDialog.getText(self, "New Project", "Project Name:")
        if ok and name.strip():
            name = name.strip()
            try:
                self.admin_manager.create_project(name)
                self._populate_tree()
            except Exception as e:
                QMessageBox.warning(
                    self, "Error",
                    f"Could not create project:\n{str(e)}"
                )

    def _on_delete_project(self, item):
        """Delete a project after confirmation."""
        project_name = item.text(0)
        project_id = item.data(0, ROLE_ID)
        reply = QMessageBox.question(
            self, "Delete Project",
            f"Delete project '{project_name}' and all its assessments?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.admin_manager.delete_project(project_id)
            self._populate_tree()

    def _on_delete_assessment(self, item):
        """Delete an assessment after confirmation."""
        assessment_name = item.text(0)
        assessment_id = item.data(0, ROLE_ID)
        reply = QMessageBox.question(
            self, "Delete Assessment",
            f"Delete assessment '{assessment_name}'?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.admin_manager.delete_assessment(assessment_id)
            self._populate_tree()

    def on_create_assessment(self):
        """Launch the assessment wizard dialog and display results."""
        if self.current_project_id is None:
            QMessageBox.warning(self, "No Project", "Please select or create a project first.")
            return

        # Resolve project name from tree
        project_name = None
        project_db_id = self.current_project_id
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.data(0, ROLE_ID) == project_db_id:
                project_name = item.text(0)
                break

        if not project_name:
            QMessageBox.warning(self, "Error", "Could not resolve project name.")
            return

        dlg = QassessmentWizardDialog(
            parent=self,
            iface=self.iface,
            project_id=project_name,
            admin_manager=self.admin_manager,
            project_db_id=project_db_id
        )
        result = dlg.exec_()

        if result == QDialog.Accepted:
            results = dlg.get_results()
            if results:
                self.display_results(results)
            # Refresh tree to show new assessment
            self._populate_tree()
        else:
            self.results_text_edit.setPlainText("Assessment cancelled.")

    def display_results(self, results):
        """Format and display the wizard results in the text area."""
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
        """Reconnect admin manager when form is shown again."""
        if self.admin_manager.connection is None:
            self.admin_manager.connect()
            self._populate_tree()
        super().showEvent(event)

    def closeEvent(self, event):
        """Clean up admin manager on close."""
        self.admin_manager.disconnect()
        super().closeEvent(event)
