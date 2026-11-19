# -*- coding: utf-8 -*-
"""
ResultsGridDialog — interactive results table with a side bar chart.

Ported from plugin_wizard (results_grid_dialog.py) and adapted to Qt 6:
filter / group / sort the rows, chart the distribution of one column as %,
and export to Excel (CSV when openpyxl is not installed) or PDF.

The dialog is data-only: the caller passes ``rows`` and ``columns``.
"""

import html
import importlib.util
import os
import tempfile

from qgis.PyQt.QtCore import Qt, QSortFilterProxyModel, QUrl
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableView, QLineEdit,
    QLabel, QComboBox, QPushButton, QHeaderView, QAbstractItemView,
    QFrame, QSplitter, QSizePolicy, QWidget, QFileDialog, QMessageBox,
)
from qgis.PyQt.QtGui import (
    QStandardItemModel, QStandardItem, QColor, QFont, QTextDocument, QImage,
    QPageSize, QPageLayout,
)

try:
    from qgis.PyQt.QtPrintSupport import QPrinter
    HAS_PRINT = True
except ImportError:
    HAS_PRINT = False

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.figure import Figure
    HAS_MPL = True
except Exception:  # ImportError, or no usable Qt binding
    HAS_MPL = False

from ...translator import tr

_BINS = 8  # bins used for numeric columns in the chart
_SORT_ROLE = Qt.ItemDataRole.UserRole
_GROUP_HEADER_ROLE = Qt.ItemDataRole.UserRole + 1

_DEFAULT_WIDTHS = {
    "input_id": 70, "fragments": 80, "total_area": 110,
    "intersect_area": 110, "no_overlap_area": 120,
    "coverage_pct": 100, "coverage_class": 130, "mcda_score": 100,
}


class _NumericSortProxy(QSortFilterProxyModel):
    """Proxy that compares the raw values so numbers sort numerically."""

    def lessThan(self, left, right):
        l_val = self.sourceModel().data(left, _SORT_ROLE)
        r_val = self.sourceModel().data(right, _SORT_ROLE)
        try:
            return l_val < r_val
        except TypeError:
            return str(l_val or "") < str(r_val or "")


