# -*- coding: utf-8 -*-
"""
Geometry Utilities Module
Shared helper functions for CRS transformation, geometry categorization,
and assessment complexity detection.
"""

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsPointXY, QgsRectangle,
    QgsWkbTypes, QgsCoordinateTransform, QgsCoordinateReferenceSystem,
    QgsCsException
)

from .translator import tr

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


def get_geometry_category(layer):
    """Get the geometry category for a layer (Point, Line, or Polygon).

    Args:
        layer: QgsVectorLayer

    Returns:
        str: 'Point', 'Line', 'Polygon', or 'Unknown'
    """
    if not layer or not layer.isValid():
        return 'Unknown'

    geom_type = layer.geometryType()
    # QgsWkbTypes.GeometryType: 0=Point, 1=Line, 2=Polygon
    if geom_type == 0:
        return 'Point'
    elif geom_type == 1:
        return 'Line'
    elif geom_type == 2:
        return 'Polygon'
    else:
        return 'Unknown'


def detect_assessment_complexity(table_widget, status_constants):
    """Detect if this is a simple or complex assessment case.

    Args:
        table_widget: QTableWidget with layer rows
        status_constants: dict with keys 'STATUS_TARGET', 'STATUS_INCLUDE',
                         'STATUS_SPATIAL_MARKER', 'STATUS_DO_NOT_INCLUDE'

    Returns:
        dict: Complexity analysis result
    """
    result = {
        'is_simple': False,
        'is_easy_complex': False,
        'is_super_complex': False,
        'operation_type': 'none',
        'included_layers': [],
        'spatial_markers': [],
        'target_layer': None,
        'requires_union': False,
        'requires_intersect': False,
        'valid_operations': [],
        'geometry_warning': None,
        'target_geometry': None,
        'assessment_geometry': None
    }

    STATUS_TARGET = status_constants['STATUS_TARGET']
    STATUS_INCLUDE = status_constants['STATUS_INCLUDE']
    STATUS_SPATIAL_MARKER = status_constants['STATUS_SPATIAL_MARKER']

    # Collect layers by status
    for row in range(table_widget.rowCount()):
        layer_name_item = table_widget.item(row, 0)
        status_combo = table_widget.cellWidget(row, 2)

        if layer_name_item and status_combo:
            layer_name = layer_name_item.text()
            # Status combos store the language-independent key as item data.
            status = status_combo.currentData() or status_combo.currentText()

            layers = QgsProject.instance().mapLayersByName(layer_name)
            if layers and isinstance(layers[0], QgsVectorLayer):
                layer = layers[0]

                if status == STATUS_TARGET:
                    result['target_layer'] = layer
                    result['target_geometry'] = get_geometry_category(layer)
                elif status == STATUS_INCLUDE:
                    result['included_layers'].append(layer)
                elif status == STATUS_SPATIAL_MARKER:
                    result['spatial_markers'].append(layer)

    # Determine geometry types and valid operations
    num_assessment_layers = len(result['included_layers'])
    num_spatial_markers = len(result['spatial_markers'])
    target_geom = result['target_geometry']

    # Simple case: Only target layer, no additional assessment layers
    if num_assessment_layers == 0 and num_spatial_markers == 0:
        result['is_simple'] = True
        result['operation_type'] = 'none'
        result['valid_operations'] = []
        return result

    # Get assessment layer geometry (use first assessment layer for validation)
    if result['included_layers']:
        assessment_geom = get_geometry_category(result['included_layers'][0])
        result['assessment_geometry'] = assessment_geom

        # Geometry compatibility matrix
        _apply_geometry_operations(result, target_geom, assessment_geom)

    # Determine complexity level
    if num_assessment_layers == 1 and num_spatial_markers <= 1:
        result['is_easy_complex'] = True
    elif num_assessment_layers > 1 or num_spatial_markers > 1:
        result['is_super_complex'] = True
    else:
        result['is_easy_complex'] = True

    return result


def _apply_geometry_operations(result, target_geom, assessment_geom):
    """Apply valid operations based on geometry type combination."""
    # Polygon + Polygon -> Intersect / Union (both valid)
    if target_geom == 'Polygon' and assessment_geom == 'Polygon':
        result['valid_operations'] = ['intersect', 'union', 'both']
        result['requires_intersect'] = True
        result['requires_union'] = True
        result['operation_type'] = 'both'

    # Point + Point -> Union (normally not useful)
    elif target_geom == 'Point' and assessment_geom == 'Point':
        result['valid_operations'] = ['union']
        result['requires_union'] = True
        result['operation_type'] = 'union'
        result['geometry_warning'] = 'Union between Point layers is normally not useful'

    # Line + Line -> Union (normally not useful)
    elif target_geom == 'Line' and assessment_geom == 'Line':
        result['valid_operations'] = ['union']
        result['requires_union'] = True
        result['operation_type'] = 'union'
        result['geometry_warning'] = 'Union between Line layers is normally not useful'

    # All other combinations -> Intersect only
    else:
        result['valid_operations'] = ['intersect']
        result['requires_intersect'] = True
        result['operation_type'] = 'intersect'


def get_assessment_summary(table_widget, status_constants):
    """Get a human-readable summary of the assessment complexity.

    Args:
        table_widget: QTableWidget with layer rows
        status_constants: dict with keys 'STATUS_TARGET', 'STATUS_INCLUDE',
                         'STATUS_SPATIAL_MARKER', 'STATUS_DO_NOT_INCLUDE'

    Returns:
        str: Summary description of the assessment type
    """
    complexity = detect_assessment_complexity(table_widget, status_constants)

    if complexity['is_simple']:
        return tr('dialog.summary_simple')

    def _operations_line():
        if complexity['requires_union'] and complexity['requires_intersect']:
            return tr('dialog.summary_union_intersect')
        if complexity['requires_union']:
            return tr('dialog.summary_union')
        if complexity['requires_intersect']:
            return tr('dialog.summary_intersect')
        return None

    def _counts_lines():
        lines = []
        if complexity['included_layers']:
            lines.append(tr('dialog.summary_n_assess', count=len(complexity['included_layers'])))
        if complexity['spatial_markers']:
            lines.append(tr('dialog.summary_n_markers', count=len(complexity['spatial_markers'])))
        return lines

    if complexity['is_easy_complex']:
        parts = [tr('dialog.summary_easy_complex'),
                 tr('dialog.summary_one_assess'),
                 tr('dialog.summary_one_marker')]
    elif complexity['is_super_complex']:
        parts = [tr('dialog.summary_super_complex')] + _counts_lines()
    else:
        parts = [tr('dialog.summary_complex')] + _counts_lines()
        if complexity['operation_type'] != 'none':
            parts.append({
                'union': tr('dialog.summary_union'),
                'intersect': tr('dialog.summary_intersect'),
                'both': tr('dialog.summary_union_intersect'),
            }.get(complexity['operation_type'], tr('dialog.summary_op_spatial')))
        return "\n".join(parts)

    op_line = _operations_line()
    if op_line:
        parts.append(op_line)
    return "\n".join(parts)
