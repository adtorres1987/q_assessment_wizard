# -*- coding: utf-8 -*-
"""
QgisMapLayers — MapLayersPort implementation over the live QGIS project.
"""

from qgis.core import QgsProject, QgsVectorLayer, QgsWkbTypes


def find_or_create_group(group_name):
    """Top-level layer-tree group *group_name* (created if missing)."""
    root = QgsProject.instance().layerTreeRoot()
    return root.findGroup(group_name) or root.addGroup(group_name)


class QgisMapLayers:
    """Operations on the current QGIS project's map layers."""

    def selected_feature_count(self, layer):
        return layer.selectedFeatureCount()

    def add_selection_as_memory_layer(self, layer, name, group_name):
        selected = list(layer.selectedFeatures())
        geom_type = QgsWkbTypes.displayString(layer.wkbType())
        crs = layer.crs().authid()

        memory_layer = QgsVectorLayer(f"{geom_type}?crs={crs}", name, "memory")
        provider = memory_layer.dataProvider()
        provider.addAttributes(layer.fields().toList())
        memory_layer.updateFields()
        provider.addFeatures(selected)
        memory_layer.updateExtents()

        group = find_or_create_group(group_name)
        QgsProject.instance().addMapLayer(memory_layer, False)
        group.addLayer(memory_layer)
        return memory_layer

    def reload_layers_showing(self, table_name):
        for map_layer in QgsProject.instance().mapLayers().values():
            if table_name in (map_layer.name() or ''):
                map_layer.reload()
