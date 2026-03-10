# -*- coding: utf-8 -*-
"""
Spatial Engine package — facade for all SpatiaLite spatial operations.

Public API:
    SpatialEngine — main entry point (context manager)
"""

from .engine import SpatialEngine

__all__ = ["SpatialEngine"]
