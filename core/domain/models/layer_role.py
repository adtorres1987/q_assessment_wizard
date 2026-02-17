# -*- coding: utf-8 -*-
"""
LayerRole — semantic role of a spatial layer in an analysis scenario.

No QGIS dependency.
"""

from enum import Enum


class LayerRole(Enum):
    """Role that a layer plays within a Scenario.

    TARGET     — the primary subject of the spatial analysis (e.g. forest units)
    ASSESSMENT — the overlay layer used to intersect / union the target
    MARKER     — a reference / context layer not directly used in analysis
    """
    TARGET     = "target"
    ASSESSMENT = "assessment"
    MARKER     = "marker"
