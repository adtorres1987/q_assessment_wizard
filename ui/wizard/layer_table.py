# -*- coding: utf-8 -*-
"""Page-1 layer table: status combos (translated label + STATUS_* key as item
data) and helpers that read layers by status."""

from qgis.PyQt.QtWidgets import QComboBox, QTableWidgetItem, QMessageBox
from qgis.core import QgsProject, QgsVectorLayer, QgsWkbTypes
from ..i18n.translator import tr


class LayerTableMixin:
    """Builds and reads the layer/status table of page 1."""

    def _status_items(self):
        """(key, translated label) pairs for the layer status combos."""
        return [
            (self.STATUS_DO_NOT_INCLUDE, tr('dialog.status_do_not_include')),
            (self.STATUS_INCLUDE,        tr('dialog.status_include')),
            (self.STATUS_TARGET,         tr('dialog.status_target')),
            (self.STATUS_SPATIAL_MARKER, tr('dialog.status_spatial_marker')),
        ]

    def _make_status_combo(self):
        combo = QComboBox()
        for key, label in self._status_items():
            combo.addItem(label, key)
        combo.currentIndexChanged.connect(self.on_status_changed)
        return combo

    @staticmethod
    def _status_of(combo):
        """Language-independent status key of a status combo."""
        return combo.currentData() or combo.currentText()

    @staticmethod
    def _set_status(combo, status):
        idx = combo.findData(status)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _status_constants(self):
        """Return status constants as a dict for external modules."""
        return {
            'STATUS_TARGET': self.STATUS_TARGET,
            'STATUS_INCLUDE': self.STATUS_INCLUDE,
            'STATUS_SPATIAL_MARKER': self.STATUS_SPATIAL_MARKER,
            'STATUS_DO_NOT_INCLUDE': self.STATUS_DO_NOT_INCLUDE,
        }

    def _collect_selected_layers(self):
        """Collect layers that are not 'Do not include' from the table widget.

        Returns:
            dict: {layer_name: QgsVectorLayer}
        """
        layers_dict = {}
        for row in range(self.tableWidget_layers.rowCount()):
            layer_name_item = self.tableWidget_layers.item(row, 0)
            status_combo = self.tableWidget_layers.cellWidget(row, 2)

            if layer_name_item and status_combo:
                if self._status_of(status_combo) != self.STATUS_DO_NOT_INCLUDE:
                    layer_name = layer_name_item.text()
                    layers = QgsProject.instance().mapLayersByName(layer_name)
                    if layers and isinstance(layers[0], QgsVectorLayer):
                        layers_dict[layer_name] = layers[0]
        return layers_dict

    def _collect_target_and_assessment_layers(self):
        """Read table widget to find target and assessment layers.

        Returns:
            tuple: (target_layer: QgsVectorLayer or None,
                    assessment_layers: list[QgsVectorLayer])
        """
        target_layer = None
        assessment_layers = []

        for row in range(self.tableWidget_layers.rowCount()):
            layer_name_item = self.tableWidget_layers.item(row, 0)
            status_combo = self.tableWidget_layers.cellWidget(row, 2)

            if layer_name_item and status_combo:
                layer_name = layer_name_item.text()
                status = self._status_of(status_combo)

                layers = QgsProject.instance().mapLayersByName(layer_name)
                if layers and isinstance(layers[0], QgsVectorLayer):
                    if status == self.STATUS_TARGET:
                        target_layer = layers[0]
                    elif status == self.STATUS_INCLUDE:
                        assessment_layers.append(layers[0])

        return target_layer, assessment_layers

    def populate_layers(self):
        """Populate the table widget with vector layers from the 'Base Layers' group folder."""
        self.tableWidget_layers.setRowCount(0)

        root = QgsProject.instance().layerTreeRoot()

        # Look for a group called "Base Layers" to find input layers
        base_layers_group = root.findGroup("Base Layers")

        if not base_layers_group:
            QMessageBox.warning(
                self,
                tr('dialog.no_base_group_title'),
                tr('dialog.no_base_group_body')
            )
            return

        tree_layers = base_layers_group.findLayers()

        for tree_layer in tree_layers:
            layer = tree_layer.layer()

            if not layer or not isinstance(layer, QgsVectorLayer):
                continue

            row_position = self.tableWidget_layers.rowCount()
            self.tableWidget_layers.insertRow(row_position)

            # Column 0: Layer name
            layer_item = QTableWidgetItem(layer.name())
            self.tableWidget_layers.setItem(row_position, 0, layer_item)

            # Column 1: Geometry type
            geometry_type = QgsWkbTypes.displayString(layer.wkbType())
            geometry_item = QTableWidgetItem(geometry_type)
            self.tableWidget_layers.setItem(row_position, 1, geometry_item)

            # Column 2: Status dropdown
            status_combo = self._make_status_combo()
            self.tableWidget_layers.setCellWidget(row_position, 2, status_combo)

        self.tableWidget_layers.resizeColumnsToContents()

    def _add_output_layers_to_table(self):
        """Add Output Layers to the table widget with a blue background (v2+ mode only)."""
        from qgis.core import QgsProject, QgsVectorLayer, QgsWkbTypes
        from qgis.PyQt.QtGui import QColor

        root = QgsProject.instance().layerTreeRoot()
        output_group = root.findGroup("Output Layers")
        if not output_group:
            return

        light_blue = QColor(173, 216, 230)

        for tree_layer in output_group.findLayers():
            layer = tree_layer.layer()
            if not layer or not isinstance(layer, QgsVectorLayer):
                continue

            row = self.tableWidget_layers.rowCount()
            self.tableWidget_layers.insertRow(row)

            layer_item = QTableWidgetItem(layer.name())
            layer_item.setBackground(light_blue)
            self.tableWidget_layers.setItem(row, 0, layer_item)

            geom_item = QTableWidgetItem(
                QgsWkbTypes.displayString(layer.wkbType())
            )
            geom_item.setBackground(light_blue)
            self.tableWidget_layers.setItem(row, 1, geom_item)

            status_combo = self._make_status_combo()
            self.tableWidget_layers.setCellWidget(row, 2, status_combo)

        self.tableWidget_layers.resizeColumnsToContents()

    def on_status_changed(self, _index=None):
        """Handle status change to ensure only one layer is set as Target."""
        sender = self.sender()
        if isinstance(sender, QComboBox) and self._status_of(sender) == self.STATUS_TARGET:
            for row in range(self.tableWidget_layers.rowCount()):
                combo = self.tableWidget_layers.cellWidget(row, 2)
                if combo and combo is not sender and self._status_of(combo) == self.STATUS_TARGET:
                    self._set_status(combo, self.STATUS_DO_NOT_INCLUDE)

    def get_target_layer(self):
        """Get the layer marked as 'Include as Target' from page 1."""
        for row in range(self.tableWidget_layers.rowCount()):
            combo = self.tableWidget_layers.cellWidget(row, 2)
            if combo and self._status_of(combo) == self.STATUS_TARGET:
                layer_name = self.tableWidget_layers.item(row, 0).text()
                layers = QgsProject.instance().mapLayersByName(layer_name)
                if layers:
                    return layers[0]
        return None
