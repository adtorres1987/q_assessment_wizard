# -*- coding: utf-8 -*-
"""VersionHistoryPanel — Git-like timeline widget for spatial scenario versions."""

from qgis.PyQt.QtWidgets import (
    QGroupBox, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QHBoxLayout, QVBoxLayout,
)
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QFont


class VersionHistoryPanel(QGroupBox):
    """Displays the immutable version chain for a selected spatial scenario.

    Shows each overlay snapshot as a list entry with:
      ★ HEAD marker on the current (active) version
      table name and creation timestamp
      "Rollback" and "Compare vs HEAD" action buttons

    Emits:
        rollback_requested(scenario_name, version_id)
        compare_requested(scenario_name, version_id_a, version_id_b)
    """

    rollback_requested = pyqtSignal(str, int)      # scenario_name, version_id
    compare_requested  = pyqtSignal(str, int, int)  # scenario_name, vid_a, vid_b

    def __init__(self, parent=None):
        super().__init__("Version History", parent)
        self._scenario_name   = None
        self._head_version_id = None

        layout = QVBoxLayout(self)

        self._placeholder = QLabel("Select an analysis node to view version history.")
        self._placeholder.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._placeholder)

        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SingleSelection)
        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._list)
        self._list.hide()

        btn_layout = QHBoxLayout()

        self._btn_rollback = QPushButton("\u21ba Rollback to selected")
        self._btn_rollback.setEnabled(False)
        self._btn_rollback.setToolTip(
            "Move HEAD to the selected version — O(1), no spatial recalculation."
        )
        self._btn_rollback.clicked.connect(self._on_rollback)
        btn_layout.addWidget(self._btn_rollback)

        self._btn_compare = QPushButton("\u21c4 Compare with HEAD")
        self._btn_compare.setEnabled(False)
        self._btn_compare.setToolTip(
            "Load the selected version and HEAD as separate QGIS layers for visual comparison."
        )
        self._btn_compare.clicked.connect(self._on_compare)
        btn_layout.addWidget(self._btn_compare)

        layout.addLayout(btn_layout)

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def load_versions(self, scenario_name, db_path):
        """Populate the list from SpatiaLite spatial_versions.

        Args:
            scenario_name: str — base name without __v{n} suffix
            db_path:       str — absolute path to the project SpatiaLite file
        """
        self._scenario_name   = scenario_name
        self._head_version_id = None
        self._list.clear()

        try:
            from ...core.spatial_engine import SpatialEngine
            with SpatialEngine(db_path) as engine:
                versions = engine.get_versions(scenario_name)
        except Exception as e:
            self._show_placeholder(f"Could not load versions: {e}")
            return

        if not versions:
            self._show_placeholder("No versions found for this scenario.")
            return

        self._placeholder.hide()
        self._list.show()

        bold_font = QFont()
        bold_font.setBold(True)

        for v in versions:
            is_head = bool(v.get('is_current'))
            if is_head:
                self._head_version_id = v['id']

            timestamp = (v.get('created_at') or '')[:19]
            head_mark = '\u2605 HEAD  ' if is_head else '         '
            label = (
                f"{head_mark}"
                f"  v{v['id']}"
                f"  \u2502  {v.get('table_name', '')}"
                f"  \u2502  {timestamp}"
            )

            item = QListWidgetItem(label)
            item.setData(Qt.UserRole,     v['id'])
            item.setData(Qt.UserRole + 1, is_head)
            if is_head:
                item.setFont(bold_font)
            self._list.addItem(item)

    def clear_panel(self):
        """Reset to empty state (no selection)."""
        self._scenario_name   = None
        self._head_version_id = None
        self._list.clear()
        self._list.hide()
        self._show_placeholder("Select an analysis node to view version history.")
        self._btn_rollback.setEnabled(False)
        self._btn_compare.setEnabled(False)

    # ------------------------------------------------------------------ #
    #  Private helpers
    # ------------------------------------------------------------------ #

    def _show_placeholder(self, text):
        self._placeholder.setText(text)
        self._placeholder.show()
        self._list.hide()

    def _on_selection_changed(self):
        selected = self._list.selectedItems()
        if not selected:
            self._btn_rollback.setEnabled(False)
            self._btn_compare.setEnabled(False)
            return

        item = selected[0]
        is_head = item.data(Qt.UserRole + 1)
        self._btn_rollback.setEnabled(not is_head)
        self._btn_compare.setEnabled(
            not is_head and self._head_version_id is not None
        )

    def _on_rollback(self):
        selected = self._list.selectedItems()
        if not selected or not self._scenario_name:
            return
        version_id = selected[0].data(Qt.UserRole)
        self.rollback_requested.emit(self._scenario_name, version_id)

    def _on_compare(self):
        selected = self._list.selectedItems()
        if not selected or not self._scenario_name or self._head_version_id is None:
            return
        version_id = selected[0].data(Qt.UserRole)
        self.compare_requested.emit(self._scenario_name, version_id, self._head_version_id)
