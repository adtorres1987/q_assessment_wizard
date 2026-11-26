# -*- coding: utf-8 -*-
"""
EMDS Project Explorer — content widget of the plugin's QDockWidget.

Tree structure:
  Project → [Base Layers | Assessments] → Assessment → Analyses → v1/v2/...

Action buttons (bottom panel):
  🗂 New Project · + New Assessment · ▶ Run Analysis · 📊 Compare Outputs

This module builds the layout, re-translates it and refreshes on show. The
behaviour lives in one mixin module per responsibility (same pattern as the
wizard):

  tree_view.py        tree population, selection, button state, visibility checkbox
  detail_views.py     contextual detail area (cards/text per node type)
  context_menu.py     right-click menu
  catalog_actions.py  projects, assessments, versions, weights/MCDA, portfolios
  results_actions.py  results grid, comparison histogram, portfolio wizard

Mixins precede QWidget in the bases and define no __init__.
"""


from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QTextEdit, QTreeWidget, QFrame, QStackedWidget,
)
from qgis.PyQt.QtCore import Qt, pyqtSignal

from ..i18n.translator import tr, set_language, get_language, LANGUAGES
from ..panels import AssessmentDetailPanel, AnalysisDetailPanel

from .tree_view import TreeViewMixin
from .detail_views import DetailViewsMixin
from .context_menu import ContextMenuMixin
from .catalog_actions import CatalogActionsMixin
from .results_actions import ResultsActionsMixin


class AssessmentMainForm(TreeViewMixin, DetailViewsMixin, ContextMenuMixin,
                         CatalogActionsMixin, ResultsActionsMixin, QWidget):
    """Main form — EMDS Project Explorer (content widget for the dock panel)."""

    language_changed = pyqtSignal(str)   # emits the new language code

    # ------------------------------------------------------------------ #
    #  Construction
    # ------------------------------------------------------------------ #

    def __init__(self, iface, facade, parent=None):
        """
        Args:
            iface:  QgisInterface.
            facade: ExplorerFacade — the panel's only access to the application.
        """
        super().__init__(parent)
        self.iface = iface
        self.facade = facade
        self.selected_path = {
            "project_id": None,
            "assessment_id": None,
        }

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

        self._analysis_panel = AnalysisDetailPanel(self.facade)
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
    #  Lifecycle
    # ------------------------------------------------------------------ #

    def showEvent(self, event):
        """Refresh tree every time the panel becomes visible."""
        self._populate_tree()
        super().showEvent(event)
