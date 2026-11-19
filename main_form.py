# -*- coding: utf-8 -*-
"""
Primary/Root form for the Assessment Wizard plugin.

EMDS Project Explorer — QDockWidget panel (like Layers/Browser).
The dock is created by assessment_wizard.py and persists for the session.

Tree structure:
  Project → [Base Layers | Assessments] → Assessment → Analyses → v1/v2/...

Action buttons (bottom panel):
  🗂 New Project · + New Assessment · ▶ Run Analysis · 📊 Compare Outputs

Analysis nodes open the Results Grid and the Portfolio Wizard from the context
menu; the language selector re-translates the panel at runtime.
"""

import os

from qgis.PyQt.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QTextEdit, QInputDialog, QMessageBox,
    QTreeWidget, QMenu, QFrame, QStackedWidget,
)
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.core import QgsProject, NULL

from .translator import tr, set_language, get_language, LANGUAGES

from .assessment_wizard_dialog import QassessmentWizardDialog
from .admin_manager import AdminManager
from .ui.dialogs import ResultsGridDialog, CompareHistogramDialog, PortfolioWizard
from .ui.panels import (
    AssessmentDetailPanel,
    AnalysisDetailPanel,
    EMDSTreeModel,
    ROLE_ID, ROLE_TYPE, ROLE_NAME,
    ROLE_OUTPUT_TABLES,
)


# ---------------------------------------------------------------------------
#  AssessmentMainForm
# ---------------------------------------------------------------------------

