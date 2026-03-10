# -*- coding: utf-8 -*-
"""AssessmentDetailPanel — contextual card for assessment nodes."""

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QFrame, QPushButton,
)
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QFont
from qgis.core import QgsProject


class AssessmentDetailPanel(QWidget):
    """Structured detail card shown when an assessment node is selected.

    Displays:
        Assessment name · Target layer · Created date · Feature count
        Weights per layer · [ ✏ Edit Weights ] button
    """

    weights_edit_clicked = pyqtSignal(int)   # emits assessment_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._assessment_id = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(3)

        bold = QFont()
        bold.setBold(True)
        sm_bold = QFont()
        sm_bold.setBold(True)

        # — Assessment title
        self._lbl_title = QLabel("—")
        self._lbl_title.setFont(bold)
        layout.addWidget(self._lbl_title)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.HLine)
        sep1.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep1)

        # — Target layer row
        tgt_row = QHBoxLayout()
        lbl_tgt_h = QLabel("Target:")
        lbl_tgt_h.setFont(sm_bold)
        tgt_row.addWidget(lbl_tgt_h)
        self._lbl_target = QLabel("—")
        tgt_row.addWidget(self._lbl_target)
        tgt_row.addStretch()
        layout.addLayout(tgt_row)

        # — Created / Records row
        meta_row = QHBoxLayout()
        self._lbl_created = QLabel("Created: —")
        self._lbl_records = QLabel("Records: —")
        meta_row.addWidget(self._lbl_created)
        meta_row.addStretch()
        meta_row.addWidget(self._lbl_records)
        layout.addLayout(meta_row)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep2)

        # — Weights block
        w_header_row = QHBoxLayout()
        lbl_w_h = QLabel("⚙ Weights:")
        lbl_w_h.setFont(sm_bold)
        w_header_row.addWidget(lbl_w_h)
        w_header_row.addStretch()
        self._btn_edit_weights = QPushButton("✏ Edit")
        self._btn_edit_weights.setFixedWidth(60)
        self._btn_edit_weights.clicked.connect(self._on_edit_weights)
        w_header_row.addWidget(self._btn_edit_weights)
        layout.addLayout(w_header_row)

        self._lbl_weights = QLabel("—")
        self._lbl_weights.setWordWrap(True)
        self._lbl_weights.setContentsMargins(10, 0, 0, 0)
        layout.addWidget(self._lbl_weights)

    def show_assessment(self, name, input_layers, target_layer, created_at,
                        assessment_id=None, weights=None):
        """Populate the card with assessment data."""
        self._assessment_id = assessment_id
        self._lbl_title.setText(f"📁 {name}")
        self._lbl_target.setText(target_layer or "—")

        date_str = (created_at or '')[:10] or '—'
        self._lbl_created.setText(f"Created: {date_str}")

        records_str = "—"
        if target_layer:
            layers = QgsProject.instance().mapLayersByName(target_layer)
            if layers:
                records_str = f"{layers[0].featureCount():,}"
        self._lbl_records.setText(f"Records: {records_str}")

        if weights:
            self._lbl_weights.setText(
                "\n".join(f"  {layer}: {w * 100:.0f}%" for layer, w in weights.items())
            )
        else:
            self._lbl_weights.setText("(no weights configured)")

        self._btn_edit_weights.setEnabled(assessment_id is not None)

    def _on_edit_weights(self):
        if self._assessment_id is not None:
            self.weights_edit_clicked.emit(self._assessment_id)

    def clear(self):
        """Reset to empty/default state."""
        self._assessment_id = None
        self._lbl_title.setText("—")
        self._lbl_target.setText("—")
        self._lbl_created.setText("Created: —")
        self._lbl_records.setText("Records: —")
        self._lbl_weights.setText("—")
