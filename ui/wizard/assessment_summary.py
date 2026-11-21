# -*- coding: utf-8 -*-
"""
Assessment complexity summary for the wizard.

Reads the page-1 layer table (status per layer), classifies the assessment
(simple / easy complex / super complex / complex) and renders a translated,
human-readable summary.
"""

from qgis.core import QgsProject, QgsVectorLayer

from ..i18n.translator import tr
from ...core.domain.rules.complexity import classify_assessment


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
    """Classify the assessment configured in the page-1 layer table.

    Collects the QGIS layers by status (the language-independent key stored
    as combo item data) and delegates the decision to the domain rule
    :func:`core.domain.rules.complexity.classify_assessment`.

    Args:
        table_widget: QTableWidget with layer rows
        status_constants: dict with keys 'STATUS_TARGET', 'STATUS_INCLUDE',
                         'STATUS_SPATIAL_MARKER', 'STATUS_DO_NOT_INCLUDE'

    Returns:
        dict: the domain classification plus 'target_layer',
              'included_layers' and 'spatial_markers' (QGIS layers).
    """
    target_layer = None
    included_layers = []
    spatial_markers = []

    for row in range(table_widget.rowCount()):
        layer_name_item = table_widget.item(row, 0)
        status_combo = table_widget.cellWidget(row, 2)
        if not (layer_name_item and status_combo):
            continue
        status = status_combo.currentData() or status_combo.currentText()
        layers = QgsProject.instance().mapLayersByName(layer_name_item.text())
        if not (layers and isinstance(layers[0], QgsVectorLayer)):
            continue
        if status == status_constants['STATUS_TARGET']:
            target_layer = layers[0]
        elif status == status_constants['STATUS_INCLUDE']:
            included_layers.append(layers[0])
        elif status == status_constants['STATUS_SPATIAL_MARKER']:
            spatial_markers.append(layers[0])

    result = classify_assessment(
        get_geometry_category(target_layer) if target_layer else None,
        [get_geometry_category(layer) for layer in included_layers],
        len(spatial_markers),
    )
    result.update(target_layer=target_layer,
                  included_layers=included_layers,
                  spatial_markers=spatial_markers)
    return result


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
