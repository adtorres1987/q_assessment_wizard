# -*- coding: utf-8 -*-
"""
Coverage classes for overlay results.

Pure Python — no QGIS. The coverage of a target feature is the percentage of
its area that intersects the assessment layer(s). The same thresholds are
used by the SQL in ``core/infrastructure/spatial/result_queries.py``.
"""

HIGH_MIN_PCT = 75
MEDIUM_MIN_PCT = 25

CLASS_NO_DATA = 'No data'
CLASS_HIGH = f'High (>={HIGH_MIN_PCT}%)'
CLASS_MEDIUM = f'Medium ({MEDIUM_MIN_PCT}-{HIGH_MIN_PCT - 1}%)'
CLASS_LOW = f'Low (<{MEDIUM_MIN_PCT}%)'
CLASS_NONE = 'None (0%)'


def coverage_class(total_area, intersect_area):
    """Coverage class of a target feature from its total / intersected area."""
    if not total_area:
        return CLASS_NO_DATA
    pct = intersect_area * 100.0 / total_area
    if pct >= HIGH_MIN_PCT:
        return CLASS_HIGH
    if pct >= MEDIUM_MIN_PCT:
        return CLASS_MEDIUM
    if intersect_area > 0:
        return CLASS_LOW
    return CLASS_NONE
