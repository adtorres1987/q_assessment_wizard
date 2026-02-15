# -*- coding: utf-8 -*-
"""
Primary/Root form for the Assessment Wizard plugin.
Provides a main interface with a tree view for project/assessment navigation,
a button to launch the assessment wizard, and a text area to display details.
"""

import json
import os
import sqlite3

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QInputDialog, QMessageBox,
    QTreeWidget, QTreeWidgetItem, QMenu, QLabel
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QFont
from qgis.core import QgsProject

from .assessment_wizard_dialog import QassessmentWizardDialog
from .admin_manager import AdminManager

# Custom data roles
ROLE_ID = Qt.UserRole
ROLE_TYPE = Qt.UserRole + 1
ROLE_OUTPUT_TABLES = Qt.UserRole + 2


class EMDSTreeModel:
    """Builds the 5-level EMDS tree:
    Project → [Base Layers | Assessments] → Assessment → Provenance → Task → Result
    """

    @staticmethod
    def populate_tree(tree_widget, admin_manager, plugin_dir,
                      expanded_project_ids=None, selected_type=None, selected_id=None):
        """Populate tree_widget from admin_manager data.

        Returns:
            QTreeWidgetItem or None: item that should be re-selected
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
            proj_item.setText(0, project['name'])
            proj_item.setFont(0, bold_font)
            proj_item.setData(0, ROLE_ID, project['id'])
            proj_item.setData(0, ROLE_TYPE, 'project')
            proj_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)

            if selected_type == 'project' and selected_id == project['id']:
                item_to_select = proj_item

            should_expand = project['id'] in expanded_project_ids

            # Base Layers group (read from project SpatiaLite DB)
            base_layers = EMDSTreeModel._get_base_layers(project, plugin_dir)
            if base_layers:
                bl_group = QTreeWidgetItem(proj_item)
                bl_group.setText(0, "Base Layers")
                bl_group.setFont(0, italic_font)
                bl_group.setData(0, ROLE_TYPE, 'group')
                bl_group.setFlags(Qt.ItemIsEnabled)
                if should_expand:
                    bl_group.setExpanded(True)
                for layer in base_layers:
                    l_item = QTreeWidgetItem(bl_group)
                    l_item.setText(0, layer['layer_name'])
                    l_item.setData(0, ROLE_TYPE, 'base_layer')
                    l_item.setFlags(Qt.ItemIsEnabled)

            # Assessments group
            assessments = admin_manager.get_assessments_for_project(project['id'])
            if assessments:
                ass_group = QTreeWidgetItem(proj_item)
                ass_group.setText(0, "Assessments")
                ass_group.setFont(0, italic_font)
                ass_group.setData(0, ROLE_TYPE, 'group')
                ass_group.setFlags(Qt.ItemIsEnabled)
                if should_expand:
                    ass_group.setExpanded(True)

                for assessment in assessments:
                    a_item = QTreeWidgetItem(ass_group)
                    a_item.setText(0, assessment['name'])
                    a_item.setData(0, ROLE_ID, assessment['id'])
                    a_item.setData(0, ROLE_TYPE, 'assessment')
                    a_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)

                    if selected_type == 'assessment' and selected_id == assessment['id']:
                        item_to_select = a_item

                    # Provenance children
                    provenances = admin_manager.get_provenance_for_assessment(assessment['id'])
                    visibility_cache = admin_manager.get_layer_visibility(assessment['id'])

                    for prov in provenances:
                        p_item = QTreeWidgetItem(a_item)
                        p_item.setText(0, prov['name'])
                        p_item.setData(0, ROLE_ID, prov['id'])
                        p_item.setData(0, ROLE_TYPE, 'provenance')
                        p_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)

                        if selected_type == 'provenance' and selected_id == prov['id']:
                            item_to_select = p_item

                        # Task tree (hierarchical)
                        task_tree = admin_manager.build_task_tree(prov['id'])
                        for found in EMDSTreeModel._build_task_items(
                                p_item, task_tree, assessment['id'],
                                visibility_cache, selected_type, selected_id):
                            if found is not None and item_to_select is None:
                                item_to_select = found

            if should_expand:
                proj_item.setExpanded(True)

        return item_to_select

    @staticmethod
    def _build_task_items(parent_item, task_list, assessment_id, visibility_cache,
                          selected_type, selected_id):
        """Recursively build task and result nodes. Yields items matching selection."""
        for task in task_list:
            label = task.get('category') or task.get('operation') or 'Task'
            t_item = QTreeWidgetItem(parent_item)
            t_item.setText(0, label)
            t_item.setData(0, ROLE_ID, task['id'])
            t_item.setData(0, ROLE_TYPE, 'task')
            t_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)

            if selected_type == 'task' and selected_id == task['id']:
                yield t_item

            # Result nodes (output tables from this task)
            try:
                output_tables = json.loads(task.get('output_tables') or '[]')
            except (json.JSONDecodeError, TypeError):
                output_tables = []

            for table_name in output_tables:
                r_item = QTreeWidgetItem(t_item)
                r_item.setText(0, table_name)
                r_item.setData(0, ROLE_ID, assessment_id)
                r_item.setData(0, ROLE_TYPE, 'result')
                r_item.setData(0, ROLE_OUTPUT_TABLES, [table_name])
                r_item.setFlags(
                    Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable
                )
                is_visible = visibility_cache.get(table_name, True)
                r_item.setCheckState(0, Qt.Checked if is_visible else Qt.Unchecked)

            # Recurse for child tasks
            if task.get('children'):
                yield from EMDSTreeModel._build_task_items(
                    t_item, task['children'], assessment_id,
                    visibility_cache, selected_type, selected_id
                )

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


class AssessmentMainForm(QDialog):
    """Main form that acts as the parent container for assessment operations."""

    def __init__(self, iface, plugin_dir, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.plugin_dir = plugin_dir
        self.selected_path = {
            "project_id": None,
            "assessment_id": None,
            "provenance_id": None,
            "task_id": None
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
            return

        node_type = current.data(0, ROLE_TYPE)
        if node_type == 'assessment':
            self._show_assessment_details(current)
        elif node_type == 'project':
            self._show_project_details(current)
        elif node_type in ('provenance', 'task', 'result'):
            self._show_node_details(current)
        else:
            self.results_text_edit.clear()

    def _update_button_state(self, current):
        """Update selected_path and button states based on the selected tree item."""
        path = {"project_id": None, "assessment_id": None,
                "provenance_id": None, "task_id": None}

        if current:
            node = current
            while node:
                ntype = node.data(0, ROLE_TYPE) or ''
                if ntype == 'project' and path['project_id'] is None:
                    path['project_id'] = node.data(0, ROLE_ID)
                elif ntype == 'assessment' and path['assessment_id'] is None:
                    path['assessment_id'] = node.data(0, ROLE_ID)
                elif ntype == 'provenance' and path['provenance_id'] is None:
                    path['provenance_id'] = node.data(0, ROLE_ID)
                elif ntype == 'task' and path['task_id'] is None:
                    path['task_id'] = node.data(0, ROLE_ID)
                node = node.parent()

        self.selected_path = path
        self.btn_create_assessment.setEnabled(path['project_id'] is not None)

    def _show_assessment_details(self, item):
        """Show assessment info in the details area."""
        assessment_id = item.data(0, ROLE_ID)
        project_name = "?"
        parent = item.parent()
        while parent:
            if parent.data(0, ROLE_TYPE) == 'project':
                project_name = parent.text(0)
                break
            parent = parent.parent()

        output_layers = self.admin_manager.get_assessment_layers(assessment_id, 'output')
        output_str = "\n  - ".join(l['layer_name'] for l in output_layers) or "None"
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

    def _show_node_details(self, item):
        """Show details for provenance, task, or result nodes."""
        node_type = item.data(0, ROLE_TYPE)
        if node_type == 'result':
            tables = item.data(0, ROLE_OUTPUT_TABLES) or []
            self.results_text_edit.setPlainText(f"Result layer: {', '.join(tables)}")
        elif node_type == 'provenance':
            self.results_text_edit.setPlainText(f"Provenance: {item.text(0)}")
        elif node_type == 'task':
            self.results_text_edit.setPlainText(f"Task: {item.text(0)}")

    # ------------------------------------------------------------------ #
    #  Layer visibility toggle
    # ------------------------------------------------------------------ #

    def _on_item_changed(self, item, column):
        """Toggle layer visibility when result checkbox changes and persist state."""
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
            if node_type == 'project':
                act = menu.addAction("New Assessment")
                act.triggered.connect(self.on_create_assessment)
                menu.addSeparator()
                act = menu.addAction("Delete Project")
                act.triggered.connect(lambda: self._on_delete_project(item))
            elif node_type == 'assessment':
                act = menu.addAction("Delete Assessment")
                act.triggered.connect(lambda: self._on_delete_assessment(item))
            elif node_type == 'provenance':
                act = menu.addAction("Delete Provenance")
                act.triggered.connect(lambda: self._on_delete_provenance(item))
            elif node_type == 'result':
                act = menu.addAction("Toggle Visibility")
                act.triggered.connect(lambda: self._toggle_result_visibility(item))

        menu.exec_(self.tree.viewport().mapToGlobal(position))

    # ------------------------------------------------------------------ #
    #  CRUD actions
    # ------------------------------------------------------------------ #

    def _on_new_project(self):
        """Open a QInputDialog to create a new project."""
        name, ok = QInputDialog.getText(self, "New Project", "Project Name:")
        if ok and name.strip():
            try:
                self.admin_manager.create_project(name.strip())
                self._populate_tree()
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not create project:\n{str(e)}")

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

    def _on_delete_provenance(self, item):
        """Delete a provenance record after confirmation."""
        prov_name = item.text(0)
        prov_id = item.data(0, ROLE_ID)
        reply = QMessageBox.question(
            self, "Delete Provenance",
            f"Delete provenance '{prov_name}' and all its tasks?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.admin_manager.delete_provenance(prov_id)
            self._populate_tree()

    def _toggle_result_visibility(self, item):
        """Toggle the checkbox state of a result item."""
        current_state = item.checkState(0)
        new_state = Qt.Unchecked if current_state == Qt.Checked else Qt.Checked
        item.setCheckState(0, new_state)

    def on_create_assessment(self):
        """Launch the assessment wizard dialog and display results."""
        project_id = self.selected_path["project_id"]
        if project_id is None:
            QMessageBox.warning(self, "No Project", "Please select or create a project first.")
            return

        # Resolve project name from tree
        project_name = None
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.data(0, ROLE_ID) == project_id and item.data(0, ROLE_TYPE) == 'project':
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
