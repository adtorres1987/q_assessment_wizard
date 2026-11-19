# -*- coding: utf-8 -*-
"""
CompareHistogramDialog — paired (butterfly) histogram to compare 2+ results.

Ported from plugin_wizard (histogram_dialog.py), adapted to Qt 6 and to
q_assessment_wizard's layering: the dialog never touches the database; it
receives a ``load_series(tables, field) -> {label: [values]}`` callable
(AssessmentExecutor.get_comparison_series).

Layout:
  - 2 results selected  → a single butterfly chart (A up / B down)
  - 3+ results selected → a grid with one butterfly chart per pair
"""

import bisect
from itertools import combinations

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QSpinBox, QComboBox, QPushButton,
    QListWidget, QListWidgetItem, QMessageBox,
    QFrame, QSizePolicy,
)
from qgis.PyQt.QtCore import Qt

from ...translator import tr

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.figure import Figure
    from matplotlib import ticker
    HAS_MPL = True
except Exception:  # ImportError, or no usable Qt binding
    ticker = None
    HAS_MPL = False

# Aggregated fields provided by core/infrastructure/spatial/result_queries.py
NUMERIC_FIELDS = ["coverage_pct", "total_area", "intersect_area",
                  "no_overlap_area", "fragments"]

# Alternating (up colour, down colour) per pair
PAIR_COLORS = [
    ("#4C72B0", "#DD8452"),
    ("#55A868", "#C44E52"),
    ("#8172B2", "#937860"),
    ("#DA8BC3", "#8C8C8C"),
]


# ── Pure helpers (no Qt) ────────────────────────────────────────────────────

def compute_edges(all_vals, n_bins, bin_type):
    """Bin edges (n_bins + 1) shared by every series.

    equal_range: identical-width intervals over [min, max].
    equal_dist:  quantile edges — each bin holds ~the same number of values;
                 duplicate edges are nudged apart so no bin has zero width.
    """
    lo, hi = min(all_vals), max(all_vals)
    if lo == hi:
        return [lo, lo + 1.0]

    if bin_type == "equal_range":
        w = (hi - lo) / n_bins
        return [lo + i * w for i in range(n_bins + 1)]

    sv = sorted(all_vals)
    n = len(sv)
    edges = []
    for i in range(n_bins + 1):
        pos = i * (n - 1) / n_bins
        lower = int(pos)
        frac = pos - lower
        edges.append(sv[-1] if lower >= n - 1
                     else sv[lower] + frac * (sv[lower + 1] - sv[lower]))
    epsilon = (hi - lo) * 1e-9
    for i in range(1, len(edges)):
        if edges[i] <= edges[i - 1]:
            edges[i] = edges[i - 1] + epsilon
    return edges


def bin_counts(values, edges):
    """Count values per bin: [e_i, e_i+1) except the last bin, which is closed."""
    n_bins = len(edges) - 1
    counts = [0] * n_bins
    for v in values:
        if v < edges[0] or v > edges[-1]:
            continue
        counts[min(bisect.bisect_right(edges, v) - 1, n_bins - 1)] += 1
    return counts


def _draw_butterfly(ax, name_a, counts_a, name_b, counts_b,
                    bin_labels, color_a, color_b, field_lbl, bin_type_lbl):
    """Back-to-back histogram: A above the axis, B below."""
    x = list(range(len(bin_labels)))
    ax.bar(x, counts_a, width=0.72, color=color_a, alpha=0.82, label=name_a)
    ax.bar(x, [-c for c in counts_b], width=0.72, color=color_b, alpha=0.82, label=name_b)
    ax.set_xticks(x)
    ax.set_xticklabels(bin_labels, rotation=35, ha="right", fontsize=7)
    max_val = max(max(counts_a or [0]), max(counts_b or [0]), 1)
    ax.set_ylim(-max_val * 1.3, max_val * 1.3)
    ax.axhline(0, color="black", linewidth=0.9, zorder=3)
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda y, _: str(abs(int(y)))))
    ax.set_ylabel(tr('histogram.chart_y_label'), fontsize=8)
    ax.set_title(f"{name_a}  (↑)  vs  (↓)  {name_b}\n{field_lbl}  ·  {bin_type_lbl}",
                 fontsize=9, pad=6)
    ax.legend(fontsize=7, loc="upper right")
    ax.grid(axis="y", linestyle="--", alpha=0.35)


# ── Dialog ──────────────────────────────────────────────────────────────────

