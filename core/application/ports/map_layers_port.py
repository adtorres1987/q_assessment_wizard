# -*- coding: utf-8 -*-
"""
MapLayersPort — what the use cases need from the live QGIS map.

Use cases receive QGIS layers inside commands (the application boundary) but
never import QGIS: every operation on the map goes through this port.
Implemented by core/infrastructure/qgis/map_layers.py:QgisMapLayers.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class MapLayersPort(Protocol):

    def selected_feature_count(self, layer) -> int:
        """Number of features currently selected in *layer*."""
        ...

    def add_selection_as_memory_layer(self, layer, name: str, group_name: str):
        """Copy the selected features of *layer* into a new memory layer
        named *name*, add it to the layer-tree group *group_name*
        (created if missing) and return it."""
        ...

    def reload_layers_showing(self, table_name: str) -> None:
        """Reload every map layer whose name contains *table_name*."""
        ...
