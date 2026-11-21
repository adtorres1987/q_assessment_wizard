# -*- coding: utf-8 -*-
"""WeightsEditDialog + AnalysisDetailPanel — MCDA analysis panels."""

from qgis.PyQt.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QDoubleSpinBox, QFrame, QMessageBox,
)
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtGui import QFont

from ..i18n.translator import tr


class WeightsEditDialog(QDialog):
    """Modal dialog for editing per-layer MCDA weights.

    Shows each assessment input layer with a QDoubleSpinBox (0–100 %).
    Validates that weights sum to 100 % before saving to admin.sqlite.
    """

    def __init__(self, assessment_id, facade, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('panels.weights_dlg_title'))
        self.assessment_id  = assessment_id
        self._facade        = facade
        self._spinboxes     = {}   # layer_name → QDoubleSpinBox

        layout = QVBoxLayout(self)

        config      = facade.weights_config(assessment_id)
        weights     = config['weights']
        layer_names = config['layer_names']

        layout.addWidget(QLabel(tr('panels.weights_dlg_intro')))

        form = QGridLayout()
        n = len(layer_names) or 1
        for row, name in enumerate(layer_names):
            lbl  = QLabel(name)
            spin = QDoubleSpinBox()
            spin.setRange(0, 100)
            spin.setSuffix(" %")
            spin.setDecimals(1)
            spin.setValue(round(weights.get(name, 1.0 / n) * 100, 1))
            self._spinboxes[name] = spin
            form.addWidget(lbl,  row, 0)
            form.addWidget(spin, row, 1)
        layout.addLayout(form)

        self._lbl_total = QLabel()
        layout.addWidget(self._lbl_total)
        for spin in self._spinboxes.values():
            spin.valueChanged.connect(self._update_total)
        self._update_total()

        btn_row    = QHBoxLayout()
        btn_save   = QPushButton(tr('panels.btn_save'))
        btn_save.clicked.connect(self._on_save)
        btn_cancel = QPushButton(tr('panels.btn_cancel'))
        btn_cancel.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(btn_save)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

    def _update_total(self):
        total = sum(s.value() for s in self._spinboxes.values())
        color = "green" if abs(total - 100) < 0.1 else "red"
        text = tr('panels.weights_total', total=f"{total:.1f}")
        self._lbl_total.setText(f'<span style="color:{color}">{text}</span>')

    def _on_save(self):
        total = sum(s.value() for s in self._spinboxes.values())
        if abs(total - 100) > 0.5:
            QMessageBox.warning(
                self, tr('panels.invalid_weights_title'),
                tr('panels.invalid_weights_body', total=f"{total:.1f}")
            )
            return
        weights = {name: round(s.value() / 100, 4)
                   for name, s in self._spinboxes.items()}
        try:
            self._facade.update_weights(self.assessment_id, weights)
        except ValueError as e:   # business rule enforced by UpdateWeights
            QMessageBox.warning(self, tr('panels.invalid_weights_title'), str(e))
            return
        self.accept()


class AnalysisDetailPanel(QWidget):
    """Structured detail card shown when an analysis node is selected.

    Displays:
        Analysis name (Model_v{n}) · Model type · Weights per layer
        Score column name · [ Edit Weights ] and [ Run Again ] buttons

    Emits:
        run_again_clicked(assessment_id, table_name)
    """

    run_again_clicked = pyqtSignal(int, str)   # assessment_id, table_name

    def __init__(self, facade, parent=None):
        super().__init__(parent)
        self._facade = facade
        self._assessment_id = None
        self._table_name    = None
        self._model_name    = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(3)

        bold    = QFont(); bold.setBold(True)
        sm_bold = QFont(); sm_bold.setBold(True)

        # Title
        self._lbl_title = QLabel("—")
        self._lbl_title.setFont(bold)
        layout.addWidget(self._lbl_title)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep1)

        # Output table row
        tbl_row = QHBoxLayout()
        self._lbl_tbl_h = QLabel()
        self._lbl_tbl_h.setFont(sm_bold)
        tbl_row.addWidget(self._lbl_tbl_h)
        self._lbl_table = QLabel("—")
        self._lbl_table.setWordWrap(True)
        tbl_row.addWidget(self._lbl_table)
        tbl_row.addStretch()
        layout.addLayout(tbl_row)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep2)

        # Weights (read-only)
        self._lbl_w_h = QLabel()
        self._lbl_w_h.setFont(sm_bold)
        layout.addWidget(self._lbl_w_h)
        self._lbl_weights = QLabel("—")
        self._lbl_weights.setWordWrap(True)
        self._lbl_weights.setContentsMargins(10, 0, 0, 0)
        layout.addWidget(self._lbl_weights)

        sep3 = QFrame()
        sep3.setFrameShape(QFrame.Shape.HLine)
        sep3.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep3)

        # Run Again button
        self._btn_run = QPushButton()
        self._btn_run.clicked.connect(self._on_run_again)
        layout.addWidget(self._btn_run)

        self.retranslateUi()

    def retranslateUi(self):
        """Re-apply static texts (and reload the current node) in the active language."""
        self._lbl_tbl_h.setText(tr('panels.output'))
        self._lbl_w_h.setText(tr('panels.weights_used'))
        self._btn_run.setText(tr('panels.btn_run_again'))
        if self._assessment_id is not None:
            self.load(self._assessment_id, self._table_name, self._model_name)

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def load(self, assessment_id, table_name, model_name):
        """Populate the panel with data for the given analysis node.

        Args:
            assessment_id: int
            table_name:    str — the specific versioned overlay table name
            model_name:    str — display name (e.g. "Analysis v2")
        """
        self._assessment_id = assessment_id
        self._table_name    = table_name
        self._model_name    = model_name
        self._lbl_title.setText(f"🔁 {model_name}")
        self._lbl_table.setText(table_name or "—")

        # GetAnalysisWeights prefers the snapshot tied to this output table and
        # falls back to the current config; None means there is no config at all.
        weights = self._facade.analysis_weights(assessment_id, table_name)

        if weights is not None:
            if weights:
                self._lbl_weights.setText(
                    "\n".join(f"  {name}: {round(w * 100, 1)}%"
                              for name, w in weights.items())
                )
            else:
                self._lbl_weights.setText(f"  {tr('panels.no_weights')}")
        else:
            self._lbl_weights.setText(f"  {tr('panels.no_config')}")

    def clear(self):
        """Reset to empty/default state."""
        self._assessment_id = None
        self._table_name    = None
        self._model_name    = None
        self._lbl_title.setText("—")
        self._lbl_table.setText("—")
        self._lbl_weights.setText("—")

    # ------------------------------------------------------------------ #
    #  Private handlers
    # ------------------------------------------------------------------ #

    def _on_run_again(self):
        if self._assessment_id is not None and self._table_name:
            self.run_again_clicked.emit(self._assessment_id, self._table_name)
