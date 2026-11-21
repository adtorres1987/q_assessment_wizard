# -*- coding: utf-8 -*-
"""
Map-canvas CRS helpers for the assessment wizard.

Choose the canvas CRS for a layer and convert points / extents / rectangles
between the canvas CRS and a layer's CRS without raising on bad CRSs.
"""

from qgis.core import (
    QgsProject, QgsPointXY, QgsRectangle,
    QgsCoordinateTransform, QgsCoordinateReferenceSystem,
    QgsCsException
)

WEB_MERCATOR = "EPSG:3857"


def choose_canvas_crs(layer):
    """Pick the CRS for a wizard map canvas showing ``layer``.

    Web Mercator is preferred so the OpenStreetMap basemap can be drawn.
    If the layer's extent cannot be reprojected to Web Mercator (layer has no
    CRS, or a wrong one, e.g. projected metre coordinates tagged as
    EPSG:4326), fall back to the layer's own CRS and skip the basemap.

    Returns:
        tuple: (QgsCoordinateReferenceSystem, use_basemap: bool)
    """
    web_mercator = QgsCoordinateReferenceSystem(WEB_MERCATOR)
    layer_crs = layer.crs()
    if not layer_crs.isValid():
        return layer_crs, False

    extent = layer.extent()
    if extent.isNull() or extent.isEmpty():
        return web_mercator, True

    if layer_crs.isGeographic() and (
            extent.xMinimum() < -180 or extent.xMaximum() > 180
            or extent.yMinimum() < -90 or extent.yMaximum() > 90):
        return layer_crs, False

    try:
        QgsCoordinateTransform(
            layer_crs, web_mercator, QgsProject.instance()
        ).transformBoundingBox(extent)
    except QgsCsException:
        return layer_crs, False
    return web_mercator, True


def transform_point_to_layer_crs(canvas, layer, map_point, search_radius):
    """Transform a map point and search radius from canvas CRS to layer CRS.

    Args:
        canvas: QgsMapCanvas
        layer: QgsVectorLayer
        map_point: QgsPointXY in canvas CRS
        search_radius: float in canvas map units

    Returns:
        tuple: (layer_point: QgsPointXY, layer_search_radius: float)
    """
    if canvas.mapSettings().destinationCrs() != layer.crs():
        transform = QgsCoordinateTransform(
            canvas.mapSettings().destinationCrs(),
            layer.crs(),
            QgsProject.instance()
        )
        try:
            layer_point = transform.transform(map_point)
            test_point = QgsPointXY(map_point.x() + search_radius, map_point.y())
            transformed_test = transform.transform(test_point)
        except QgsCsException:
            return map_point, search_radius
        layer_search_radius = layer_point.distance(transformed_test)
        return layer_point, layer_search_radius

    return map_point, search_radius


def transform_extent_to_canvas_crs(canvas, layer):
    """Transform a layer's extent to the canvas CRS with 10% buffer.

    Args:
        canvas: QgsMapCanvas
        layer: QgsVectorLayer or QgsRasterLayer

    Returns:
        QgsRectangle: Transformed and buffered extent, or world extent fallback
    """
    extent = layer.extent()
    if not extent.isNull() and not extent.isEmpty():
        if layer.crs() != canvas.mapSettings().destinationCrs():
            transform = QgsCoordinateTransform(
                layer.crs(),
                canvas.mapSettings().destinationCrs(),
                QgsProject.instance()
            )
            try:
                extent = transform.transformBoundingBox(extent)
            except QgsCsException:
                full = canvas.fullExtent()
                if not full.isNull() and not full.isEmpty():
                    return full
                return QgsRectangle(-20037508, -20037508, 20037508, 20037508)
        extent.scale(1.1)
        return extent

    # Fallback to world extent in EPSG:3857
    return QgsRectangle(-20037508, -20037508, 20037508, 20037508)


def transform_rect_to_layer_crs(canvas, layer, rect):
    """Transform a rectangle from canvas CRS to layer CRS.

    Args:
        canvas: QgsMapCanvas
        layer: QgsVectorLayer
        rect: QgsRectangle in canvas CRS

    Returns:
        QgsRectangle: in layer CRS
    """
    if canvas.mapSettings().destinationCrs() != layer.crs():
        transform = QgsCoordinateTransform(
            canvas.mapSettings().destinationCrs(),
            layer.crs(),
            QgsProject.instance()
        )
        try:
            return transform.transformBoundingBox(rect)
        except QgsCsException:
            return rect
    return rect
