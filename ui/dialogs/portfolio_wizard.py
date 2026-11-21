# -*- coding: utf-8 -*-
"""
PortfolioWizard — five-page wizard to configure a Portfolio (LPA) run.

Ported from plugin_wizard (portfolio_wizard.py) and adapted to Qt 6.
It only collects the configuration; persistence and validation of the
business rules happen in the CreatePortfolio use case. There is no solver
yet, so saved portfolios have status 'pending'.

Pages:
  0  PortfolioNamePage  — portfolio name (+ engine label)
  1  ColumnMappingPage  — Benefits / Cost / Prioritization → result columns
  2  BudgetPage         — total budget
  3  BucketPage         — optional budget buckets A / B / C
  4  SummaryPage        — read-only review
"""

import html

from qgis.PyQt.QtWidgets import (
    QWizard, QWizardPage,
    QVBoxLayout, QFormLayout,
    QLabel, QLineEdit, QComboBox, QDoubleSpinBox,
    QGroupBox, QTextBrowser, QSizePolicy,
)
from qgis.PyQt.QtCore import Qt

from ..i18n.translator import tr

PAGE_NAME = 0
PAGE_COLUMNS = 1
PAGE_BUDGET = 2
PAGE_BUCKETS = 3
PAGE_SUMMARY = 4

_MAX_AMOUNT = 1_000_000_000.0


def _money_spin():
    spin = QDoubleSpinBox()
    spin.setPrefix("$ ")
    spin.setMinimum(0.0)
    spin.setMaximum(_MAX_AMOUNT)
    spin.setDecimals(2)
    spin.setSingleStep(1_000.0)
    return spin


class PortfolioNamePage(QWizardPage):
    """Page 0 — portfolio name."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._form = QFormLayout()
        self.name_edit = QLineEdit()
        self._form.addRow(tr('page_name.label_name'), self.name_edit)
        self._engine_val_lbl = QLabel()
        self._engine_val_lbl.setTextFormat(Qt.TextFormat.RichText)
        self._form.addRow(tr('page_name.label_engine'), self._engine_val_lbl)
        self.setLayout(self._form)
        self.registerField("portfolio_name*", self.name_edit)
        self.retranslateUi()

    def retranslateUi(self):
        self.setTitle(tr('page_name.title'))
        self.setSubTitle(tr('page_name.subtitle'))
        self.name_edit.setPlaceholderText(tr('page_name.placeholder'))
        self._form.labelForField(self.name_edit).setText(tr('page_name.label_name'))
        self._form.labelForField(self._engine_val_lbl).setText(tr('page_name.label_engine'))
        self._engine_val_lbl.setText(f"<b>{html.escape(tr('page_name.engine_value'))}</b>")


class ColumnMappingPage(QWizardPage):
    """Page 1 — map the three LPA variables to result columns."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._columns = []
        self._form = QFormLayout()
        self.benefits_combo = QComboBox()
        self.cost_combo = QComboBox()
        self.priority_combo = QComboBox()
        self._form.addRow(tr('page_columns.label_benefits'), self.benefits_combo)
        self._form.addRow(tr('page_columns.label_cost'), self.cost_combo)
        self._form.addRow(tr('page_columns.label_priority'), self.priority_combo)
        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: red;")
        self._form.addRow(self.error_label)
        self.setLayout(self._form)

        for name, combo in (("col_benefits", self.benefits_combo),
                            ("col_cost", self.cost_combo),
                            ("col_priority", self.priority_combo)):
            self.registerField(name, combo, "currentText", combo.currentTextChanged)
        self.retranslateUi()

    def set_columns(self, columns):
        self._columns = list(columns)
        for i, combo in enumerate((self.benefits_combo, self.cost_combo, self.priority_combo)):
            combo.clear()
            combo.addItems(self._columns)
            # Pre-select distinct columns so the defaults are valid.
            if len(self._columns) > i:
                combo.setCurrentIndex(i)

    def initializePage(self):
        self.error_label.setText("")

    def validatePage(self):
        b = self.benefits_combo.currentText()
        c = self.cost_combo.currentText()
        p = self.priority_combo.currentText()
        if not b or not c or not p:
            self.error_label.setText(tr('page_columns.error_all_required'))
            return False
        if len({b, c, p}) < 3:
            self.error_label.setText(tr('page_columns.error_distinct'))
            return False
        self.error_label.setText("")
        return True

    def retranslateUi(self):
        self.setTitle(tr('page_columns.title'))
        self.setSubTitle(tr('page_columns.subtitle'))
        self._form.labelForField(self.benefits_combo).setText(tr('page_columns.label_benefits'))
        self._form.labelForField(self.cost_combo).setText(tr('page_columns.label_cost'))
        self._form.labelForField(self.priority_combo).setText(tr('page_columns.label_priority'))


