# -*- coding: utf-8 -*-
"""Portfolio (LPA) configurations built on an overlay result."""

import json


class PortfoliosMixin:
    """Portfolio records (status 'pending' until a solver exists)."""

    def create_portfolio(self, assessment_id, source_table, name, config_json):
        """Insert a portfolio configuration (status 'pending'). Returns its id."""
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                "INSERT INTO portfolios (assessment_id, source_table, name, config_json) "
                "VALUES (?, ?, ?, ?)",
                (assessment_id, source_table, name, config_json),
            )
            self.connection.commit()
            return cursor.lastrowid
        finally:
            cursor.close()

    def portfolio_name_exists(self, assessment_id, name):
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                "SELECT 1 FROM portfolios WHERE assessment_id = ? AND name = ?",
                (assessment_id, name),
            )
            return cursor.fetchone() is not None
        finally:
            cursor.close()

    def get_portfolios_for_assessment(self, assessment_id):
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                "SELECT id, assessment_id, source_table, name, config_json, status, created_at "
                "FROM portfolios WHERE assessment_id = ? ORDER BY id",
                (assessment_id,),
            )
            return [self._row_to_portfolio(r) for r in cursor.fetchall()]
        finally:
            cursor.close()

    def get_portfolio(self, portfolio_id):
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                "SELECT id, assessment_id, source_table, name, config_json, status, created_at "
                "FROM portfolios WHERE id = ?",
                (portfolio_id,),
            )
            row = cursor.fetchone()
            return self._row_to_portfolio(row) if row else None
        finally:
            cursor.close()

    def delete_portfolio(self, portfolio_id):
        cursor = self.connection.cursor()
        try:
            cursor.execute("DELETE FROM portfolios WHERE id = ?", (portfolio_id,))
            self.connection.commit()
        finally:
            cursor.close()

    @staticmethod
    def _row_to_portfolio(r):
        try:
            config = json.loads(r[4] or '{}')
        except (ValueError, TypeError):
            config = {}
        return {
            'id': r[0], 'assessment_id': r[1], 'source_table': r[2],
            'name': r[3], 'config': config, 'status': r[5], 'created_at': r[6],
        }
