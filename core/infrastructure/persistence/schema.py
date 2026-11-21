# -*- coding: utf-8 -*-
"""admin.sqlite schema: table creation, incremental column migrations and
removal of legacy tables. Run on every AdminManager.connect() (idempotent).
"""


class SchemaMixin:
    """Creates and migrates the admin.sqlite schema."""

    def _create_tables(self):
        """Create all admin tables if they do not exist (new-database schema)."""
        cursor = self.connection.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL UNIQUE,
                description TEXT DEFAULT '',
                db_path TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                is_deleted INTEGER DEFAULT 0,
                base_layer_names TEXT DEFAULT '',
                db_type TEXT DEFAULT 'spatialite',
                qgs_project_file TEXT DEFAULT '',
                db_connection_string TEXT DEFAULT '',
                workspace_paths TEXT DEFAULT ''
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS assessments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid TEXT UNIQUE NOT NULL,
                project_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                target_layer TEXT DEFAULT '',
                spatial_extent TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                is_deleted INTEGER DEFAULT 0,
                UNIQUE(project_id, name),
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS assessment_layers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assessment_id INTEGER NOT NULL,
                layer_name TEXT NOT NULL,
                layer_type TEXT NOT NULL CHECK(layer_type IN ('input', 'output', 'reference')),
                geometry_type TEXT DEFAULT '',
                FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS layer_visibility_state (
                assessment_id INTEGER NOT NULL,
                layer_name TEXT NOT NULL,
                visible INTEGER DEFAULT 1,
                PRIMARY KEY (assessment_id, layer_name),
                FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS provenance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid TEXT UNIQUE NOT NULL,
                assessment_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS task_details (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid TEXT UNIQUE NOT NULL,
                provenance_id INTEGER NOT NULL,
                parent_task_id INTEGER DEFAULT NULL,
                step_order INTEGER NOT NULL,
                operation TEXT NOT NULL,
                category TEXT DEFAULT '',
                input_tables TEXT DEFAULT '',
                output_tables TEXT DEFAULT '',
                db_type TEXT DEFAULT 'spatialite',
                added_to_map INTEGER DEFAULT 1,
                scenario TEXT DEFAULT '',
                symbology TEXT DEFAULT '',
                duration_ms INTEGER DEFAULT 0,
                parameters TEXT DEFAULT '',
                comments TEXT DEFAULT '',
                engine_type TEXT DEFAULT 'spatialite',
                is_scenario INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (provenance_id) REFERENCES provenance(id) ON DELETE CASCADE,
                FOREIGN KEY (parent_task_id) REFERENCES task_details(id) ON DELETE SET NULL
            )
        """)

        # App settings — single-row config table (EMDS 8 adaptation)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                plugin_version TEXT DEFAULT '',
                default_project_dir TEXT DEFAULT '',
                default_base_layers_group TEXT DEFAULT 'Base Layers',
                output_group_name TEXT DEFAULT 'Output Layers',
                symbology_defaults TEXT DEFAULT '',
                misc TEXT DEFAULT ''
            )
        """)
        cursor.execute("INSERT OR IGNORE INTO app_settings (id) VALUES (1)")

        # ── Analysis tables ───────────────────────────────────────────────

        # assessment_criteria — separates layer (data) from criterion (model)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS assessment_criteria (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assessment_id INTEGER NOT NULL,
                layer_name TEXT NOT NULL,
                criterion_name TEXT NOT NULL,
                criterion_type TEXT DEFAULT 'weighted',
                normalization_method TEXT DEFAULT 'minmax',
                weight_default REAL DEFAULT 0.0,
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE CASCADE
            )
        """)

        # analyses — one row per scenario/version, replaces analysis_configurations
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS analyses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assessment_id INTEGER NOT NULL,
                name TEXT DEFAULT 'Default',
                model_type TEXT DEFAULT 'weighted_sum',
                score_column TEXT DEFAULT 'MCDA_SCORE',
                status TEXT DEFAULT 'valid',
                weights_json TEXT DEFAULT '{}',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE CASCADE
            )
        """)

        # analysis_weights — normalized weight per analysis × criterion
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS analysis_weights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_id INTEGER NOT NULL,
                criterion_id INTEGER NOT NULL,
                weight REAL DEFAULT 0.0,
                normalized_weight REAL DEFAULT 0.0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (analysis_id) REFERENCES analyses(id) ON DELETE CASCADE,
                FOREIGN KEY (criterion_id) REFERENCES assessment_criteria(id) ON DELETE CASCADE
            )
        """)

        # analysis_results — metadata about overlay outputs (geometry lives in SpatiaLite)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS analysis_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_id INTEGER NOT NULL,
                output_table TEXT NOT NULL,
                output_layer_name TEXT DEFAULT '',
                feature_count INTEGER DEFAULT 0,
                min_score REAL DEFAULT 0.0,
                max_score REAL DEFAULT 0.0,
                mean_score REAL DEFAULT 0.0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (analysis_id) REFERENCES analyses(id) ON DELETE CASCADE
            )
        """)

        # portfolios — Portfolio (LPA) configurations built on an overlay
        # result. No solver yet: rows are stored with status 'pending'.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS portfolios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assessment_id INTEGER NOT NULL,
                source_table TEXT NOT NULL,
                name TEXT NOT NULL,
                config_json TEXT DEFAULT '{}',
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (assessment_id, name),
                FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE CASCADE
            )
        """)

        self.connection.commit()
        cursor.close()

    def _migrate_schema(self):
        """Apply incremental schema migrations for existing databases (idempotent).

        Each ALTER TABLE is wrapped in try/except so it is safe to call on
        both new and previously-existing databases.
        """
        migrations = [
            # (table, column, definition)
            ("projects",      "is_deleted",           "INTEGER DEFAULT 0"),
            ("projects",      "base_layer_names",     "TEXT DEFAULT ''"),
            ("projects",      "db_type",              "TEXT DEFAULT 'spatialite'"),
            ("projects",      "qgs_project_file",     "TEXT DEFAULT ''"),
            ("projects",      "db_connection_string", "TEXT DEFAULT ''"),
            ("projects",      "workspace_paths",      "TEXT DEFAULT ''"),
            ("assessments",   "is_deleted",           "INTEGER DEFAULT 0"),
            ("task_details",  "engine_type",          "TEXT DEFAULT 'spatialite'"),
            ("task_details",  "is_scenario",          "INTEGER DEFAULT 0"),
        ]
        cursor = self.connection.cursor()
        for table, column, definition in migrations:
            try:
                cursor.execute(
                    f'ALTER TABLE {table} ADD COLUMN {column} {definition}'
                )
            except Exception:
                pass  # column already exists — skip silently
        self.connection.commit()
        cursor.close()

    def _drop_unused_tables(self):
        """Drop legacy/unused tables from existing databases (idempotent)."""
        cursor = self.connection.cursor()
        for table in ('spatial_references', 'analysis_comparisons',
                      'workflow_steps', 'analysis_configurations'):
            cursor.execute(f"DROP TABLE IF EXISTS {table}")
        self.connection.commit()
        cursor.close()