class BudgetPage(QWizardPage):
    """Page 2 — total budget."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._form = QFormLayout()
        self.budget_spin = _money_spin()
        self.budget_spin.setMinimumWidth(200)
        self._form.addRow(tr('page_budget.label_budget'), self.budget_spin)
        self.setLayout(self._form)
        self.registerField("budget", self.budget_spin, "value", self.budget_spin.valueChanged)
        self.retranslateUi()

    def retranslateUi(self):
        self.setTitle(tr('page_budget.title'))
        self.setSubTitle(tr('page_budget.subtitle'))
        self._form.labelForField(self.budget_spin).setText(tr('page_budget.label_budget'))


class BucketPage(QWizardPage):
    """Page 3 — optional split of the budget into up to three buckets."""

    LETTERS = ("A", "B", "C")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._budget = 0.0
        vbox = QVBoxLayout()
        self._buckets = []   # (QGroupBox, QFormLayout, QLineEdit, QDoubleSpinBox)
        for letter in self.LETTERS:
            grp = QGroupBox()
            grp.setCheckable(True)
            grp.setChecked(letter == "A")
            form = QFormLayout()
            name_edit = QLineEdit()
            amount_spin = _money_spin()
            form.addRow(tr('page_buckets.label_name'), name_edit)
            form.addRow(tr('page_buckets.label_amount'), amount_spin)
            grp.setLayout(form)
            vbox.addWidget(grp)
            self._buckets.append((grp, form, name_edit, amount_spin))
        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: red;")
        vbox.addWidget(self.error_label)
        vbox.addStretch(1)
        self.setLayout(vbox)
        self.retranslateUi()

    def initializePage(self):
        self._budget = float(self.wizard().field("budget") or 0.0)
        limit = self._budget if self._budget > 0 else _MAX_AMOUNT
        for i, (_grp, _form, _name, spin) in enumerate(self._buckets):
            spin.setMaximum(limit)
            if i == 0:
                spin.setValue(self._budget)
        self.error_label.setText("")

    def validatePage(self):
        total = sum(spin.value() for grp, _f, _n, spin in self._buckets if grp.isChecked())
        if self._budget > 0 and total > self._budget:
            self.error_label.setText(tr('page_buckets.error_exceeds',
                                        total=f'{total:,.2f}',
                                        budget=f'{self._budget:,.2f}'))
            return False
        self.error_label.setText("")
        return True

    def get_buckets(self):
        return [
            {"name": name_edit.text().strip() or grp.title(), "amount": spin.value()}
            for grp, _form, name_edit, spin in self._buckets
            if grp.isChecked()
        ]

    def retranslateUi(self):
        self.setTitle(tr('page_buckets.title'))
        self.setSubTitle(tr('page_buckets.subtitle'))
        for letter, (grp, form, name_edit, spin) in zip(self.LETTERS, self._buckets):
            grp.setTitle(tr('page_buckets.group_title', letter=letter))
            name_edit.setPlaceholderText(tr('page_buckets.placeholder_name', letter=letter))
            form.labelForField(name_edit).setText(tr('page_buckets.label_name'))
            form.labelForField(spin).setText(tr('page_buckets.label_amount'))


class SummaryPage(QWizardPage):
    """Page 4 — read-only overview."""

    def __init__(self, parent=None):
        super().__init__(parent)
        vbox = QVBoxLayout()
        self.browser = QTextBrowser()
        self.browser.setOpenLinks(False)
        self.browser.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        vbox.addWidget(self.browser)
        self.setLayout(vbox)
        self.retranslateUi()

    def initializePage(self):
        wiz = self.wizard()
        bucket_page = wiz.page(PAGE_BUCKETS)
        self.browser.setHtml(build_summary_html(
            wiz.field("portfolio_name") or "",
            wiz.field("col_benefits") or "",
            wiz.field("col_cost") or "",
            wiz.field("col_priority") or "",
            float(wiz.field("budget") or 0.0),
            bucket_page.get_buckets() if bucket_page else [],
        ))

    def retranslateUi(self):
        self.setTitle(tr('page_summary.title'))
        self.setSubTitle(tr('page_summary.subtitle'))
        wiz = self.wizard()
        if wiz and wiz.field("portfolio_name"):
            self.initializePage()


def build_summary_html(name, col_b, col_c, col_p, budget, buckets):
    esc = html.escape
    rows_mapping = "".join(
        f"<tr><td>{esc(tr(label))}</td><td><code>{esc(col)}</code></td></tr>"
        for label, col in (('page_summary.html_benefits', col_b),
                           ('page_summary.html_cost', col_c),
                           ('page_summary.html_priority', col_p))
    )
    bucket_section = ""
    if buckets:
        bucket_rows = "".join(
            f"<tr><td>{esc(b['name'])}</td><td>$ {b['amount']:,.2f}</td></tr>"
            for b in buckets
        )
        bucket_section = (
            f"<h3>{esc(tr('page_summary.html_buckets'))}</h3>"
            '<table border="1" cellpadding="4" cellspacing="0" width="100%">'
            f"<tr><th align=\"left\">{esc(tr('page_summary.html_bucket_col'))}</th>"
            f"<th align=\"left\">{esc(tr('page_summary.html_amount'))}</th></tr>"
            f"{bucket_rows}</table>"
        )
    return (
        '<html><body style="font-family: sans-serif; font-size: 10pt;">'
        f"<h2>{esc(name)}</h2>"
        f"<p><b>{esc(tr('page_summary.html_engine'))}</b> {esc(tr('page_name.engine_value'))}</p>"
        f"<h3>{esc(tr('page_summary.html_col_mapping'))}</h3>"
        '<table border="1" cellpadding="4" cellspacing="0" width="100%">'
        f"<tr><th align=\"left\">{esc(tr('page_summary.html_variable'))}</th>"
        f"<th align=\"left\">{esc(tr('page_summary.html_column'))}</th></tr>"
        f"{rows_mapping}</table>"
        f"<h3>{esc(tr('page_summary.html_budget'))}</h3><p>$ {budget:,.2f}</p>"
        f"{bucket_section}</body></html>"
    )


class PortfolioWizard(QWizard):
    """Collects a portfolio configuration.

    Usage::

        wiz = PortfolioWizard(columns=result_columns, parent=self)
        if wiz.exec() == QDialog.DialogCode.Accepted:
            config = wiz.get_config()
    """

    def __init__(self, columns=None, parent=None):
        super().__init__(parent)
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setMinimumSize(540, 440)

        self._page_name = PortfolioNamePage()
        self._page_columns = ColumnMappingPage()
        self._page_budget = BudgetPage()
        self._page_buckets = BucketPage()
        self._page_summary = SummaryPage()
        for page_id, page in ((PAGE_NAME, self._page_name),
                              (PAGE_COLUMNS, self._page_columns),
                              (PAGE_BUDGET, self._page_budget),
                              (PAGE_BUCKETS, self._page_buckets),
                              (PAGE_SUMMARY, self._page_summary)):
            self.setPage(page_id, page)
        self.setStartId(PAGE_NAME)
        self.setWindowTitle(tr('wizard.title'))
        if columns:
            self._page_columns.set_columns(columns)

    def set_columns(self, columns):
        self._page_columns.set_columns(columns)

    def get_config(self):
        """Keys: portfolio_name, col_benefits, col_cost, col_priority, budget, buckets."""
        return {
            "portfolio_name": (self.field("portfolio_name") or "").strip(),
            "col_benefits": self.field("col_benefits"),
            "col_cost": self.field("col_cost"),
            "col_priority": self.field("col_priority"),
            "budget": float(self.field("budget") or 0.0),
            "buckets": self._page_buckets.get_buckets(),
        }
