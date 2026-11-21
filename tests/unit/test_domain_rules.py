# -*- coding: utf-8 -*-
"""Unit tests for core/domain/rules (pure Python, no QGIS)."""

import unittest

from core.domain.rules import naming, complexity, coverage


class NamingTest(unittest.TestCase):

    def test_version_of_and_defaults(self):
        self.assertEqual(naming.version_of("proj__assess__v12"), 12)
        self.assertIsNone(naming.version_of("proj__assess"))
        self.assertEqual(naming.version_of("proj__assess", default=1), 1)
        self.assertEqual(naming.version_of("x__v1__v2"), 2)
        self.assertIsNone(naming.version_of("x_v3"))      # needs the double underscore

    def test_strip_and_build_round_trip(self):
        for version in (1, 2, 10):
            name = naming.versioned_name("demo__overlay", version)
            self.assertEqual(name, f"demo__overlay__v{version}")
            self.assertEqual(naming.strip_version(name), "demo__overlay")
            self.assertEqual(naming.version_of(name), version)
        self.assertEqual(naming.step_table_name("demo__overlay", 0), "demo__overlay__step_0_tmp")

    def test_sanitize_table_name(self):
        self.assertEqual(naming.sanitize_table_name("Río Negro"), "r_o_negro")
        self.assertEqual(naming.sanitize_table_name("Demo__Overlay"), "demo__overlay")
        self.assertEqual(naming.sanitize_table_name("a___b"), "a__b")      # keeps separator
        self.assertEqual(naming.sanitize_table_name("9layer"), "layer_9layer")
        self.assertEqual(naming.sanitize_table_name("___"), "unnamed_layer")

    def test_sanitize_file_name_is_a_different_rule(self):
        # project DB file names: no underscore collapsing, no digit prefix
        self.assertEqual(naming.sanitize_file_name("a___b"), "a___b")
        self.assertEqual(naming.sanitize_file_name("9layer"), "9layer")
        self.assertEqual(naming.sanitize_file_name("!!"), "unnamed")


class ComplexityTest(unittest.TestCase):

    def test_simple(self):
        r = complexity.classify_assessment('Polygon', [], 0)
        self.assertTrue(r['is_simple'])
        self.assertEqual(r['operation_type'], 'none')

    def test_easy_complex_polygons(self):
        r = complexity.classify_assessment('Polygon', ['Polygon'], 1)
        self.assertTrue(r['is_easy_complex'])
        self.assertEqual(r['operation_type'], 'both')
        self.assertTrue(r['requires_union'] and r['requires_intersect'])

    def test_super_complex(self):
        r = complexity.classify_assessment('Polygon', ['Polygon', 'Polygon'], 0)
        self.assertTrue(r['is_super_complex'])

    def test_marker_only_is_easy_complex_without_operations(self):
        r = complexity.classify_assessment('Polygon', [], 1)
        self.assertTrue(r['is_easy_complex'])
        self.assertEqual(r['valid_operations'], [])

    def test_operations_matrix(self):
        self.assertEqual(complexity.overlay_operations('Point', 'Point')['operation_type'], 'union')
        self.assertIsNotNone(complexity.overlay_operations('Line', 'Line')['geometry_warning'])
        self.assertEqual(complexity.overlay_operations('Polygon', 'Line')['operation_type'], 'intersect')


class CoverageTest(unittest.TestCase):

    def test_thresholds(self):
        self.assertEqual(coverage.coverage_class(0, 0), coverage.CLASS_NO_DATA)
        self.assertEqual(coverage.coverage_class(4, 3), coverage.CLASS_HIGH)        # 75 %
        self.assertEqual(coverage.coverage_class(4, 1), coverage.CLASS_MEDIUM)      # 25 %
        self.assertEqual(coverage.coverage_class(4, 0.5), coverage.CLASS_LOW)
        self.assertEqual(coverage.coverage_class(4, 0), coverage.CLASS_NONE)

    def test_labels_match_results_grid(self):
        self.assertEqual(coverage.CLASS_HIGH, 'High (>=75%)')
        self.assertEqual(coverage.CLASS_MEDIUM, 'Medium (25-74%)')
        self.assertEqual(coverage.CLASS_LOW, 'Low (<25%)')


if __name__ == '__main__':
    unittest.main()
