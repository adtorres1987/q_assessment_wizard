# -*- coding: utf-8 -*-
"""
Read-only queries over cumulative-overlay output tables.

An overlay table (``{project}__{assessment}__v{n}``) holds one row per
fragment, with ``input_id`` (feature of the target layer), ``split_type``
('intersect' | 'no_overlap') and ``shape_area``. These helpers aggregate it
per target feature for the results grid and the comparison histogram.

All functions take an open sqlite3 connection to the project SpatiaLite DB.

Raises:
    LookupError: the table does not exist.
    ValueError:  the table is not an overlay output (missing columns) or an
                 unknown field was requested.
"""

from ...domain.rules import coverage

_GEOMETRY_COLUMNS = {"geom", "geometry"}
_REQUIRED_COLUMNS = {"input_id", "split_type", "shape_area"}

_INTERSECT = "SUM(CASE WHEN split_type='intersect' THEN shape_area ELSE 0 END)"
_NO_OVERLAP = "SUM(CASE WHEN split_type='no_overlap' THEN shape_area ELSE 0 END)"

# Per-target-feature aggregates available to the histogram.
FIELD_EXPRESSIONS = {
    "coverage_pct":    f"{_INTERSECT} * 100.0 / NULLIF(SUM(shape_area), 0)",
    "total_area":      "SUM(shape_area)",
    "intersect_area":  _INTERSECT,
    "no_overlap_area": _NO_OVERLAP,
    "fragments":       "COUNT(*)",
}
NUMERIC_FIELDS = list(FIELD_EXPRESSIONS)


def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def table_columns(conn, table):
    """Return the table's non-geometry column names, in table order."""
    rows = conn.execute(f"PRAGMA table_info({_quote(table)})").fetchall()
    if not rows:
        raise LookupError(f"Table '{table}' not found in the project database.")
    return [r[1] for r in rows if r[1].lower() not in _GEOMETRY_COLUMNS]


def _require_overlay(conn, table):
    columns = table_columns(conn, table)
    missing = _REQUIRED_COLUMNS - {c.lower() for c in columns}
    if missing:
        raise ValueError(
            f"Table '{table}' is not an overlay result "
            f"(missing columns: {', '.join(sorted(missing))})."
        )
    return columns


def coverage_summary(conn, table):
    """Aggregate an overlay table per target feature.

    Columns: input_id, fragments, total_area, intersect_area, no_overlap_area,
    coverage_pct, coverage_class — plus mcda_score (sum of the fragment
    scores) when the table has been scored with MCDA.

    Returns:
        tuple: (columns: list[str], rows: list[tuple]) sorted by coverage desc.
    """
    columns = _require_overlay(conn, table)
    score_col = next((c for c in columns if c.lower() == "mcda_score"), None)

    pct = f"{_INTERSECT} * 100.0 / NULLIF(SUM(shape_area), 0)"
    select = [
        "input_id",
        "COUNT(*) AS fragments",
        "ROUND(SUM(shape_area), 2) AS total_area",
        f"ROUND({_INTERSECT}, 2) AS intersect_area",
        f"ROUND({_NO_OVERLAP}, 2) AS no_overlap_area",
        f"ROUND({pct}, 1) AS coverage_pct",
        # Same thresholds/labels as core.domain.rules.coverage.coverage_class
        f"""CASE
                WHEN SUM(shape_area) = 0 OR SUM(shape_area) IS NULL THEN '{coverage.CLASS_NO_DATA}'
                WHEN {pct} >= {coverage.HIGH_MIN_PCT} THEN '{coverage.CLASS_HIGH}'
                WHEN {pct} >= {coverage.MEDIUM_MIN_PCT} THEN '{coverage.CLASS_MEDIUM}'
                WHEN {_INTERSECT} > 0 THEN '{coverage.CLASS_LOW}'
                ELSE '{coverage.CLASS_NONE}'
            END AS coverage_class""",
    ]
    out_columns = ["input_id", "fragments", "total_area", "intersect_area",
                   "no_overlap_area", "coverage_pct", "coverage_class"]
    if score_col:
        select.append(f"ROUND(SUM({_quote(score_col)}), 6) AS mcda_score")
        out_columns.append("mcda_score")

    rows = conn.execute(
        f"SELECT {', '.join(select)} FROM {_quote(table)} "
        f"GROUP BY input_id ORDER BY coverage_pct DESC"
    ).fetchall()
    return out_columns, [tuple(r) for r in rows]


def coverage_values(conn, table, field):
    """Return one aggregated value per target feature for *field*."""
    if field not in FIELD_EXPRESSIONS:
        raise ValueError(
            f"Unknown field '{field}'. Available: {', '.join(NUMERIC_FIELDS)}"
        )
    _require_overlay(conn, table)
    rows = conn.execute(
        f"SELECT {FIELD_EXPRESSIONS[field]} FROM {_quote(table)} GROUP BY input_id"
    ).fetchall()
    return [r[0] for r in rows if r[0] is not None]
