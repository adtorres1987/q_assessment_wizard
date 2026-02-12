# -*- coding: utf-8 -*-
"""
Map Tools Module
Custom QgsMapTool implementations for feature selection by click and rectangle.
"""

from qgis.PyQt.QtCore import Qt
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsPointXY, QgsGeometry,
    QgsWkbTypes, QgsRectangle, QgsFeatureRequest
)
from qgis.gui import QgsMapTool, QgsRubberBand
from PyQt5.QtGui import QColor

from .geometry_utils import transform_point_to_layer_crs, transform_rect_to_layer_crs


class FeatureSelectionTool(QgsMapTool):
    """Custom map tool for selecting features by clicking."""

    def __init__(self, canvas, layer, selection_callback):
        """Initialize the feature selection tool.

        Args:
            canvas: QgsMapCanvas - The map canvas
            layer: QgsVectorLayer - The layer to select features from
            selection_callback: callable - Function to call when selection changes
        """
        super(FeatureSelectionTool, self).__init__(canvas)
        self.layer = layer
        self.selection_callback = selection_callback
        self.setCursor(Qt.CrossCursor)

    def create_layer_from_feature_id(self, source_layer, feature_ids):
        """Create a new memory layer from selected feature IDs.

        Args:
            source_layer: QgsVectorLayer - The source layer
            feature_ids: list - List of feature IDs to copy

        Returns:
            QgsVectorLayer - New memory layer with selected features
        """
        # Get layer properties
        crs = source_layer.crs().authid()
        layer_name = f"{source_layer.name()}_selection"

        # Create new memory layer with proper URI format
        new_layer = QgsVectorLayer(
            f"{QgsWkbTypes.displayString(source_layer.wkbType())}?crs={crs}",
            layer_name, "memory"
        )

        if not new_layer.isValid():
            return None

        # Copy fields from source layer
        new_layer.dataProvider().addAttributes(source_layer.fields())
        new_layer.updateFields()

        # Copy features from source layer
        features = []
        for fid in feature_ids:
            feature = source_layer.getFeature(fid)
            if feature.isValid():
                features.append(feature)

        if features:
            new_layer.dataProvider().addFeatures(features)
            new_layer.updateExtents()

        return new_layer

    def canvasReleaseEvent(self, event):
        """Handle mouse click on the map canvas with CRS transformation."""
        # Get the click point in map coordinates
        point = self.toMapCoordinates(event.pos())

        # Calculate search tolerance based on map scale (5 pixels)
        search_radius = self.canvas().mapUnitsPerPixel() * 5

        # Transform point to layer CRS if needed
        layer_point, layer_search_radius = transform_point_to_layer_crs(
            self.canvas(), self.layer, point, search_radius
        )

        # Create a point geometry for distance calculation in layer CRS
        point_geom = QgsGeometry.fromPointXY(QgsPointXY(layer_point))

        # Create search rectangle for efficient spatial filtering
        search_rect = QgsRectangle(
            layer_point.x() - layer_search_radius,
            layer_point.y() - layer_search_radius,
            layer_point.x() + layer_search_radius,
            layer_point.y() + layer_search_radius
        )

        # Use spatial filter for efficient querying
        request = QgsFeatureRequest()
        request.setFilterRect(search_rect)

        # Find features and calculate distances in layer CRS
        candidates = []
        for feature in self.layer.getFeatures(request):
            geom = feature.geometry()
            if geom and not geom.isNull():
                distance = geom.distance(point_geom)
                if distance <= layer_search_radius:
                    candidates.append((feature.id(), distance))

        # Sort by distance to get the closest feature
        candidates.sort(key=lambda x: x[1])

        if candidates:
            # Get current selection
            selected_ids = set(self.layer.selectedFeatureIds())

            # Toggle selection for the closest feature
            clicked_id = candidates[0][0]
            if clicked_id in selected_ids:
                selected_ids.discard(clicked_id)
            else:
                selected_ids.add(clicked_id)

            # Update layer selection
            self.layer.selectByIds(list(selected_ids))

            # Refresh canvas to show selection
            self.canvas().refresh()

            # Trigger callback to update UI
            if self.selection_callback:
                self.selection_callback()