class CompareHistogramDialog(QDialog):
    """Paired-histogram comparison of overlay results.

    Args:
        results:      list[dict] — {'label': str, 'table': str}
        load_series:  callable(tables: dict[label, table], field: str)
                      -> dict[label, list[float]]; may raise
                      LookupError / ValueError / RuntimeError.
    """

    def __init__(self, results, load_series, parent=None):
        super().__init__(parent)
        self.results = list(results)
        self._load_series = load_series
        self.setWindowTitle(tr('histogram.window_title'))
        self.setMinimumSize(980, 680)
        self.resize(1150, 760)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(10, 10, 10, 10)

        ctrl = QGridLayout()
        ctrl.setSpacing(8)

        ctrl.addWidget(QLabel(f"<b>{tr('histogram.lbl_outputs')}</b>"), 0, 0, 1, 2)
        self.list_widget = QListWidget()
        self.list_widget.setMaximumHeight(120)
        for r in self.results:
            item = QListWidgetItem(r['label'])
            item.setData(Qt.ItemDataRole.UserRole, r)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.list_widget.addItem(item)
        ctrl.addWidget(self.list_widget, 1, 0, 1, 2)

        ctrl.addWidget(QLabel(tr('histogram.lbl_field')), 0, 2)
        self.field_combo = QComboBox()
        for f in NUMERIC_FIELDS:
            self.field_combo.addItem(tr(f'histogram.field_{f}'), f)
        ctrl.addWidget(self.field_combo, 1, 2)

        ctrl.addWidget(QLabel(tr('histogram.lbl_bins')), 0, 3)
        self.bins_spin = QSpinBox()
        self.bins_spin.setRange(2, 40)
        self.bins_spin.setValue(10)
        ctrl.addWidget(self.bins_spin, 1, 3)

        ctrl.addWidget(QLabel(tr('histogram.lbl_bin_type')), 0, 4)
        self.bintype_combo = QComboBox()
        self.bintype_combo.addItem(tr('histogram.bin_equal_range'), "equal_range")
        self.bintype_combo.addItem(tr('histogram.bin_equal_dist'), "equal_dist")
        ctrl.addWidget(self.bintype_combo, 1, 4)

        self.plot_btn = QPushButton(tr('histogram.btn_plot'))
        self.plot_btn.setMinimumHeight(36)
        self.plot_btn.setEnabled(HAS_MPL)
        self.plot_btn.clicked.connect(self.plot)
        ctrl.addWidget(self.plot_btn, 1, 5)

        for col, stretch in ((0, 3), (2, 2), (3, 1), (4, 2), (5, 1)):
            ctrl.setColumnStretch(col, stretch)
        root.addLayout(ctrl)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep)

        if HAS_MPL:
            self.figure = Figure(tight_layout=True)
            self.canvas = FigureCanvas(self.figure)
            self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding,
                                      QSizePolicy.Policy.Expanding)
            root.addWidget(self.canvas, 1)
        else:
            root.addWidget(QLabel(tr('histogram.no_matplotlib')), 1)

        btm = QHBoxLayout()
        self.status_lbl = QLabel()
        self.status_lbl.setStyleSheet("color: grey; font-size: 11px;")
        btm.addWidget(self.status_lbl, 1)
        close_btn = QPushButton(tr('histogram.btn_close'))
        close_btn.clicked.connect(self.close)
        btm.addWidget(close_btn)
        root.addLayout(btm)

    def checked_results(self):
        out = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                out.append(item.data(Qt.ItemDataRole.UserRole))
        return out

    def plot(self):
        if not HAS_MPL:
            return
        checked = self.checked_results()
        if len(checked) < 2:
            QMessageBox.warning(self, tr('histogram.err_selection_title'),
                                tr('histogram.err_selection_body'))
            return

        field = self.field_combo.currentData()
        n_bins = self.bins_spin.value()
        bin_type = self.bintype_combo.currentData()
        field_lbl = tr(f'histogram.field_{field}')
        bt_lbl = tr('histogram.bin_equal_range' if bin_type == "equal_range"
                    else 'histogram.bin_equal_dist')

        try:
            series = self._load_series({r['label']: r['table'] for r in checked}, field)
        except (LookupError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, tr('histogram.err_load_title'), str(exc))
            return

        all_vals = [v for vs in series.values() for v in vs]
        edges = compute_edges(all_vals, n_bins, bin_type)
        actual_bins = len(edges) - 1
        bin_labels = [f"{edges[b]:.2g}–{edges[b + 1]:.2g}" for b in range(actual_bins)]
        counts = {name: bin_counts(vals, edges) for name, vals in series.items()}

        pairs = list(combinations(counts.keys(), 2))
        n_cols = 1 if len(pairs) == 1 else 2
        n_rows = (len(pairs) + n_cols - 1) // n_cols

        self.figure.clear()
        for idx, (name_a, name_b) in enumerate(pairs):
            ax = self.figure.add_subplot(n_rows, n_cols, idx + 1)
            color_a, color_b = PAIR_COLORS[idx % len(PAIR_COLORS)]
            _draw_butterfly(ax, name_a, counts[name_a], name_b, counts[name_b],
                            bin_labels, color_a, color_b, field_lbl, bt_lbl)
        self.figure.tight_layout(pad=2.0)
        self.canvas.draw()

        self.status_lbl.setText(tr(
            'histogram.status', n_series=len(series), n_pairs=len(pairs),
            total=sum(len(v) for v in series.values()), bins=actual_bins,
            bin_type=bt_lbl,
        ))
