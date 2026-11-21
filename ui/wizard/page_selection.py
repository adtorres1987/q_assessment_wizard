# -*- coding: utf-8 -*-
"""Wizard page 2 — map canvas, basemap, feature selection tools and
map controls; creates the selection layer on Next."""

from qgis.PyQt import QtWidgets
from qgis.PyQt.QtWidgets import QToolBar, QPushButton
from qgis.PyQt.QtCore import Qt, QSize
from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsCoordinateReferenceSystem,
)
from qgis.gui import QgsMapCanvas, QgsMapToolPan
from .map_tools import FeatureSelectionTool, RectangleSelectTool
from .canvas_crs import transform_extent_to_canvas_crs, choose_canvas_crs
from ..i18n.translator import tr


class SelectionPageMixin:
    """Behaviour of page 2 (feature selection on the map)."""

    def initialize_page_2(self):
        """Initialize the second wizard page."""
        self.currentIdChanged.connect(self.on_page_changed)
        self.pushButton_select_all.clicked.connect(self.select_all_features)
        self.pushButton_clear_selection.clicked.connect(self.clear_selection)
        self.page_2.validatePage = self.validate_page_2

    def setup_page_2(self):
        """Setup page 2 with the target layer and map canvas."""
        saved_selection = None
        if self.target_layer and isinstance(self.target_layer, QgsVectorLayer):
            saved_selection = list(self.target_layer.selectedFeatureIds())

        self.target_layer = self.get_target_layer()

        if not self.target_layer:
            QtWidgets.QMessageBox.warning(
                self, tr('dialog.err_no_target_title'),
                tr('dialog.err_no_target_body')
            )
            return

        if not isinstance(self.target_layer, QgsVectorLayer):
            QtWidgets.QMessageBox.warning(
                self, tr('dialog.err_not_vector_title'),
                tr('dialog.err_not_vector_body')
            )
            return

        self.label_target_layer_name.setText(
            tr('dialog.lbl_target_layer', name=self.target_layer.name())
        )

        # Create map canvas if it doesn't exist
        if not self.map_canvas:
            self.map_canvas = QgsMapCanvas(self.map_canvas_container)
            self.map_canvas.setCanvasColor(Qt.GlobalColor.white)
            self.map_canvas.setMinimumSize(400, 400)
            self.map_canvas.resize(800, 600)

            # Create toolbar for map controls
            self.map_toolbar = QToolBar()
            self.map_toolbar.setIconSize(QSize(16, 16))

            self.zoom_in_button = QPushButton(tr('dialog.btn_zoom_in'))
            self.zoom_in_button.clicked.connect(self.zoom_in)
            self.map_toolbar.addWidget(self.zoom_in_button)

            self.zoom_out_button = QPushButton(tr('dialog.btn_zoom_out'))
            self.zoom_out_button.clicked.connect(self.zoom_out)
            self.map_toolbar.addWidget(self.zoom_out_button)

            self.zoom_full_button = QPushButton(tr('dialog.btn_zoom_layer'))
            self.zoom_full_button.clicked.connect(self.zoom_to_layer)
            self.map_toolbar.addWidget(self.zoom_full_button)

            self.pan_button = QPushButton(tr('dialog.btn_pan'))
            self.pan_button.setCheckable(True)
            self.pan_button.clicked.connect(self.toggle_pan)
            self.map_toolbar.addWidget(self.pan_button)

            self.rect_select_button = QPushButton(tr('dialog.btn_rect_select'))
            self.rect_select_button.setCheckable(True)
            self.rect_select_button.clicked.connect(self.toggle_rectangle_select)
            self.map_toolbar.addWidget(self.rect_select_button)

            self.verticalLayout_map.addWidget(self.map_toolbar)
            self.verticalLayout_map.addWidget(self.map_canvas)

            canvas_crs = QgsCoordinateReferenceSystem("EPSG:3857")
            self.map_canvas.setDestinationCrs(canvas_crs)

            self.map_toolbar.show()
            self.map_canvas.show()
            self.map_canvas_container.show()

        # Setup map with target layer and OpenStreetMap (only when the layer
        # can be reprojected to Web Mercator; otherwise draw in its own CRS).
        canvas_crs, use_basemap = choose_canvas_crs(self.target_layer)
        self.map_canvas.setDestinationCrs(canvas_crs)
        osm_layer = self.create_osm_layer() if use_basemap else None
        if not use_basemap:
            crs_label = self.target_layer.crs().authid() or tr('dialog.crs_none')
            self.label_target_layer_name.setText(tr(
                'dialog.lbl_target_no_basemap',
                name=self.target_layer.name(), crs=crs_label,
            ))

        layers_to_display = [self.target_layer]
        if osm_layer and osm_layer.isValid():
            layers_to_display.append(osm_layer)

        self.map_canvas.setLayers([])
        self.map_canvas.setLayers(layers_to_display)

        # Zoom to target layer extent using utility function
        extent = transform_extent_to_canvas_crs(self.map_canvas, self.target_layer)
        self.map_canvas.setExtent(extent)

        self.map_canvas.setCanvasColor(Qt.GlobalColor.white)
        self.map_canvas.setRenderFlag(True)
        self.map_canvas.show()
        self.map_canvas_container.show()
        self.map_canvas.refresh()
        QtWidgets.QApplication.processEvents()
        self.map_canvas.repaint()

        # Create and set the custom selection tool
        self.map_tool_select = FeatureSelectionTool(
            self.map_canvas,
            self.target_layer,
            self.update_selection_count
        )
        self.map_canvas.setMapTool(self.map_tool_select)

        # Connect to layer selection changed signal
        if self.target_layer:
            try:
                self.target_layer.selectionChanged.disconnect(self.update_selection_count)
            except:
                pass
            self.target_layer.selectionChanged.connect(self.update_selection_count)

        # Restore saved selection
        if saved_selection and len(saved_selection) > 0:
            self.target_layer.selectByIds(saved_selection)

        self.update_selection_count()

    def create_osm_layer(self):
        """Create an OpenStreetMap base layer."""
        osm_url = "type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png&zmax=19&zmin=0&crs=EPSG:3857"
        osm_layer = QgsRasterLayer(osm_url, "OpenStreetMap", "wms")
        if osm_layer.isValid():
            return osm_layer
        return None

    def select_all_features(self):
        """Select all features in the target layer."""
        if self.target_layer:
            self.target_layer.selectAll()
            self.update_selection_count()

    def clear_selection(self):
        """Clear all selected features in the target layer."""
        if self.target_layer:
            self.target_layer.removeSelection()
            self.update_selection_count()

    def update_selection_count(self):
        """Update the label showing the number of selected features."""
        if self.target_layer and isinstance(self.target_layer, QgsVectorLayer):
            count = self.target_layer.selectedFeatureCount()
            self.label_selection_count.setText(tr('dialog.lbl_selected_count', count=count))
            if self.map_canvas:
                self.map_canvas.refresh()

    def validate_page_2(self):
        """Validate page 2 before allowing user to proceed."""
        if not self.target_layer:
            QtWidgets.QMessageBox.warning(
                self, tr('dialog.val_title'),
                tr('dialog.val_no_target_available')
            )
            return False

        if self.target_layer.selectedFeatureCount() == 0:
            QtWidgets.QMessageBox.warning(
                self, tr('dialog.val_title'),
                tr('dialog.val_no_features')
            )
            return False

        # Create new layer with selected features
        selected_ids = list(self.target_layer.selectedFeatureIds())
        if selected_ids:
            expected_layer_name = f"{self.target_layer.name()}_selection"
            should_create_new = True

            try:
                if self.selected_features_layer and self.selected_features_layer.isValid():
                    existing_ids = [f.id() for f in self.selected_features_layer.getFeatures()]
                    if sorted(existing_ids) == sorted(selected_ids):
                        should_create_new = False
            except RuntimeError:
                self.selected_features_layer = None
                should_create_new = True

            if should_create_new:
                existing_layers = QgsProject.instance().mapLayersByName(expected_layer_name)
                for existing_layer in existing_layers:
                    if isinstance(existing_layer, QgsVectorLayer):
                        existing_ids = [f.id() for f in existing_layer.getFeatures()]
                        if sorted(existing_ids) == sorted(selected_ids):
                            self.selected_features_layer = existing_layer
                            should_create_new = False
                            break

            if should_create_new:
                try:
                    if self.selected_features_layer and self.selected_features_layer.isValid():
                        QgsProject.instance().removeMapLayer(self.selected_features_layer.id())
                except RuntimeError:
                    pass

                if self.map_tool_select:
                    self.selected_features_layer = self.map_tool_select.create_layer_from_feature_id(
                        self.target_layer,
                        selected_ids
                    )

                    if self.selected_features_layer and self.selected_features_layer.isValid():
                        QgsProject.instance().addMapLayer(self.selected_features_layer)

        return True

    def zoom_in(self):
        """Zoom in on the map canvas."""
        if self.map_canvas:
            self.map_canvas.zoomIn()

    def zoom_out(self):
        """Zoom out on the map canvas."""
        if self.map_canvas:
            self.map_canvas.zoomOut()

    def zoom_to_layer(self):
        """Zoom to the extent of the target layer."""
        if self.map_canvas and self.target_layer:
            extent = transform_extent_to_canvas_crs(self.map_canvas, self.target_layer)
            self.map_canvas.setExtent(extent)
            self.map_canvas.refresh()

    def toggle_pan(self):
        """Toggle pan mode for the map canvas."""
        if self.map_canvas:
            if self.pan_button.isChecked():
                if hasattr(self, 'rect_select_button') and self.rect_select_button.isChecked():
                    self.rect_select_button.setChecked(False)

                if not hasattr(self, 'pan_tool'):
                    self.pan_tool = QgsMapToolPan(self.map_canvas)
                self.map_canvas.setMapTool(self.pan_tool)
            else:
                if self.map_tool_select:
                    self.map_canvas.setMapTool(self.map_tool_select)

    def toggle_rectangle_select(self):
        """Toggle rectangle selection mode for the map canvas."""
        if self.map_canvas:
            if self.rect_select_button.isChecked():
                if hasattr(self, 'pan_button') and self.pan_button.isChecked():
                    self.pan_button.setChecked(False)

                self.rect_select_tool = RectangleSelectTool(
                    self.map_canvas,
                    self.target_layer,
                    self.update_selection_count
                )
                self.map_canvas.setMapTool(self.rect_select_tool)
            else:
                if self.map_tool_select:
                    self.map_canvas.setMapTool(self.map_tool_select)