class ResultsGridDialog(QDialog):
    """Results grid + distribution chart.

    Args:
        layer_name: str — shown in the title and used for export file names.
        rows:       list[tuple]
        columns:    list[str]
    """

    def __init__(self, layer_name, rows, columns, parent=None):
        super().__init__(parent)
        self.layer_name = layer_name
        self.all_rows = list(rows)
        self.columns = list(columns)
        self.proxy = None
        self._setup_ui()
        self._populate(self.all_rows, "None")

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    @staticmethod
    def _vline():
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        return sep

    def _setup_ui(self):
        self.setWindowTitle(tr('results_grid.window_title', name=self.layer_name))
        self.setMinimumSize(1050, 580)
        self.resize(1300, 700)

        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(10, 10, 10, 10)

        # ── Controls bar ──────────────────────────────────────────────
        ctrl = QHBoxLayout()
        ctrl.setSpacing(6)

        ctrl.addWidget(QLabel(tr('results_grid.lbl_filter')))
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText(tr('results_grid.placeholder_filter'))
        self.filter_input.setClearButtonEnabled(True)
        self.filter_input.textChanged.connect(self._apply_filter)
        ctrl.addWidget(self.filter_input, 2)

        ctrl.addWidget(QLabel(tr('results_grid.lbl_in_col')))
        self.col_combo = QComboBox()
        self.col_combo.addItem(tr('results_grid.combo_all_cols'), -1)
        for i, col in enumerate(self.columns):
            self.col_combo.addItem(col, i)
        self.col_combo.currentIndexChanged.connect(self._apply_filter)
        ctrl.addWidget(self.col_combo, 1)

        ctrl.addWidget(self._vline())

        ctrl.addWidget(QLabel(tr('results_grid.lbl_group_by')))
        self.group_combo = QComboBox()
        self.group_combo.addItem(tr('results_grid.combo_none'), "None")
        for col in self._groupable_columns():
            self.group_combo.addItem(col, col)
        self.group_combo.currentIndexChanged.connect(self._on_group_changed)
        ctrl.addWidget(self.group_combo, 1)

        ctrl.addWidget(self._vline())

        ctrl.addWidget(QLabel(tr('results_grid.lbl_chart_col')))
        self.chart_col_combo = QComboBox()
        for col in self._chartable_columns():
            self.chart_col_combo.addItem(col, col)
        self.chart_col_combo.currentIndexChanged.connect(self._update_chart)
        ctrl.addWidget(self.chart_col_combo, 1)

        root.addLayout(ctrl)

        # ── Splitter: table (left) + chart (right) ────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.table_view = QTableView()
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hdr = self.table_view.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hdr.setStretchLastSection(True)
        hdr.setMinimumSectionSize(60)
        self.table_view.verticalHeader().setDefaultSectionSize(22)
        self.table_view.setSortingEnabled(True)
        splitter.addWidget(self.table_view)

        chart_panel = QWidget()
        chart_layout = QVBoxLayout(chart_panel)
        chart_layout.setContentsMargins(4, 0, 0, 0)
        chart_layout.setSpacing(4)
        if HAS_MPL:
            self.figure = Figure(tight_layout=True)
            self.canvas = FigureCanvas(self.figure)
            self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding,
                                      QSizePolicy.Policy.Expanding)
            chart_layout.addWidget(self.canvas)
        else:
            chart_layout.addWidget(QLabel(tr('results_grid.no_matplotlib')))
        splitter.addWidget(chart_panel)
        splitter.setStretchFactor(0, 6)
        splitter.setStretchFactor(1, 4)
        total = self.width() or 1300
        splitter.setSizes([int(total * 0.60), int(total * 0.40)])
        root.addWidget(splitter, 1)

        # ── Status + buttons ──────────────────────────────────────────
        self.status_label = QLabel()
        self.status_label.setStyleSheet("color: grey; font-size: 11px;")
        root.addWidget(self.status_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        excel_btn = QPushButton(tr('results_grid.btn_export_excel'))
        excel_btn.clicked.connect(self._export_excel)
        btn_row.addWidget(excel_btn)
        pdf_btn = QPushButton(tr('results_grid.btn_export_pdf'))
        pdf_btn.setEnabled(HAS_PRINT)
        pdf_btn.clicked.connect(self._export_pdf)
        btn_row.addWidget(pdf_btn)
        close_btn = QPushButton(tr('results_grid.btn_close'))
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Data helpers
    # ------------------------------------------------------------------

    def _groupable_columns(self):
        """Text columns (first non-null value is a string)."""
        result = []
        for idx, col in enumerate(self.columns):
            for row in self.all_rows:
                val = row[idx]
                if val is None:
                    continue
                if isinstance(val, str):
                    result.append(col)
                break
        return result

    def _chartable_columns(self):
        """Columns with at least one value repeated 2+ times."""
        result = []
        for idx, col in enumerate(self.columns):
            seen = {}
            for row in self.all_rows:
                val = row[idx]
                if val is None:
                    continue
                seen[val] = seen.get(val, 0) + 1
                if seen[val] >= 2:
                    result.append(col)
                    break
        return result

    def _col_values(self, col_name):
        idx = self.columns.index(col_name)
        return [r[idx] for r in self.all_rows if r[idx] is not None]

    # ------------------------------------------------------------------
    # Table population
    # ------------------------------------------------------------------

    def _populate(self, rows, group_by):
        grouped = group_by != "None" and group_by in self.columns
        model = QStandardItemModel()
        model.setHorizontalHeaderLabels(self.columns)

        if grouped:
            g_idx = self.columns.index(group_by)
            groups = {}
            for row in rows:
                gkey = row[g_idx] if row[g_idx] is not None else "NULL"
                groups.setdefault(gkey, []).append(row)

            bold = QFont()
            bold.setBold(True)
            for gkey in sorted(groups, key=str):
                grp_rows = groups[gkey]
                header_item = QStandardItem(
                    tr('results_grid.group_header',
                       group_by=group_by, group_key=gkey, count=len(grp_rows))
                )
                header_item.setData(True, _GROUP_HEADER_ROLE)
                header_item.setBackground(QColor("#c8dff7"))
                header_item.setFont(bold)
                padding = []
                for _ in self.columns[1:]:
                    cell = QStandardItem("")
                    cell.setBackground(QColor("#c8dff7"))
                    cell.setData(True, _GROUP_HEADER_ROLE)
                    padding.append(cell)
                model.appendRow([header_item] + padding)
                for data_row in grp_rows:
                    model.appendRow(self._make_row(data_row))
        else:
            for data_row in rows:
                model.appendRow(self._make_row(data_row))

        self.proxy = _NumericSortProxy(self)
        self.proxy.setSourceModel(model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        self.proxy.setSortRole(_SORT_ROLE)
        self.table_view.setModel(self.proxy)
        self.table_view.setSortingEnabled(not grouped)
        if not grouped:
            self.table_view.horizontalHeader().setSortIndicatorShown(True)

        for col, header in enumerate(self.columns):
            self.table_view.setColumnWidth(col, _DEFAULT_WIDTHS.get(header, 100))

        self._update_status(len(rows), group_by if grouped else None)
        self._apply_filter()
        self._update_chart()

    @staticmethod
    def _make_row(data_row):
        items = []
        for val in data_row:
            if val is None:
                display, sort_val = "", ""
            elif isinstance(val, bool):
                display, sort_val = str(val), int(val)
            elif isinstance(val, float):
                display, sort_val = f"{val:.4f}", val
            elif isinstance(val, int):
                display, sort_val = str(val), val
            else:
                display = sort_val = str(val)
            item = QStandardItem(display)
            item.setData(sort_val, _SORT_ROLE)
            items.append(item)
        return items

    # ------------------------------------------------------------------
    # Chart
    # ------------------------------------------------------------------

    def _update_chart(self):
        if not HAS_MPL or not hasattr(self, "figure"):
            return
        col_name = self.chart_col_combo.currentData()
        if col_name is None or col_name not in self.columns:
            return
        values = self._col_values(col_name)
        total = len(values)
        if total == 0:
            return

        self.figure.clear()
        ax = self.figure.add_subplot(111)

        categorical = isinstance(values[0], str)
        if categorical:
            counts = {}
            for v in values:
                counts[v] = counts.get(v, 0) + 1
            labels = sorted(counts)
            pcts = [counts[label] / total * 100 for label in labels]
        else:
            lo, hi = min(values), max(values)
            if lo == hi:
                hi = lo + 1
            width = (hi - lo) / _BINS
            edges = [lo + i * width for i in range(_BINS + 1)]
            counts = [0] * _BINS
            for v in values:
                counts[min(int((v - lo) / width), _BINS - 1)] += 1
            labels = [f"{edges[b]:.1f}–\n{edges[b + 1]:.1f}" for b in range(_BINS)]
            pcts = [c / total * 100 for c in counts]

        bars = ax.bar(range(len(labels)), pcts, color="#4c8ed6", alpha=0.85)
        for bar, pct in zip(bars, pcts):
            if pct > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.8,
                        f"{pct:.1f}%", ha="center", va="bottom", fontsize=7)

        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, fontsize=7, rotation=30 if categorical else 0,
                           ha="right" if categorical else "center")
        ax.set_ylabel(tr('results_grid.chart_y_label'), fontsize=8)
        ax.set_title(col_name, fontsize=9, pad=6)
        ax.set_ylim(0, max(pcts) * 1.2 if pcts and max(pcts) > 0 else 10)
        ax.grid(axis="y", linestyle="--", alpha=0.4)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        self.canvas.draw()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_group_changed(self):
        self._populate(self.all_rows, self.group_combo.currentData())

    def _apply_filter(self):
        if self.proxy is None:
            return
        self.proxy.setFilterKeyColumn(self.col_combo.currentData())
        self.proxy.setFilterFixedString(self.filter_input.text())

    def _update_status(self, total, group_by):
        parts = [tr('results_grid.status_total', total=total)]
        if group_by:
            parts.append(tr('results_grid.status_grouped', group_by=group_by))
        parts.append(tr('results_grid.status_sort_hint'))
        self.status_label.setText("  |  ".join(parts))

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def visible_rows(self):
        """Rows currently shown (filter + sort applied, group headers skipped)."""
        rows = []
        model = self.proxy.sourceModel()
        for r in range(self.proxy.rowCount()):
            if model.data(self.proxy.mapToSource(self.proxy.index(r, 0)), _GROUP_HEADER_ROLE):
                continue
            row = []
            for c in range(self.proxy.columnCount()):
                raw = model.data(self.proxy.mapToSource(self.proxy.index(r, c)), _SORT_ROLE)
                row.append(raw if raw is not None else "")
            rows.append(row)
        return rows

    def _safe_file_stem(self):
        return "".join(ch if ch.isalnum() or ch in "-_" else "_"
                       for ch in self.layer_name) or "results"

    def _export_excel(self):
        # openpyxl is not bundled with QGIS 4.0.3 → fall back to CSV.
        use_xlsx = importlib.util.find_spec("openpyxl") is not None

        ext = "xlsx" if use_xlsx else "csv"
        filt = "Excel Files (*.xlsx)" if use_xlsx else "CSV Files (*.csv)"
        path, _ = QFileDialog.getSaveFileName(
            self, tr('results_grid.excel_dlg_title'),
            f"{self._safe_file_stem()}_results.{ext}", filt
        )
        if not path:
            return
        if not path.lower().endswith(f".{ext}"):
            path += f".{ext}"
        self.write_table(path, use_xlsx)
        QMessageBox.information(self, tr('results_grid.excel_success_title'),
                                tr('results_grid.excel_success_body', path=path))

    def write_table(self, path, use_xlsx=False):
        """Write the visible rows to *path* as .xlsx (openpyxl) or .csv."""
        data_rows = self.visible_rows()
        if use_xlsx:
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = (self.layer_name or "results")[:31]
            fill = PatternFill("solid", fgColor="4C8ED6")
            font = Font(bold=True, color="FFFFFF")
            for c, col_name in enumerate(self.columns, start=1):
                cell = ws.cell(row=1, column=c, value=col_name)
                cell.fill, cell.font = fill, font
                cell.alignment = Alignment(horizontal="center")
            for r, row in enumerate(data_rows, start=2):
                for c, val in enumerate(row, start=1):
                    ws.cell(row=r, column=c, value=val)
            for col_cells in ws.columns:
                width = max((len(str(cell.value or "")) for cell in col_cells), default=8)
                ws.column_dimensions[col_cells[0].column_letter].width = min(width + 4, 40)
            wb.save(path)
        else:
            import csv
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.writer(fh)
                writer.writerow(self.columns)
                writer.writerows(data_rows)

    def _export_pdf(self):
        has_chart = HAS_MPL and hasattr(self, "figure") and self.chart_col_combo.count() > 0
        export_grid, export_chart = True, False

        if has_chart:
            msg = QMessageBox(self)
            msg.setWindowTitle(tr('results_grid.pdf_what_title'))
            msg.setText(tr('results_grid.pdf_what_body'))
            role = QMessageBox.ButtonRole
            btn_grid = msg.addButton(tr('results_grid.pdf_btn_grid'), role.ActionRole)
            btn_chart = msg.addButton(tr('results_grid.pdf_btn_chart'), role.ActionRole)
            btn_both = msg.addButton(tr('results_grid.pdf_btn_both'), role.ActionRole)
            btn_cancel = msg.addButton(tr('results_grid.pdf_btn_cancel'), role.RejectRole)
            msg.exec()
            clicked = msg.clickedButton()
            if clicked is None or clicked is btn_cancel:
                return
            export_grid = clicked in (btn_grid, btn_both)
            export_chart = clicked in (btn_chart, btn_both)

        path, _ = QFileDialog.getSaveFileName(
            self, tr('results_grid.pdf_dlg_title'),
            f"{self._safe_file_stem()}_results.pdf", "PDF Files (*.pdf)"
        )
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        self.write_pdf(path, export_grid, export_chart)
        QMessageBox.information(self, tr('results_grid.pdf_success_title'),
                                tr('results_grid.pdf_success_body', path=path))

    def write_pdf(self, path, include_grid=True, include_chart=False):
        """Render the grid and/or chart to an A4 landscape PDF at *path*."""
        chart_path = None
        if include_chart and HAS_MPL and hasattr(self, "figure"):
            fd, chart_path = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            self.figure.savefig(chart_path, dpi=150, bbox_inches="tight",
                                facecolor="white")
        try:
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(path)
            printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
            printer.setPageOrientation(QPageLayout.Orientation.Landscape)

            doc = QTextDocument()
            if chart_path:
                # addResource() takes an int: PyQt6 enums expose .value, PyQt5's are ints
                image_type = QTextDocument.ResourceType.ImageResource
                doc.addResource(getattr(image_type, "value", image_type),
                                QUrl("chart.png"), QImage(chart_path))
            doc.setHtml(self._build_html(include_grid,
                                         "chart.png" if chart_path else None))
            # PyQt6 renamed print_() to print()
            (getattr(doc, "print", None) or doc.print_)(printer)
        finally:
            if chart_path and os.path.exists(chart_path):
                os.unlink(chart_path)

    def _build_html(self, include_grid, chart_resource=None):
        esc = html.escape
        out = (
            "<html><head><style>"
            "body{font-family:Arial,sans-serif;font-size:10pt;}"
            "h2{font-size:13pt;margin:4px 0;color:#2c5282;}"
            "p.sub{font-size:9pt;color:#666;margin:2px 0 8px 0;}"
            "table{border-collapse:collapse;width:100%;margin-top:6px;}"
            "th{background:#4c8ed6;color:white;padding:4px 8px;text-align:left;}"
            "td{padding:3px 8px;border-bottom:1px solid #ddd;}"
            "</style></head><body>"
            f"<h2>{esc(tr('results_grid.window_title', name=self.layer_name))}</h2>"
        )
        if chart_resource:
            out += f'<img src="{chart_resource}" width="420"/>'
            if include_grid:
                out += "<br/>"

        if include_grid:
            row_count = self.proxy.rowCount()
            col_count = self.proxy.columnCount()
            model = self.proxy.sourceModel()
            sub = tr('results_grid.pdf_rows', count=row_count)
            if self.filter_input.text():
                sub += tr('results_grid.pdf_filtered', filter=self.filter_input.text())
            out += f'<p class="sub">{esc(sub)}</p><table><tr>'
            out += "".join(f"<th>{esc(col)}</th>" for col in self.columns)
            out += "</tr>"
            display = Qt.ItemDataRole.DisplayRole
            for row in range(row_count):
                src = self.proxy.mapToSource(self.proxy.index(row, 0))
                if model.data(src, _GROUP_HEADER_ROLE):
                    label = self.proxy.data(self.proxy.index(row, 0), display) or ""
                    out += (f'<tr><td colspan="{col_count}" '
                            f'style="background:#c8dff7;font-weight:bold">{esc(label)}</td></tr>')
                    continue
                out += "<tr>" + "".join(
                    f"<td>{esc(str(self.proxy.data(self.proxy.index(row, c), display) or ''))}</td>"
                    for c in range(col_count)
                ) + "</tr>"
            out += "</table>"
        return out + "</body></html>"