class AssessmentMainForm(QWidget):
    """Main form — EMDS Project Explorer (content widget for the dock panel)."""

    language_changed = pyqtSignal(str)   # emits the new language code

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

        # ── Language selector ────────────────────────────────────────────
        lang_row = QHBoxLayout()
        self._lbl_language = QLabel()
        lang_row.addWidget(self._lbl_language)
        self.language_combo = QComboBox()
        for code, label in LANGUAGES.items():
            self.language_combo.addItem(label, code)
        self.language_combo.setCurrentIndex(
            max(0, self.language_combo.findData(get_language()))
        )
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        lang_row.addWidget(self.language_combo, 1)
        layout.addLayout(lang_row)

        # ── Tree widget ──────────────────────────────────────────────────
        self.tree = QTreeWidget()
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self.tree.currentItemChanged.connect(self._on_tree_selection_changed)
        self.tree.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.tree, 1)

        # ── Contextual detail panel (stacked: assessment card | text area) ──
        self._detail_stack = QStackedWidget()
        self._detail_stack.setMaximumHeight(200)

        self._assessment_panel = AssessmentDetailPanel()
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
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep)

        # ── Action buttons (vertical stack) ──────────────────────────────
        self.btn_new_project = QPushButton()
        self.btn_new_project.clicked.connect(self._on_new_project)
        layout.addWidget(self.btn_new_project)

        self.btn_new_assessment = QPushButton()
        self.btn_new_assessment.setEnabled(False)
        self.btn_new_assessment.clicked.connect(self.on_create_assessment)
        layout.addWidget(self.btn_new_assessment)

        self.btn_run_analysis = QPushButton()
        self.btn_run_analysis.setEnabled(False)
        self.btn_run_analysis.clicked.connect(self._on_run_analysis)
        layout.addWidget(self.btn_run_analysis)

        self.btn_compare = QPushButton()
        self.btn_compare.setEnabled(False)
        self.btn_compare.clicked.connect(self._on_compare_outputs)
        layout.addWidget(self.btn_compare)

        self.retranslateUi()

        # Populate tree
        self._populate_tree()

    # ------------------------------------------------------------------ #
    #  i18n
    # ------------------------------------------------------------------ #

    def retranslateUi(self):
        """Re-apply every static text of the panel in the active language."""
        self._lbl_language.setText(tr('main.lbl_language'))
        self.tree.setHeaderLabels([tr('main.tree_header')])
        self.btn_new_project.setText(tr('main.btn_new_project'))
        self.btn_new_assessment.setText(tr('main.btn_new_assessment'))
        self.btn_run_analysis.setText(tr('main.btn_run_analysis'))
        self.btn_run_analysis.setToolTip(tr('main.btn_run_analysis_tip'))
        self.btn_compare.setText(tr('main.btn_compare'))
        self.btn_compare.setToolTip(tr('main.btn_compare_tip'))
        self._assessment_panel.retranslateUi()
        self._analysis_panel.retranslateUi()

    def _on_language_changed(self, _index):
        code = self.language_combo.currentData()
        if not code or code == get_language():
            return
        set_language(code)
        self.retranslateUi()
        self._populate_tree()          # node labels are translated
        current = self.tree.currentItem()
        if current:
            self._on_tree_selection_changed(current, None)
        self.language_changed.emit(code)

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
        node_type = current.data(0, ROLE_TYPE) if current else None

        self.btn_new_assessment.setEnabled(path['project_id'] is not None)
        self.btn_run_analysis.setEnabled(path['assessment_id'] is not None)
        self.btn_compare.setEnabled(path['project_id'] is not None)

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
        text = tr('main.details_project', name=project_name, count=len(assessments))
        self._detail_stack.setCurrentIndex(1)
        self.results_text_edit.setPlainText(text)

    def _show_portfolio_details(self, item):
        """Show the stored configuration of a portfolio (💼) node."""
        portfolio = self.admin_manager.get_portfolio(item.data(0, ROLE_ID))
        self._detail_stack.setCurrentIndex(1)
        if not portfolio:
            self.results_text_edit.clear()
            return
        cfg = portfolio['config']
        buckets = ", ".join(
            f"{b.get('name', '')} ($ {float(b.get('amount', 0)):,.2f})"
            for b in cfg.get('buckets', [])
        ) or tr('main.none')
        self.results_text_edit.setPlainText(tr(
            'main.details_portfolio',
            name=portfolio['name'],
            status=tr(f"tree.status_{portfolio['status']}"),
            table=portfolio['source_table'],
            benefits=cfg.get('col_benefits', ''),
            cost=cfg.get('col_cost', ''),
            priority=cfg.get('col_priority', ''),
            budget=f"{float(cfg.get('budget', 0)):,.2f}",
            buckets=buckets,
        ))

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
        if dlg.exec():
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

        checked = item.checkState(0) == Qt.CheckState.Checked
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
        name, ok = QInputDialog.getText(
            self, tr('main.new_project_title'), tr('main.new_project_label')
        )
        if ok and name.strip():
            try:
                self.admin_manager.create_project(name.strip())
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
            self.admin_manager.delete_project(project_id)
            self._populate_tree()
        elif ok:
            QMessageBox.warning(
                self, tr('main.delete_cancelled_title'),
                tr('main.delete_cancelled_body')
            )

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
            self.admin_manager.delete_assessment(assessment_id)
            self._populate_tree()

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
        new_state = Qt.CheckState.Unchecked if current_state == Qt.CheckState.Checked else Qt.CheckState.Checked
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
            QMessageBox.warning(self, tr('main.no_project_title'), tr('main.no_project_body'))
            return

        project_name = self._get_project_name(project_id)
        if not project_name:
            QMessageBox.warning(self, tr('main.err_title'), tr('main.err_project_name'))
            return

        dlg = QassessmentWizardDialog(
            parent=self,
            iface=self.iface,
            project_id=project_name,
            admin_manager=self.admin_manager,
            project_db_id=project_id
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

    def display_results(self, results):
        """Format and display the wizard results in the details area."""
        none = tr('main.none')
        text = tr(
            'main.results_text',
            name=results.get('assessment_name', ''),
            target=results.get('target_layer', ''),
            layers=", ".join(results.get("assessment_layers", [])) or none,
            tables="\n  - ".join(results.get("output_tables", [])) or none,
            description=results.get('description', ''),
        )
        self._detail_stack.setCurrentIndex(1)
        self.results_text_edit.setPlainText(text)

    # ------------------------------------------------------------------ #
    #  Results grid / comparison histogram / portfolio
    # ------------------------------------------------------------------ #

    def _project_item_of(self, item):
        node = item
        while node is not None and node.data(0, ROLE_TYPE) != 'project':
            node = node.parent()
        return node

    def _executor_for_item(self, item):
        """AssessmentExecutor for the project that contains *item* (or None)."""
        from .assessment_executor import AssessmentExecutor
        project_item = self._project_item_of(item)
        if project_item is None:
            return None
        project_id = project_item.data(0, ROLE_ID)
        return AssessmentExecutor(
            project_item.data(0, ROLE_NAME) or '', self.admin_manager, project_id
        )

    @staticmethod
    def _analysis_table(item):
        tables = item.data(0, ROLE_OUTPUT_TABLES) or []
        return tables[0] if tables else ''

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

    def _on_delete_portfolio(self, item):
        name = item.data(0, ROLE_NAME) or item.text(0)
        reply = QMessageBox.question(
            self, tr('main.delete_portfolio_title'),
            tr('main.delete_portfolio_body', name=name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.admin_manager.delete_portfolio(item.data(0, ROLE_ID))
            self._populate_tree()

    # ------------------------------------------------------------------ #
    #  Lifecycle
    # ------------------------------------------------------------------ #

    def showEvent(self, event):
        """Refresh tree every time the panel becomes visible."""
        if self.admin_manager.connection is None:
            self.admin_manager.connect()
        self._populate_tree()
        super().showEvent(event)
