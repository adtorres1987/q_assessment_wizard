# -*- coding: utf-8 -*-
"""
Actions that create, delete or re-run things: projects, assessments
(wizard and new versions), portfolios, MCDA weights and scoring.

Mixin of AssessmentMainForm (ui/main_panel/panel.py): shares its widgets
and state through self and defines no __init__.
"""

from qgis.PyQt.QtWidgets import QDialog, QInputDialog, QMessageBox

from ..i18n.translator import tr
from ..wizard.assessment_wizard_dialog import QassessmentWizardDialog
from ..panels import ROLE_ID, ROLE_TYPE, ROLE_NAME


class CatalogActionsMixin:
    """Actions that create, delete or re-run things: projects, assessments"""

    # ------------------------------------------------------------------ #
    #  Projects
    # ------------------------------------------------------------------ #

    def _on_new_project(self):
        """Create a new project via QInputDialog."""
        name, ok = QInputDialog.getText(
            self, tr('main.new_project_title'), tr('main.new_project_label')
        )
        if ok and name.strip():
            try:
                self.facade.create_project(name.strip())
                self._populate_tree()
            except Exception as e:
                QMessageBox.warning(self, tr('main.err_title'),
                                    tr('main.err_create_project', error=str(e)))

    def _on_delete_project(self, item):
        """Delete a project — requires typing the project name to confirm."""
        project_name = item.data(0, ROLE_NAME) or item.text(0)
        project_id = item.data(0, ROLE_ID)

        typed, ok = QInputDialog.getText(
            self, tr('main.delete_project_title'),
            tr('main.delete_project_body', name=project_name)
        )
        if ok and typed.strip() == project_name:
            self.facade.delete_project(project_id)
            self._populate_tree()
        elif ok:
            QMessageBox.warning(
                self, tr('main.delete_cancelled_title'),
                tr('main.delete_cancelled_body')
            )

    # ------------------------------------------------------------------ #
    #  Assessments
    # ------------------------------------------------------------------ #

    def on_create_assessment(self):
        """Launch the assessment wizard dialog and display results."""
        project_id = self.selected_path["project_id"]
        if project_id is None:
            QMessageBox.warning(self, tr('main.no_project_title'), tr('main.no_project_body'))
            return

        project_name = self._get_project_name(project_id)
        if not project_name:
            QMessageBox.warning(self, tr('main.err_title'), tr('main.err_project_name'))
            return

        dlg = QassessmentWizardDialog(
            parent=self,
            iface=self.iface,
            executor=self.facade.executor_for(project_id, project_name),
        )
        result = dlg.exec()

        if result == QDialog.DialogCode.Accepted:
            results = dlg.get_results()
            if results:
                self.display_results(results)
            self._populate_tree()
        else:
            self._detail_stack.setCurrentIndex(1)
            self.results_text_edit.setPlainText(tr('main.assessment_cancelled'))

    def _on_delete_assessment(self, item):
        """Delete an assessment after confirmation."""
        assessment_name = item.data(0, ROLE_NAME) or item.text(0)
        assessment_id = item.data(0, ROLE_ID)
        reply = QMessageBox.question(
            self, tr('main.delete_assessment_title'),
            tr('main.delete_assessment_body', name=assessment_name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.facade.delete_assessment(assessment_id)
            self._populate_tree()

    def _on_run_analysis(self):
        """Re-run spatial overlay for the selected assessment (new version)."""
        node = self.tree.currentItem()
        while node:
            if node.data(0, ROLE_TYPE) == 'assessment':
                self._on_new_version(node)
                return
            node = node.parent()

    def _on_new_version(self, item):
        """Re-run spatial overlay for this assessment, creating a new version."""
        assessment_id = item.data(0, ROLE_ID)
        project_id = self.selected_path.get('project_id')
        if not project_id:
            return

        assessment_name = item.data(0, ROLE_NAME) or item.text(0)
        input_layers = self.facade.assessment_details(assessment_id)['input_layers']
        if not input_layers:
            QMessageBox.warning(
                self, tr('main.not_supported_title'),
                tr('main.simple_no_versioning', name=assessment_name)
            )
            return

        reply = QMessageBox.question(
            self, tr('main.new_version_title'),
            tr('main.new_version_body', name=assessment_name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        executor = self.facade.executor_for(project_id, self._get_project_name(project_id))
        result = executor.rerun_spatial_assessment(assessment_id, parent_widget=self)

        if result:
            self._populate_tree()

    # ------------------------------------------------------------------ #
    #  MCDA weights and scoring
    # ------------------------------------------------------------------ #

    def _on_edit_weights(self, assessment_id):
        """Open WeightsEditDialog for the given assessment."""
        from ..panels.analysis_detail_panel import WeightsEditDialog
        dlg = WeightsEditDialog(assessment_id, self.facade, parent=self)
        if dlg.exec():
            self._populate_tree()
            current = self.tree.currentItem()
            if current:
                self._show_assessment_details(current)

    def _on_edit_weights_from_tree(self, item):
        """Open the weights editor for the assessment linked to this weights node."""
        assessment_id = item.data(0, ROLE_ID)
        if assessment_id is not None:
            self._analysis_panel.load(assessment_id, '', '')
            self._analysis_panel._on_edit_weights()

    def _on_run_mcda(self, assessment_id, table_name):
        """Handle run_again_clicked signal from AnalysisDetailPanel."""
        project_id = self.selected_path.get('project_id')
        if not project_id:
            return
        executor = self.facade.executor_for(project_id, self._get_project_name(project_id))
        executor.apply_mcda_score(assessment_id, table_name, parent_widget=self)

    # ------------------------------------------------------------------ #
    #  Portfolios
    # ------------------------------------------------------------------ #

    def _on_delete_portfolio(self, item):
        name = item.data(0, ROLE_NAME) or item.text(0)
        reply = QMessageBox.question(
            self, tr('main.delete_portfolio_title'),
            tr('main.delete_portfolio_body', name=name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.facade.delete_portfolio(item.data(0, ROLE_ID))
            self._populate_tree()
