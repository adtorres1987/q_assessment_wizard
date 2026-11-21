# -*- coding: utf-8 -*-
"""
Assessment complexity classification.

Pure Python — no QGIS. Geometry categories are plain strings:
'Point', 'Line', 'Polygon' or 'Unknown'.

Rules:
  - No assessment layers and no spatial markers → simple assessment.
  - 1 assessment layer and at most 1 marker      → easy complex.
  - More than 1 assessment layer or marker        → super complex.
  - Otherwise (only 1 marker)                     → easy complex.

Valid overlay operations depend on the target geometry and the geometry of
the first assessment layer (see :func:`overlay_operations`).
"""


def overlay_operations(target_geometry, assessment_geometry):
    """Operations allowed for a target/assessment geometry combination.

    Returns:
        dict: valid_operations, requires_union, requires_intersect,
              operation_type ('intersect' | 'union' | 'both'),
              geometry_warning (str or None).
    """
    if target_geometry == 'Polygon' and assessment_geometry == 'Polygon':
        return {'valid_operations': ['intersect', 'union', 'both'],
                'requires_intersect': True, 'requires_union': True,
                'operation_type': 'both', 'geometry_warning': None}
    if target_geometry == 'Point' and assessment_geometry == 'Point':
        return {'valid_operations': ['union'],
                'requires_intersect': False, 'requires_union': True,
                'operation_type': 'union',
                'geometry_warning': 'Union between Point layers is normally not useful'}
    if target_geometry == 'Line' and assessment_geometry == 'Line':
        return {'valid_operations': ['union'],
                'requires_intersect': False, 'requires_union': True,
                'operation_type': 'union',
                'geometry_warning': 'Union between Line layers is normally not useful'}
    return {'valid_operations': ['intersect'],
            'requires_intersect': True, 'requires_union': False,
            'operation_type': 'intersect', 'geometry_warning': None}


def classify_assessment(target_geometry, assessment_geometries, marker_count):
    """Classify an assessment from its layer configuration.

    Args:
        target_geometry:        geometry category of the target layer (or None).
        assessment_geometries:  geometry categories of the assessment layers,
                                in table order.
        marker_count:           number of spatial-marker layers.

    Returns:
        dict with is_simple, is_easy_complex, is_super_complex, operation_type,
        requires_union, requires_intersect, valid_operations,
        geometry_warning, target_geometry, assessment_geometry.
    """
    n_assessment = len(assessment_geometries)
    result = {
        'is_simple': False,
        'is_easy_complex': False,
        'is_super_complex': False,
        'operation_type': 'none',
        'requires_union': False,
        'requires_intersect': False,
        'valid_operations': [],
        'geometry_warning': None,
        'target_geometry': target_geometry,
        'assessment_geometry': None,
    }

    if n_assessment == 0 and marker_count == 0:
        result['is_simple'] = True
        return result

    if assessment_geometries:
        result['assessment_geometry'] = assessment_geometries[0]
        result.update(overlay_operations(target_geometry, assessment_geometries[0]))

    if n_assessment == 1 and marker_count <= 1:
        result['is_easy_complex'] = True
    elif n_assessment > 1 or marker_count > 1:
        result['is_super_complex'] = True
    else:
        result['is_easy_complex'] = True
    return result
