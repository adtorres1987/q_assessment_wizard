# -*- coding: utf-8 -*-
"""
Spatial Engine package — facade for all SpatiaLite spatial operations.

Public API:
    SpatialEngine     — main entry point (context manager)
    OverlayOperation  — enum for operation types
"""

from .engine import SpatialEngine
from .operations import OverlayOperation

__all__ = ["SpatialEngine", "OverlayOperation"]
