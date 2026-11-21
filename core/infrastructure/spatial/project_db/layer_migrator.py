# -*- coding: utf-8 -*-
"""Copy of QGIS vector layers into SpatiaLite tables (geometry + attributes)."""

from qgis.core import QgsWkbTypes
from qgis.PyQt.QtCore import QVariant
from ....application.errors import OperationCancelled


class LayerMigrationMixin:
    """Migrates QGIS layers into the project database."""

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

                    try:
                        cursor.execute(insert_sql, python_attrs + [geom_wkt, srid])
                        stats['inserted'] += 1
                    except Exception:
                        # Fallback: drop Z values and retry (handles 3D geometries)
                        try:
                            geom_2d = feature.geometry()
                            geom_2d.get().dropZValue()
                            geom_wkt_2d = geom_2d.asWkt()
                            cursor.execute(insert_sql, python_attrs + [geom_wkt_2d, srid])
                            stats['inserted'] += 1
                        except Exception as e2:
                            print(f"Error inserting feature {idx} (2D fallback failed): {e2}")
                            stats['errors'] += 1

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
            except OperationCancelled:
                raise   # user cancelled: stop, don't record as a layer error
            except Exception as e:
                all_stats.append({
                    'table_name': self.sanitize_table_name(layer_name),
                    'error': str(e),
                    'inserted': 0,
                    'errors': 0
                })

        return all_stats

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
