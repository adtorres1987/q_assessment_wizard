# -*- coding: utf-8 -*-
"""Table operations: existence, drop, rename (with geometry re-registration), temp cleanup."""


class TablesMixin:
    """Low-level table operations on the project database."""

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

    def rename_table(self, old_name, new_name):
        """Rename a SpatiaLite table, re-registering geometry and spatial index.

        Uses drop_table() on the original to properly clean all SpatiaLite
        metadata (geometry_columns + satellite tables), then re-registers
        geometry for the new table name with RecoverGeometryColumn.

        Args:
            old_name: Current table name
            new_name: New table name
        """
        cursor = self.connection.cursor()

        # Step 1: Read geometry registration from the source table
        cursor.execute(
            "SELECT srid, geometry_type, coord_dimension "
            "FROM geometry_columns WHERE f_table_name = ?",
            (old_name,)
        )
        row = cursor.fetchone()
        srid = row[0] if row else 4326
        geom_type_int = row[1] if row else 6   # default MULTIPOLYGON
        coord_dim_raw = row[2] if row else 'XY'
        cursor.close()

        # Convert geometry_type integer to string
        geom_type_str = self._geometry_type_int_to_str(geom_type_int)

        # Normalise coord_dimension: SpatiaLite stores 'XY', 'XYZ', 2, or 3
        if coord_dim_raw in (3, 'XYZ', 'xyz'):
            dimension = 'XYZ'
        else:
            dimension = 'XY'

        # Step 2: Copy all data to the new table name
        cursor = self.connection.cursor()
        cursor.execute(f"CREATE TABLE {new_name} AS SELECT * FROM {old_name}")
        self.connection.commit()
        cursor.close()

        # Step 3: Remove the original table and ALL its SpatiaLite metadata
        # drop_table() calls DiscardGeometryColumn + DisableSpatialIndex first,
        # which respects PRAGMA foreign_keys = ON.
        self.drop_table(old_name)

        # Step 4: Register geometry column for the new table name
        cursor = self.connection.cursor()
        registered = False
        for try_type in [geom_type_str, 'MULTIPOLYGON', 'POLYGON', 'GEOMETRY']:
            try:
                cursor.execute(
                    f"SELECT RecoverGeometryColumn('{new_name}', 'geom', "
                    f"{srid}, '{try_type}', '{dimension}')"
                )
                result = cursor.fetchone()
                self.connection.commit()
                if result and result[0] == 1:
                    registered = True
                    break
            except Exception:
                continue

        if not registered:
            print(f"Warning: Could not register geometry for '{new_name}' after rename.")

        # Step 5: Recreate spatial index on the new table
        try:
            cursor.execute(f"SELECT CreateSpatialIndex('{new_name}', 'geom')")
            self.connection.commit()
        except Exception as e:
            print(f"Note: Could not recreate spatial index for '{new_name}': {e}")

        cursor.close()

    def cleanup_temp_tables(self):
        """Drop temporary tables left from interrupted previous sessions.
        Targets tables matching the pattern *_tmp_*.
        """
        if not self.connection:
            return
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%_tmp_%'"
        )
        temp_tables = [row[0] for row in cursor.fetchall()]
        cursor.close()
        for table in temp_tables:
            self.drop_table(table)
            print(f"Cleanup: dropped temp table '{table}'")

    def _geometry_type_int_to_str(self, type_int):
        """Convert SpatiaLite geometry type integer to string."""
        type_map = {
            1: 'POINT', 2: 'LINESTRING', 3: 'POLYGON',
            4: 'MULTIPOINT', 5: 'MULTILINESTRING', 6: 'MULTIPOLYGON',
            1001: 'POINTZ', 1002: 'LINESTRINGZ', 1003: 'POLYGONZ',
            1004: 'MULTIPOINTZ', 1005: 'MULTILINESTRINGZ', 1006: 'MULTIPOLYGONZ',
        }
        return type_map.get(type_int, 'GEOMETRY')
