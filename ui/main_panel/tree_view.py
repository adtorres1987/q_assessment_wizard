# -*- coding: utf-8 -*-
"""
Tree of the main panel: population, selection, button state, the
analysis visibility checkbox and the helpers that walk from a node to its
project.

Mixin of AssessmentMainForm (ui/main_panel/panel.py): shares its widgets
and state through self and defines no __init__.
"""

from qgis.PyQt.QtCore import Qt
from qgis.core import QgsProject

from ..panels import EMDSTreeModel, ROLE_ID, ROLE_TYPE, ROLE_NAME, ROLE_OUTPUT_TABLES


class TreeViewMixin:
    """Tree of the main panel: population, selection, button state, the"""

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
            self.tree, self.facade.project_tree(),
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
        elif node_type == 'portfolio':
            self._show_portfolio_details(current)
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

        self.btn_new_assessment.setEnabled(path['project_id'] is not None)
        self.btn_run_analysis.setEnabled(path['assessment_id'] is not None)
        self.btn_compare.setEnabled(path['project_id'] is not None)

    # ------------------------------------------------------------------ #
    #  Node → project helpers
    # ------------------------------------------------------------------ #

    def _get_project_name(self, project_id):
        """Return the raw project name from the tree (ROLE_NAME, not display text)."""
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.data(0, ROLE_ID) == project_id:
                return item.data(0, ROLE_NAME) or item.text(0)
        return ''

    def _project_item_of(self, item):
        node = item
        while node is not None and node.data(0, ROLE_TYPE) != 'project':
            node = node.parent()
        return node

    def _executor_for_item(self, item):
        """AssessmentExecutor for the project that contains *item* (or None)."""
        project_item = self._project_item_of(item)
        if project_item is None:
            return None
        return self.facade.executor_for(
            project_item.data(0, ROLE_ID), project_item.data(0, ROLE_NAME) or ''
        )

    @staticmethod
    def _analysis_table(item):
        tables = item.data(0, ROLE_OUTPUT_TABLES) or []
        return tables[0] if tables else ''

    # ------------------------------------------------------------------ #
    #  Layer visibility toggle
    # ------------------------------------------------------------------ #

    def _on_item_changed(self, item, column):
        """Toggle layer visibility when an analysis checkbox changes and persist state."""
        if item.data(0, ROLE_TYPE) != 'analysis':
            return

        checked = item.checkState(0) == Qt.CheckState.Checked
        assessment_id = item.data(0, ROLE_ID)
        output_tables = item.data(0, ROLE_OUTPUT_TABLES) or []

        root = QgsProject.instance().layerTreeRoot()
        for table_name in output_tables:
            self.facade.set_layer_visibility(assessment_id, table_name, checked)
            layers = QgsProject.instance().mapLayersByName(table_name)
            for layer in layers:
                node = root.findLayer(layer.id())
                if node:
                    node.setItemVisibilityChecked(checked)

    def _on_toggle_analysis_visibility(self, item):
        """Toggle the visibility checkbox of an analysis node."""
        self._toggle_result_visibility(item)

    def _toggle_result_visibility(self, item):
        """Toggle the checkbox state of a result (analysis) item."""
        current_state = item.checkState(0)
        new_state = Qt.CheckState.Unchecked if current_state == Qt.CheckState.Checked else Qt.CheckState.Checked
        item.setCheckState(0, new_state)
