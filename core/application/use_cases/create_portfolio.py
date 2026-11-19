# -*- coding: utf-8 -*-
"""
CreatePortfolio — use case to save a Portfolio (LPA) configuration.

Business rules:
  - Name is required and unique within the assessment.
  - Benefits, Cost and Prioritization map to three distinct, non-empty columns.
  - Budget is >= 0; enabled buckets cannot exceed a positive budget.
  - No optimisation runs yet: the portfolio is stored with status 'pending'.

Returns:
  - dict: {'portfolio_id': int, 'name': str, 'config': dict}

Raises:
  - ValueError: a business rule is violated.
"""

import json

from ..ports import MetadataRepositoryPort
from .commands import CreatePortfolioCommand


class CreatePortfolio:
    """Use case: validate and persist a portfolio configuration."""

    def __init__(self, metadata_repo: MetadataRepositoryPort):
        if metadata_repo is None:
            raise RuntimeError("CreatePortfolio requires a metadata_repo instance.")
        self._meta = metadata_repo

    def execute(self, cmd: CreatePortfolioCommand) -> dict:
        name = (cmd.name or '').strip()
        if not name:
            raise ValueError("Portfolio name is required.")
        if self._meta.portfolio_name_exists(cmd.assessment_id, name):
            raise ValueError(
                f"A portfolio named '{name}' already exists for this assessment."
            )

        columns = [cmd.col_benefits, cmd.col_cost, cmd.col_priority]
        if not all(columns):
            raise ValueError("Benefits, Cost and Prioritization columns are required.")
        if len(set(columns)) < 3:
            raise ValueError(
                "Benefits, Cost and Prioritization must map to distinct columns."
            )

        budget = float(cmd.budget or 0.0)
        if budget < 0:
            raise ValueError("Budget cannot be negative.")
        buckets = [
            {'name': str(b.get('name', '')).strip(), 'amount': float(b.get('amount', 0.0))}
            for b in (cmd.buckets or [])
        ]
        if any(b['amount'] < 0 for b in buckets):
            raise ValueError("Bucket amounts cannot be negative.")
        allocated = sum(b['amount'] for b in buckets)
        if budget > 0 and allocated > budget + 1e-9:
            raise ValueError(
                f"Sum of buckets ({allocated:,.2f}) exceeds the total budget "
                f"({budget:,.2f})."
            )

        config = {
            'engine': 'portfolio_lpa',
            'col_benefits': cmd.col_benefits,
            'col_cost': cmd.col_cost,
            'col_priority': cmd.col_priority,
            'budget': budget,
            'buckets': buckets,
        }
        portfolio_id = self._meta.create_portfolio(
            cmd.assessment_id, cmd.source_table, name, json.dumps(config)
        )
        return {'portfolio_id': portfolio_id, 'name': name, 'config': config}
