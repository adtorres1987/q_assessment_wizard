# -*- coding: utf-8 -*-
"""
Domain package — pure Python business entities.

Rules:
  - No QGIS imports anywhere in this package
  - No database imports anywhere in this package
  - Only IDs, names, enums, and state transitions

Public API:
    LayerRole  — enum: TARGET | ASSESSMENT | MARKER
    LayerRef   — value object: named reference to a spatial layer
    Scenario   — aggregate: an analysis run (project + layers + outputs)
"""

from .models.layer_role import LayerRole
from .models.scenario import Scenario, LayerRef

__all__ = [
    "LayerRole",
    "LayerRef",
    "Scenario",
]
