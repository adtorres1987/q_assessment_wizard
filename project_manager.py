# -*- coding: utf-8 -*-
"""
Project Manager Module
Manages per-project SpatiaLite databases for spatial data storage.
Replaces database_manager.py (PostgreSQL/PostGIS) with SQLite/SpatiaLite.
"""

import sqlite3
import re
import os

from qgis.core import QgsWkbTypes
from PyQt5.QtCore import QVariant


class ProjectManager:
    """Manages a per-project SpatiaLite database for spatial data."""

    def __init__(self, db_path):
        """
        Initialize project manager.

        Args:
            db_path: Absolute path to the project's .sqlite file
        """
        self.db_path = db_path
        self.connection = None

    # ------------------------------------------------------------------ #
    #  Connection
    # ------------------------------------------------------------------ #

    def connect(self):
        """Open SpatiaLite connection. Creates DB and initializes spatial metadata if new."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        is_new_db = not os.path.exists(self.db_path)

        self.connection = sqlite3.connect(self.db_path)
        self.connection.execute("PRAGMA foreign_keys = ON")

        # Load SpatiaLite extension
        self.connection.enable_load_extension(True)
        self._load_spatialite()

        # Initialize spatial metadata for new databases
        if is_new_db:
            self.connection.execute("SELECT InitSpatialMetaData(1)")
            self.connection.commit()

        self._create_tables()

    def disconnect(self):
        """Close the SpatiaLite connection."""
        if self.connection:
            self.connection.close()
            self.connection = None

    def _create_tables(self):
        """Create registry tables if they do not exist."""
        cursor = self.connection.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS base_layers_registry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                layer_name TEXT UNIQUE NOT NULL,
                geometry_type TEXT DEFAULT '',
                srid INTEGER DEFAULT 4326,
                source TEXT DEFAULT '',
                feature_count INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS assessment_results_metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assessment_uuid TEXT NOT NULL,
                output_layer TEXT NOT NULL,
                operation TEXT NOT NULL,
                source_target TEXT DEFAULT '',
                source_assessment TEXT DEFAULT '',
                feature_count INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        self.connection.commit()
        cursor.close()

    # ------------------------------------------------------------------ #
    #  Base Layers Registry
    # ------------------------------------------------------------------ #

    def register_base_layer(self, layer_name, geometry_type="", srid=4326,
                            source="", feature_count=0):
        """Register a base layer in the registry."""
        cursor = self.connection.cursor()
        cursor.execute(
            """INSERT OR REPLACE INTO base_layers_registry
               (layer_name, geometry_type, srid, source, feature_count)
               VALUES (?, ?, ?, ?, ?)""",
            (layer_name, geometry_type, srid, source, feature_count)
        )
        self.connection.commit()
        cursor.close()

    def get_registered_layers(self):
        """Return list of dicts with all registered base layers."""
        cursor = self.connection.cursor()
        cursor.execute(
            """SELECT id, layer_name, geometry_type, srid, source, feature_count, created_at
               FROM base_layers_registry ORDER BY layer_name"""
        )
        rows = cursor.fetchall()
        cursor.close()
        return [
            {
                'id': r[0], 'layer_name': r[1], 'geometry_type': r[2],
                'srid': r[3], 'source': r[4], 'feature_count': r[5],
                'created_at': r[6]
            }
            for r in rows
        ]

    def is_layer_registered(self, layer_name):
        """Return True if a layer with this name is registered."""
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT 1 FROM base_layers_registry WHERE layer_name = ?",
            (layer_name,)
        )
        exists = cursor.fetchone() is not None
        cursor.close()
        return exists

    def unregister_layer(self, layer_name):
        """Remove a layer from the registry."""
        cursor = self.connection.cursor()
        cursor.execute(
            "DELETE FROM base_layers_registry WHERE layer_name = ?",
            (layer_name,)
        )
        self.connection.commit()
        cursor.close()

    # ------------------------------------------------------------------ #
    #  Table operations
    # ------------------------------------------------------------------ #

    def table_exists(self, table_name):
        """Check if a table exists in the database."""
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,)
        )
        exists = cursor.fetchone() is not None
        cursor.close()
        return exists

    def drop_table(self, table_name):
        """Drop a table and clean up its geometry registration."""
        cursor = self.connection.cursor()
        # Remove from SpatiaLite geometry_columns
        try:
            cursor.execute(
                "SELECT DiscardGeometryColumn(?, 'geom')",
                (table_name,)
            )
        except Exception:
            pass
        # Remove spatial index if exists
        try:
            cursor.execute(
                "SELECT DisableSpatialIndex(?, 'geom')",
                (table_name,)
            )
            cursor.execute(f"DROP TABLE IF EXISTS idx_{table_name}_geom")
        except Exception:
            pass
        cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
        self.connection.commit()
        cursor.close()

    def get_table_srid(self, table_name):
        """Get the SRID of a table's geometry column."""
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT srid FROM geometry_columns WHERE f_table_name = ? AND f_geometry_column = 'geom'",
            (table_name,)
        )
        row = cursor.fetchone()
        cursor.close()
        return row[0] if row else None

    def get_table_geometry_type(self, table_name):
        """Get the geometry type of a table."""
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT geometry_type FROM geometry_columns WHERE f_table_name = ? AND f_geometry_column = 'geom'",
            (table_name,)
        )
        row = cursor.fetchone()
        cursor.close()
        if row:
            # SpatiaLite stores geometry_type as integer code
            return self._geometry_type_int_to_str(row[0])
        return None

    # ------------------------------------------------------------------ #
    #  Layer migration (QGIS → SpatiaLite)
    # ------------------------------------------------------------------ #

    def migrate_layer(self, layer, table_name=None, progress_callback=None):
        """
        Migrate a QGIS vector layer into SpatiaLite.

        Args:
            layer: QgsVectorLayer to migrate
            table_name: Optional table name (defaults to sanitized layer name)
            progress_callback: Optional callback(current, total, message)

        Returns:
            dict: Stats {inserted, errors, table_name}
        """
        if not self.connection:
            raise Exception("Not connected to database. Call connect() first.")

        if not table_name:
            table_name = self.sanitize_table_name(layer.name())

        stats = {'inserted': 0, 'errors': 0, 'table_name': table_name}

        try:
            srid = layer.crs().postgisSrid()
            geometry_type = self.get_spatialite_type(layer)
            dimension = 'XYZ' if 'Z' in geometry_type else 'XY'
            # Normalize type for AddGeometryColumn (remove Z suffix)
            geom_type_clean = geometry_type.replace('Z', '')

            # Drop existing table if it exists
            if self.table_exists(table_name):
                self.drop_table(table_name)

            cursor = self.connection.cursor()

            # Create table WITHOUT geometry (SpatiaLite requires AddGeometryColumn)
            columns = ["id INTEGER PRIMARY KEY AUTOINCREMENT"]
            field_names = []
            for field in layer.fields():
                fname = field.name().lower()
                ftype = self._get_sqlite_type(field)
                columns.append(f'"{fname}" {ftype}')
                field_names.append(fname)

            create_sql = f"CREATE TABLE {table_name} ({', '.join(columns)})"
            cursor.execute(create_sql)
            self.connection.commit()

            # Add geometry column via SpatiaLite
            cursor.execute(
                f"SELECT AddGeometryColumn('{table_name}', 'geom', {srid}, '{geom_type_clean}', '{dimension}')"
            )
            self.connection.commit()

            # Insert features
            total_features = layer.featureCount()
            quoted_fields = ', '.join([f'"{fn}"' for fn in field_names])
            placeholders = ', '.join(['?'] * len(field_names))
            insert_sql = (
                f"INSERT INTO {table_name} ({quoted_fields}, geom) "
                f"VALUES ({placeholders}, GeomFromText(?, ?))"
            )

            for idx, feature in enumerate(layer.getFeatures()):
                try:
                    if progress_callback:
                        progress_callback(
                            idx + 1, total_features,
                            f"Processing feature {idx + 1}/{total_features}"
                        )

                    geometry = feature.geometry()
                    if geometry.isNull():
                        stats['errors'] += 1
                        continue

                    geom_wkt = geometry.asWkt()
                    attributes = feature.attributes()
                    python_attrs = [self._convert_qvariant(attr) for attr in attributes]

                    cursor.execute(insert_sql, python_attrs + [geom_wkt, srid])
                    stats['inserted'] += 1

                except Exception as e:
                    print(f"Error processing feature {idx}: {e}")
                    stats['errors'] += 1

            self.connection.commit()

            # Create spatial index
            try:
                cursor.execute(
                    f"SELECT CreateSpatialIndex('{table_name}', 'geom')"
                )
                self.connection.commit()
            except Exception as e:
                print(f"Note: Could not create spatial index for {table_name}: {e}")

            cursor.close()

            # Register in base_layers_registry
            self.register_base_layer(
                layer_name=table_name,
                geometry_type=geometry_type,
                srid=srid,
                source=layer.source(),
                feature_count=stats['inserted']
            )

        except Exception as e:
            raise Exception(f"Migration error: {e}")

        return stats

    def migrate_layers(self, layers_dict, progress_callback=None):
        """
        Migrate multiple QGIS layers to SpatiaLite.

        Args:
            layers_dict: Dict mapping layer names to QgsVectorLayer objects
            progress_callback: Optional callback(layer_index, total, layer_name, message)

        Returns:
            list: List of stats dicts for each layer
        """
        all_stats = []
        total_layers = len(layers_dict)

        for idx, (layer_name, layer) in enumerate(layers_dict.items()):
            try:
                if progress_callback:
                    progress_callback(
                        idx, total_layers, layer_name,
                        f"Migrating layer {idx + 1}/{total_layers}: {layer_name}"
                    )
                stats = self.migrate_layer(layer)
                all_stats.append(stats)
            except Exception as e:
                all_stats.append({
                    'table_name': self.sanitize_table_name(layer_name),
                    'error': str(e),
                    'inserted': 0,
                    'errors': 0
                })

        return all_stats

    # ------------------------------------------------------------------ #
    #  Assessment Results
    # ------------------------------------------------------------------ #

    def record_result(self, assessment_uuid, output_layer, operation,
                      source_target="", source_assessment="", feature_count=0):
        """Record an assessment result in the metadata table."""
        cursor = self.connection.cursor()
        cursor.execute(
            """INSERT INTO assessment_results_metadata
               (assessment_uuid, output_layer, operation,
                source_target, source_assessment, feature_count)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (assessment_uuid, output_layer, operation,
             source_target, source_assessment, feature_count)
        )
        self.connection.commit()
        cursor.close()

    def get_results_for_assessment(self, assessment_uuid):
        """Return list of result dicts for a given assessment UUID."""
        cursor = self.connection.cursor()
        cursor.execute(
            """SELECT id, assessment_uuid, output_layer, operation,
                      source_target, source_assessment, feature_count, created_at
               FROM assessment_results_metadata
               WHERE assessment_uuid = ? ORDER BY id""",
            (assessment_uuid,)
        )
        rows = cursor.fetchall()
        cursor.close()
        return [
            {
                'id': r[0], 'assessment_uuid': r[1], 'output_layer': r[2],
                'operation': r[3], 'source_target': r[4],
                'source_assessment': r[5], 'feature_count': r[6],
                'created_at': r[7]
            }
            for r in rows
        ]

    # ------------------------------------------------------------------ #
    #  Utilities
    # ------------------------------------------------------------------ #

    def _load_spatialite(self):
        """Load the SpatiaLite extension, trying multiple paths."""
        # 1. Try QGIS built-in finder (works inside QGIS on all platforms)
        try:
            from qgis.utils import spatialite_connect
            # If qgis.utils has spatialite_connect, use its approach
            self.connection.load_extension("mod_spatialite")
            return
        except Exception:
            pass

        # 2. Try QGIS Mac Packager's finder
        try:
            from qgis.find_mod_spatialite import mod_spatialite_path
            path = mod_spatialite_path()
            self.connection.load_extension(path)
            return
        except Exception:
            pass

        # 3. Try common macOS QGIS paths
        mac_paths = [
            "/Applications/QGIS.app/Contents/MacOS/lib/mod_spatialite.7.so",
            "/Applications/QGIS.app/Contents/MacOS/lib/mod_spatialite.so",
            "/Applications/QGIS-LTR.app/Contents/MacOS/lib/mod_spatialite.7.so",
            "/Applications/QGIS-LTR.app/Contents/MacOS/lib/mod_spatialite.so",
        ]
        for path in mac_paths:
            if os.path.exists(path):
                try:
                    self.connection.load_extension(path)
                    return
                except Exception:
                    continue

        # 4. Try generic name (Linux, or if in PATH)
        try:
            self.connection.load_extension("mod_spatialite")
            return
        except Exception as e:
            raise Exception(
                f"Could not load SpatiaLite extension: {e}\n"
                "Make sure SpatiaLite is installed and accessible."
            )

    def sanitize_table_name(self, layer_name):
        """Convert layer name to valid SQLite table name.
        Preserves __ as separator between project and assessment names.
        """
        table_name = re.sub(r'[^a-zA-Z0-9_]', '_', layer_name)
        table_name = table_name.lower()
        # Remove 3+ consecutive underscores (preserves __ as separator)
        table_name = re.sub(r'_{3,}', '__', table_name)
        table_name = table_name.strip('_')
        if table_name and table_name[0].isdigit():
            table_name = 'layer_' + table_name
        return table_name if table_name else 'unnamed_layer'

    def get_spatialite_type(self, layer):
        """Map QGIS layer geometry to SpatiaLite geometry type string."""
        wkb_type = layer.wkbType()
        geom_type_name = QgsWkbTypes.displayString(wkb_type)

        type_mapping = {
            'Point': 'POINT',
            'MultiPoint': 'MULTIPOINT',
            'LineString': 'LINESTRING',
            'MultiLineString': 'MULTILINESTRING',
            'Polygon': 'POLYGON',
            'MultiPolygon': 'MULTIPOLYGON',
            'PointZ': 'POINTZ',
            'MultiPointZ': 'MULTIPOINTZ',
            'LineStringZ': 'LINESTRINGZ',
            'MultiLineStringZ': 'MULTILINESTRINGZ',
            'PolygonZ': 'POLYGONZ',
            'MultiPolygonZ': 'MULTIPOLYGONZ',
        }

        return type_mapping.get(geom_type_name, 'GEOMETRY')

    def _get_sqlite_type(self, field):
        """Map QGIS field type to SQLite type."""
        type_name = field.typeName().upper()

        type_mapping = {
            'INTEGER': 'INTEGER',
            'INTEGER64': 'INTEGER',
            'REAL': 'REAL',
            'DOUBLE': 'REAL',
            'STRING': 'TEXT',
            'DATE': 'TEXT',
            'TIME': 'TEXT',
            'DATETIME': 'TEXT',
            'BOOL': 'INTEGER',
            'BINARY': 'BLOB',
        }

        return type_mapping.get(type_name, 'TEXT')

    def _convert_qvariant(self, value):
        """Convert QVariant to native Python type."""
        if value is None:
            return None
        try:
            if isinstance(value, QVariant):
                if value.isNull():
                    return None
                return value.value()
            return value
        except Exception:
            return value

    def _geometry_type_int_to_str(self, type_int):
        """Convert SpatiaLite geometry type integer to string."""
        type_map = {
            1: 'POINT', 2: 'LINESTRING', 3: 'POLYGON',
            4: 'MULTIPOINT', 5: 'MULTILINESTRING', 6: 'MULTIPOLYGON',
            1001: 'POINTZ', 1002: 'LINESTRINGZ', 1003: 'POLYGONZ',
            1004: 'MULTIPOINTZ', 1005: 'MULTILINESTRINGZ', 1006: 'MULTIPOLYGONZ',
        }
        return type_map.get(type_int, 'GEOMETRY')
