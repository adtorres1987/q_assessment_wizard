# -*- coding: utf-8 -*-
"""
Result viewers launched from the tree: results grid, comparison
histogram and portfolio wizard. Simple (memory) assessments are not in
SpatiaLite, so these fall back to the loaded QGIS layer's attributes.

Mixin of AssessmentMainForm (ui/main_panel/panel.py): shares its widgets
and state through self and defines no __init__.
"""

from qgis.PyQt.QtWidgets import QDialog, QMessageBox
from qgis.core import QgsProject, NULL

from ..i18n.translator import tr
from ..dialogs import ResultsGridDialog, CompareHistogramDialog, PortfolioWizard
from ..panels import ROLE_ID, ROLE_TYPE, ROLE_NAME


class ResultsActionsMixin:
    """Result viewers launched from the tree: results grid, comparison"""

    # ------------------------------------------------------------------ #
    #  Results grid
    # ------------------------------------------------------------------ #

    def _on_view_results(self, item):
        """Open the Results Grid for an analysis (🔁) node."""
        table = self._analysis_table(item)
        executor = self._executor_for_item(item)
        if not table or executor is None:
            return
        try:
            data = executor.get_results_grid(table)
            rows, columns = data['rows'], data['columns']
        except LookupError:
            # Simple (memory) assessments are not stored in SpatiaLite:
            # show the attributes of the loaded QGIS layer instead.
            layers = QgsProject.instance().mapLayersByName(table)
            if not layers:
                QMessageBox.warning(self, tr('main.grid_title'),
                                    tr('main.result_not_found', table=table))
                return
            layer = layers[0]
            columns = [f.name() for f in layer.fields()]
            rows = [tuple(None if feat[c] == NULL else feat[c] for c in columns)
                    for feat in layer.getFeatures()]
        except (ValueError, RuntimeError) as e:
            QMessageBox.warning(self, tr('main.grid_title'),
                                tr('main.grid_error', table=table, error=str(e)))
            return
        ResultsGridDialog(table, rows, columns, parent=self).exec()

    # ------------------------------------------------------------------ #
    #  Comparison histogram
    # ------------------------------------------------------------------ #

    def _collect_project_results(self, project_item):
        """[{'label', 'table'}] for every analysis node under *project_item*."""
        results = []
        for i in range(project_item.childCount()):
            a_item = project_item.child(i)
            if a_item.data(0, ROLE_TYPE) != 'assessment':
                continue
            a_name = a_item.data(0, ROLE_NAME) or a_item.text(0)
            for j in range(a_item.childCount()):
                child = a_item.child(j)
                if child.data(0, ROLE_TYPE) == 'analysis':
                    table = self._analysis_table(child)
                    if table:
                        label = f"{a_name} · {child.data(0, ROLE_NAME)}"
                        results.append({'label': label, 'table': table})
        return results

    def _on_compare_outputs(self):
        """Open the paired histogram for the selected project's results."""
        current = self.tree.currentItem()
        project_item = self._project_item_of(current) if current else None
        if project_item is None:
            QMessageBox.warning(self, tr('main.no_project_title'), tr('main.no_project_body'))
            return
        executor = self._executor_for_item(project_item)

        # Keep only results stored in SpatiaLite as overlay tables.
        results = []
        for r in self._collect_project_results(project_item):
            try:
                executor.get_result_columns(r['table'])
                results.append(r)
            except (LookupError, ValueError, RuntimeError):
                continue
        if len(results) < 2:
            QMessageBox.information(self, tr('main.compare_title'),
                                    tr('main.compare_not_enough'))
            return
        CompareHistogramDialog(
            results, executor.get_comparison_series, parent=self
        ).exec()

    # ------------------------------------------------------------------ #
    #  Portfolio wizard
    # ------------------------------------------------------------------ #

    def _on_portfolio_wizard(self, item):
        """Configure a Portfolio (LPA) on top of an analysis result."""
        table = self._analysis_table(item)
        executor = self._executor_for_item(item)
        assessment_id = item.data(0, ROLE_ID)
        if not table or executor is None or assessment_id is None:
            return
        try:
            columns = [c for c in executor.get_result_columns(table)
                       if c.lower() not in ('id', 'ogc_fid', 'fid')]
        except LookupError:
            layers = QgsProject.instance().mapLayersByName(table)
            columns = [f.name() for f in layers[0].fields()] if layers else []
        except (ValueError, RuntimeError) as e:
            QMessageBox.warning(self, tr('main.portfolio_title'),
                                tr('main.grid_error', table=table, error=str(e)))
            return
        if len(columns) < 3:
            QMessageBox.warning(self, tr('main.portfolio_title'),
                                tr('main.portfolio_no_columns', table=table))
            return

        wiz = PortfolioWizard(columns=columns, parent=self)
        if wiz.exec() != QDialog.DialogCode.Accepted:
            return
        result = executor.create_portfolio(assessment_id, table, wiz.get_config(),
                                           parent_widget=self)
        if not result:
            return
        cfg = result['config']
        self._populate_tree()
        QMessageBox.information(
            self, tr('main.portfolio_saved_title'),
            tr('main.portfolio_saved_body', name=result['name'],
               benefits=cfg['col_benefits'], cost=cfg['col_cost'],
               priority=cfg['col_priority'], budget=f"{cfg['budget']:,.2f}"),
        )
