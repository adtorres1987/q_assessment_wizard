# -*- coding: utf-8 -*-
"""Wizard page 3 — summary of the configuration and map of the selection."""

from qgis.PyQt import QtWidgets
from qgis.PyQt.QtWidgets import QTableWidgetItem, QVBoxLayout
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsProject, QgsVectorLayer, QgsCoordinateReferenceSystem
from qgis.gui import QgsMapCanvas
from .canvas_crs import transform_extent_to_canvas_crs, choose_canvas_crs
from .assessment_summary import get_assessment_summary
from ..i18n.translator import tr


class SummaryPageMixin:
    """Behaviour of page 3 (summary)."""

    def initialize_page_3(self):
        """Initialize the third wizard page."""
        self.tableWidget_summary_layers.setColumnCount(3)
        self.tableWidget_summary_layers.setHorizontalHeaderLabels(
            [tr('dialog.tbl_col_layer'), tr('dialog.tbl_col_geometry'),
             tr('dialog.tbl_col_status')]
        )
        self.tableWidget_summary_layers.horizontalHeader().setStretchLastSection(True)

    def setup_page_3(self):
        """Populate page 3 with summary information."""
        assessment_name = self.lineEdit_name.text().strip()
        assessment_description = self.textEdit_description.toPlainText().strip()

        self.label_summary_name.setText(assessment_name)
        self.label_summary_description.setText(
            assessment_description if assessment_description else tr('dialog.lbl_no_description')
        )

        # Get assessment summary using extracted utility
        summary = get_assessment_summary(
            self.tableWidget_layers, self._status_constants()
        )
        self.label_complexity_summary.setText(summary)

        # Selected feature count
        if self.target_layer and isinstance(self.target_layer, QgsVectorLayer):
            feature_count = self.target_layer.selectedFeatureCount()
            self.label_summary_features.setText(
                tr('dialog.lbl_features_selected', count=feature_count)
            )
        else:
            self.label_summary_features.setText(tr('dialog.lbl_features_selected', count=0))

        # Populate layers summary table
        self.tableWidget_summary_layers.setRowCount(0)

        row = 0
        for table_row in range(self.tableWidget_layers.rowCount()):
            layer_name_item = self.tableWidget_layers.item(table_row, 0)
            geometry_type_item = self.tableWidget_layers.item(table_row, 1)
            status_combo = self.tableWidget_layers.cellWidget(table_row, 2)

            if layer_name_item and status_combo:
                status = self._status_of(status_combo)

                if status != self.STATUS_DO_NOT_INCLUDE:
                    self.tableWidget_summary_layers.insertRow(row)

                    name_item = QTableWidgetItem(layer_name_item.text())
                    self.tableWidget_summary_layers.setItem(row, 0, name_item)

                    geometry_item = QTableWidgetItem(
                        geometry_type_item.text() if geometry_type_item else "Unknown"
                    )
                    self.tableWidget_summary_layers.setItem(row, 1, geometry_item)

                    status_item = QTableWidgetItem(status_combo.currentText())
                    self.tableWidget_summary_layers.setItem(row, 2, status_item)

                    if status == self.STATUS_TARGET:
                        name_item.setBackground(Qt.GlobalColor.gray)
                        geometry_item.setBackground(Qt.GlobalColor.gray)
                        status_item.setBackground(Qt.GlobalColor.gray)

                    row += 1

        self.tableWidget_summary_layers.resizeColumnsToContents()

        # Setup map canvas for page 3
        if not self.map_canvas_page3:
            self.map_canvas_page3 = QgsMapCanvas(self.widget_map_container_page3)
            self.map_canvas_page3.setCanvasColor(Qt.GlobalColor.white)
            self.map_canvas_page3.setMinimumSize(400, 400)
            self.map_canvas_page3.resize(800, 400)

            if not self.widget_map_container_page3.layout():
                layout = QVBoxLayout(self.widget_map_container_page3)
                layout.setContentsMargins(0, 0, 0, 0)
            else:
                layout = self.widget_map_container_page3.layout()

            layout.addWidget(self.map_canvas_page3)

            canvas_crs = QgsCoordinateReferenceSystem("EPSG:3857")
            self.map_canvas_page3.setDestinationCrs(canvas_crs)

            self.map_canvas_page3.show()
            self.widget_map_container_page3.show()
            self.groupBox_selected_features_map.show()

        # Display the selected features layer
        if self.selected_features_layer and self.selected_features_layer.isValid():
            canvas_crs, use_basemap = choose_canvas_crs(self.selected_features_layer)
            self.map_canvas_page3.setDestinationCrs(canvas_crs)
            osm_layer = self.create_osm_layer() if use_basemap else None

            # Get assessment layers for display
            assessment_layers = []
            for table_row in range(self.tableWidget_layers.rowCount()):
                layer_name_item = self.tableWidget_layers.item(table_row, 0)
                status_combo = self.tableWidget_layers.cellWidget(table_row, 2)

                if layer_name_item and status_combo:
                    if self._status_of(status_combo) == self.STATUS_INCLUDE:
                        layer_name = layer_name_item.text()
                        layers = QgsProject.instance().mapLayersByName(layer_name)
                        if layers and isinstance(layers[0], QgsVectorLayer):
                            assessment_layers.append(layers[0])

            layers_to_display = [self.selected_features_layer]
            layers_to_display.extend(assessment_layers)
            if osm_layer and osm_layer.isValid():
                layers_to_display.append(osm_layer)

            self.map_canvas_page3.setLayers([])
            self.map_canvas_page3.setLayers(layers_to_display)

            # Zoom to selected features using utility function
            extent = transform_extent_to_canvas_crs(
                self.map_canvas_page3, self.selected_features_layer
            )
            self.map_canvas_page3.setExtent(extent)

            self.map_canvas_page3.setRenderFlag(True)
            self.map_canvas_page3.refresh()
            QtWidgets.QApplication.processEvents()
            self.map_canvas_page3.repaint()
