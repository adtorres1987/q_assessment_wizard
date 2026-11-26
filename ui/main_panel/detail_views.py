# -*- coding: utf-8 -*-
"""
Contextual detail area under the tree: which card or text is shown for
the selected node, and the summary after the wizard finishes.

Mixin of AssessmentMainForm (ui/main_panel/panel.py): shares its widgets
and state through self and defines no __init__.
"""

from ..i18n.translator import tr
from ..panels import ROLE_ID, ROLE_NAME, ROLE_OUTPUT_TABLES


class DetailViewsMixin:
    """Contextual detail area under the tree: which card or text is shown for"""

    # ------------------------------------------------------------------ #
    #  Detail views per node type
    # ------------------------------------------------------------------ #

    def _show_assessment_details(self, item):
        """Show assessment detail card in the contextual panel."""
        assessment_id   = item.data(0, ROLE_ID)
        assessment_name = item.data(0, ROLE_NAME) or item.text(0)

        details      = self.facade.assessment_details(assessment_id)
        assessment   = details['assessment']
        input_layers = details['input_layers']
        weights      = details['weights']
        target_layer = assessment.get('target_layer', '') if assessment else ''
        created_at   = assessment.get('created_at', '')  if assessment else ''

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
        count = self.facade.project_summary(project_id)['assessment_count']
        text = tr('main.details_project', name=project_name, count=count)
        self._detail_stack.setCurrentIndex(1)
        self.results_text_edit.setPlainText(text)

    def _show_portfolio_details(self, item):
        """Show the stored configuration of a portfolio (💼) node."""
        portfolio = self.facade.portfolio(item.data(0, ROLE_ID))
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
    #  Wizard result summary
    # ------------------------------------------------------------------ #

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