class RectangleSelectTool(QgsMapTool):
    """Custom map tool for selecting features with a rectangle."""

    def __init__(self, canvas, target_layer=None, selection_callback=None):
        """Initialize the rectangle selection tool.

        Args:
            canvas: QgsMapCanvas - The map canvas
            target_layer: QgsVectorLayer - The layer to select features from (optional)
            selection_callback: callable - Function to call when selection changes
        """
        super(RectangleSelectTool, self).__init__(canvas)
        self.canvas = canvas
        self.target_layer = target_layer
        self.selection_callback = selection_callback
        self.rubber_band = QgsRubberBand(canvas, QgsWkbTypes.PolygonGeometry)
        self.rubber_band.setColor(QColor(255, 0, 0, 100))
        self.rubber_band.setWidth(2)
        self.start_point = None
        self.end_point = None
        self.setCursor(Qt.CrossCursor)

    def canvasPressEvent(self, event):
        """Handle mouse press event."""
        if event.button() == Qt.LeftButton:
            self.start_point = self.toMapCoordinates(event.pos())
            self.end_point = self.start_point
            self.rubber_band.reset(QgsWkbTypes.PolygonGeometry)

    def canvasMoveEvent(self, event):
        """Handle mouse move event to update rubber band."""
        if self.start_point is None:
            return
        self.end_point = self.toMapCoordinates(event.pos())
        self.update_rubber_band()

    def canvasReleaseEvent(self, event):
        """Handle mouse release event to select features (rectangle or point)."""
        if event.button() != Qt.LeftButton or self.start_point is None:
            return

        self.end_point = self.toMapCoordinates(event.pos())
        self.update_rubber_band()

        # Create rectangle from start and end points
        rect = QgsRectangle(self.start_point, self.end_point)

        # Check if this is a single click or a rectangle drag
        is_single_click = rect.isEmpty() or (
            abs(self.start_point.x() - self.end_point.x()) < self.canvas.mapUnitsPerPixel() * 3 and
            abs(self.start_point.y() - self.end_point.y()) < self.canvas.mapUnitsPerPixel() * 3
        )

        additive = event.modifiers() & Qt.ShiftModifier

        # Use target layer if specified, otherwise use all visible vector layers
        if self.target_layer:
            layers = [self.target_layer]
        else:
            layers = [layer for layer in self.canvas.layers()
                     if isinstance(layer, QgsVectorLayer)]

        for layer in layers:
            if not layer or not isinstance(layer, QgsVectorLayer):
                continue

            if is_single_click:
                self._handle_point_selection(layer, self.end_point)
            else:
                self._handle_rect_selection(layer, rect, additive)

        # Reset tool
        self.rubber_band.reset(QgsWkbTypes.PolygonGeometry)
        self.start_point = None
        self.end_point = None

        # Refresh canvas to show selection
        self.canvas.refresh()

        # Trigger callback to update UI after refresh
        if self.selection_callback:
            self.selection_callback()

    def _handle_point_selection(self, layer, point):
        """Handle point (click) selection for a single layer."""
        search_radius = self.canvas.mapUnitsPerPixel() * 5

        layer_point, layer_search_radius = transform_point_to_layer_crs(
            self.canvas, layer, point, search_radius
        )

        point_geom = QgsGeometry.fromPointXY(QgsPointXY(layer_point))
        search_rect = QgsRectangle(
            layer_point.x() - layer_search_radius,
            layer_point.y() - layer_search_radius,
            layer_point.x() + layer_search_radius,
            layer_point.y() + layer_search_radius
        )

        request = QgsFeatureRequest()
        request.setFilterRect(search_rect)

        candidates = []
        for feature in layer.getFeatures(request):
            geom = feature.geometry()
            if geom and not geom.isNull():
                distance = geom.distance(point_geom)
                if distance <= layer_search_radius:
                    candidates.append((feature.id(), distance))

        candidates.sort(key=lambda x: x[1])

        if candidates:
            existing_ids = set(layer.selectedFeatureIds())
            clicked_id = candidates[0][0]

            if clicked_id in existing_ids:
                existing_ids.discard(clicked_id)
            else:
                existing_ids.add(clicked_id)

            layer.selectByIds(list(existing_ids))

    def _handle_rect_selection(self, layer, rect, additive):
        """Handle rectangle selection for a single layer."""
        layer_rect = transform_rect_to_layer_crs(self.canvas, layer, rect)

        request = QgsFeatureRequest()
        request.setFilterRect(layer_rect)

        rect_geom = QgsGeometry.fromRect(layer_rect)
        new_feature_ids = []

        for feature in layer.getFeatures(request):
            if feature.geometry() and feature.geometry().intersects(rect_geom):
                new_feature_ids.append(feature.id())

        if additive:
            existing_ids = set(layer.selectedFeatureIds())
            for fid in new_feature_ids:
                if fid not in existing_ids:
                    existing_ids.add(fid)
            layer.selectByIds(list(existing_ids))
        else:
            layer.selectByIds(new_feature_ids)

    def update_rubber_band(self):
        """Update the rubber band rectangle visualization."""
        self.rubber_band.reset(QgsWkbTypes.PolygonGeometry)
        if self.start_point and self.end_point:
            points = [
                self.start_point,
                QgsPointXY(self.start_point.x(), self.end_point.y()),
                self.end_point,
                QgsPointXY(self.end_point.x(), self.start_point.y())
            ]
            for i, point in enumerate(points):
                self.rubber_band.addPoint(point, True if i == len(points) - 1 else False)
            self.rubber_band.show()

    def deactivate(self):
        """Clean up when tool is deactivated."""
        self.rubber_band.reset(QgsWkbTypes.PolygonGeometry)
        super(RectangleSelectTool, self).deactivate()
