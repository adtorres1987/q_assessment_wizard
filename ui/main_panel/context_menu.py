# -*- coding: utf-8 -*-
"""
Right-click menu of the tree. Add new node actions here; their handlers
belong in catalog_actions.py or results_actions.py.

Mixin of AssessmentMainForm (ui/main_panel/panel.py): shares its widgets
and state through self and defines no __init__.
"""

from qgis.PyQt.QtWidgets import QMenu

from ..i18n.translator import tr
from ..panels import ROLE_TYPE


class ContextMenuMixin:
    """Right-click menu of the tree. Add new node actions here; their handlers"""

    # ------------------------------------------------------------------ #
    #  Context menu
    # ------------------------------------------------------------------ #

    def _on_context_menu(self, position):
        """Show right-click context menu based on node type."""
        item = self.tree.itemAt(position)
        menu = QMenu(self)

        if item is None:
            act = menu.addAction(tr('main.ctx_new_project'))
            act.triggered.connect(self._on_new_project)
        else:
            node_type = item.data(0, ROLE_TYPE) or ''
            if node_type == 'base_layers_group':
                lbl = menu.addAction(tr('main.ctx_base_layers_info'))
                lbl.setEnabled(False)
            elif node_type == 'project':
                act = menu.addAction(tr('main.ctx_new_assessment'))
                act.triggered.connect(self.on_create_assessment)
                act = menu.addAction(tr('main.ctx_compare'))
                act.triggered.connect(self._on_compare_outputs)
                menu.addSeparator()
                act = menu.addAction(tr('main.ctx_delete_project'))
                act.triggered.connect(lambda checked, i=item: self._on_delete_project(i))
            elif node_type == 'assessment':
                menu.addSeparator()
                act = menu.addAction(tr('main.ctx_delete_assessment'))
                act.triggered.connect(lambda checked, i=item: self._on_delete_assessment(i))
            elif node_type == 'weights':
                act = menu.addAction(tr('main.ctx_edit_weights'))
                act.triggered.connect(
                    lambda checked, i=item: self._on_edit_weights_from_tree(i)
                )
            elif node_type == 'analysis':
                act = menu.addAction(tr('main.ctx_view_results'))
                act.triggered.connect(lambda checked, i=item: self._on_view_results(i))
                act = menu.addAction(tr('main.ctx_portfolio'))
                act.triggered.connect(lambda checked, i=item: self._on_portfolio_wizard(i))
                menu.addSeparator()
                act = menu.addAction(tr('main.ctx_toggle_visibility'))
                act.triggered.connect(
                    lambda checked, i=item: self._on_toggle_analysis_visibility(i)
                )
            elif node_type == 'portfolio':
                act = menu.addAction(tr('main.ctx_delete_portfolio'))
                act.triggered.connect(lambda checked, i=item: self._on_delete_portfolio(i))

        menu.exec(self.tree.viewport().mapToGlobal(position))
