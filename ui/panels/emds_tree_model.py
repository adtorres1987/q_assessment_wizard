# -*- coding: utf-8 -*-
"""ROLE_* constants and EMDSTreeModel — builds the EMDS project tree."""

import json
import re

from qgis.PyQt.QtWidgets import QTreeWidget, QTreeWidgetItem
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QFont
from qgis.core import QgsProject

# Custom data roles
ROLE_ID             = Qt.UserRole
ROLE_TYPE           = Qt.UserRole + 1
ROLE_OUTPUT_TABLES  = Qt.UserRole + 2
ROLE_SCENARIO_NAME  = Qt.UserRole + 3   # base scenario name (without __v{n})
ROLE_NAME           = Qt.UserRole + 4   # raw name (separate from display text)


class EMDSTreeModel:
    """Builds the EMDS tree:
    Project → Base Layers | Assessment → Weights + Analysis v{n}
    """

    @staticmethod
    def populate_tree(tree_widget, admin_manager, plugin_dir=None,
                      expanded_project_ids=None, selected_type=None, selected_id=None):
        """Populate tree_widget from admin_manager data.

        Args:
            tree_widget:          QTreeWidget to populate
            admin_manager:        AdminManager instance
            plugin_dir:           ignored (kept for backward compatibility)
            expanded_project_ids: set of project IDs to auto-expand
            selected_type:        str — node type to re-select after rebuild
            selected_id:          int — node ID to re-select after rebuild

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
            proj_item.setText(0, f"📁 {project['name']}")
            proj_item.setFont(0, bold_font)
            proj_item.setData(0, ROLE_ID,   project['id'])
            proj_item.setData(0, ROLE_TYPE, 'project')
            proj_item.setData(0, ROLE_NAME, project['name'])
            proj_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)

            if selected_type == 'project' and selected_id == project['id']:
                item_to_select = proj_item

            should_expand = project['id'] in expanded_project_ids

            # ── 📁 Base Layers ────────────────────────────────────────────
            base_layers = EMDSTreeModel._get_base_layers(project, admin_manager)
            if base_layers:
                bl_group = QTreeWidgetItem(proj_item)
                bl_group.setText(0, "📁 Base Layers")
                bl_group.setFont(0, italic_font)
                bl_group.setData(0, ROLE_TYPE, 'base_layers_group')
                bl_group.setFlags(Qt.ItemIsEnabled)
                if should_expand:
                    bl_group.setExpanded(True)
                for layer in base_layers:
                    icon = EMDSTreeModel._geometry_icon(layer['layer_name'])
                    l_item = QTreeWidgetItem(bl_group)
                    l_item.setText(0, f"{icon} {layer['layer_name']}")
                    l_item.setData(0, ROLE_TYPE, 'base_layer')
                    l_item.setData(0, ROLE_NAME, layer['layer_name'])
                    l_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)

            # ── Assessments (direct children — no wrapper group) ──────────
            assessments = admin_manager.get_assessments_for_project(project['id'])
            for assessment in assessments:
                status = EMDSTreeModel._assessment_status(assessment)
                a_item = QTreeWidgetItem(proj_item)
                a_item.setText(0, f"{status} 📁 {assessment['name']}")
                a_item.setData(0, ROLE_ID,   assessment['id'])
                a_item.setData(0, ROLE_TYPE, 'assessment')
                a_item.setData(0, ROLE_NAME, assessment['name'])
                a_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)

                if selected_type == 'assessment' and selected_id == assessment['id']:
                    item_to_select = a_item

                # ── ⚙ Weights ─────────────────────────────────────────────
                w_item = QTreeWidgetItem(a_item)
                w_item.setText(0, "⚙ Weights")
                w_item.setData(0, ROLE_TYPE, 'weights')
                w_item.setData(0, ROLE_ID,   assessment['id'])
                w_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)

                config = admin_manager.get_analysis_config(assessment['id'])
                if config:
                    try:
                        weights = json.loads(config.get('weights_json') or '{}')
                        for layer_name, w in weights.items():
                            wl_item = QTreeWidgetItem(w_item)
                            wl_item.setText(0, f"  {layer_name}: {w * 100:.0f}%")
                            wl_item.setFlags(Qt.ItemIsEnabled)
                    except (json.JSONDecodeError, TypeError):
                        pass

                if selected_type == 'weights' and selected_id == assessment['id']:
                    item_to_select = w_item

                # ── 🔁 Analysis v{n} (all versions, sorted) ───────────────
                all_tables = EMDSTreeModel._collect_analysis_items(
                    admin_manager, assessment
                )
                if not all_tables:
                    all_tables = assessment.get('output_tables', [])

                vis_cache = (
                    admin_manager.get_layer_visibility(assessment['id'])
                    if all_tables else {}
                )

                def _ver(t):
                    m = re.search(r'__v(\d+)$', t)
                    return int(m.group(1)) if m else 0

                for table_name in sorted(all_tables, key=_ver):
                    v_match   = re.search(r'__v(\d+)$', table_name)
                    v_num     = int(v_match.group(1)) if v_match else 1
                    scen_name = re.sub(r'__v\d+$', '', table_name)

                    an_item = QTreeWidgetItem(a_item)
                    an_item.setText(0, f"🔁 Analysis v{v_num}")
                    an_item.setData(0, ROLE_TYPE,          'analysis')
                    an_item.setData(0, ROLE_ID,            assessment['id'])
                    an_item.setData(0, ROLE_NAME,          f"Analysis v{v_num}")
                    an_item.setData(0, ROLE_OUTPUT_TABLES, [table_name])
                    an_item.setData(0, ROLE_SCENARIO_NAME, scen_name)
                    an_item.setFlags(
                        Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable
                    )
                    is_visible = vis_cache.get(table_name, True)
                    an_item.setCheckState(0, Qt.Checked if is_visible else Qt.Unchecked)

                    if selected_type == 'analysis' and selected_id == assessment['id']:
                        item_to_select = an_item

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
    def _get_base_layers(project, admin_manager):
        """Return base layer names for the given project via admin_manager.

        Delegates to admin_manager.get_base_layers_for_project() so that
        the UI layer never accesses the database directly.
        """
        return admin_manager.get_base_layers_for_project(project['id'])
