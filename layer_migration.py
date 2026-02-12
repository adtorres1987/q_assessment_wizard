# -*- coding: utf-8 -*-
"""
Layer Migration Module
Handles migration of QGIS layers to SpatiaLite project databases.
"""

from qgis.PyQt.QtWidgets import QMessageBox, QProgressDialog
from qgis.PyQt.QtCore import Qt, QCoreApplication

from .project_manager import ProjectManager


class LayerMigrationService:
    """Handles migration of QGIS layers to SpatiaLite project databases."""

    def __init__(self, admin_manager, project_db_id):
        """
        Args:
            admin_manager: AdminManager instance
            project_db_id: int - project database ID
        """
        self.admin_manager = admin_manager
        self.project_db_id = project_db_id

    def get_project_db_path(self):
        """Resolve the absolute path to the project SpatiaLite database.

        Returns:
            str or None
        """
        return self.admin_manager.get_project_db_path(self.project_db_id)

    def migrate_selected_layers(self, layers_dict, parent_widget=None):
        """Migrate selected layers to the project SpatiaLite database.

        Args:
            layers_dict: dict mapping layer_name -> QgsVectorLayer
            parent_widget: QWidget for dialog parenting (optional)

        Returns:
            bool: True if migration succeeded or was skipped, False on failure
        """
        try:
            project_db_path = self.get_project_db_path()
            if not project_db_path:
                QMessageBox.critical(
                    parent_widget,
                    "Database Error",
                    "Project database path not found."
                )
                return False

            pm = ProjectManager(project_db_path)
            try:
                pm.connect()
            except Exception as e:
                QMessageBox.critical(
                    parent_widget,
                    "Database Connection Error",
                    f"Failed to connect to project database:\n{str(e)}"
                )
                return False

            if not layers_dict:
                QMessageBox.information(
                    parent_widget,
                    "Migration Info",
                    "No layers selected for migration."
                )
                pm.disconnect()
                return True

            # Check for existing tables and ask user
            existing_tables = []
            for layer_name in layers_dict.keys():
                table_name = pm.sanitize_table_name(layer_name)
                if pm.table_exists(table_name):
                    existing_tables.append(layer_name)

            if existing_tables:
                tables_list = "\n".join([f"• {name}" for name in existing_tables])
                message = f"The following tables already exist in the database:\n\n{tables_list}\n\n"
                message += "Do you want to overwrite these layers?"

                reply = QMessageBox.question(
                    parent_widget,
                    "Tables Already Exist",
                    message,
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )

                if reply == QMessageBox.No:
                    for layer_name in existing_tables:
                        del layers_dict[layer_name]

                    if not layers_dict:
                        QMessageBox.information(
                            parent_widget,
                            "Migration Cancelled",
                            "No new layers to migrate."
                        )
                        pm.disconnect()
                        return True

            # Create progress dialog
            progress = QProgressDialog(
                "Migrating layers to SpatiaLite...", "Cancel",
                0, len(layers_dict), parent_widget
            )
            progress.setWindowTitle("Database Migration")
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(0)
            progress.setValue(0)

            def progress_callback(layer_index, total_layers, layer_name, message):
                progress.setLabelText(message)
                progress.setValue(layer_index)
                QCoreApplication.processEvents()

                if progress.wasCanceled():
                    raise Exception("Migration cancelled by user")

            all_stats = pm.migrate_layers(layers_dict, progress_callback)

            progress.setValue(len(layers_dict))

            # Process results
            total_stats = {'inserted': 0, 'errors': 0}
            failed_layers = []

            for stats in all_stats:
                if 'error' in stats:
                    failed_layers.append(f"{stats['table_name']}: {stats['error']}")
                else:
                    total_stats['inserted'] += stats['inserted']
                    total_stats['errors'] += stats['errors']

            if failed_layers:
                QMessageBox.warning(
                    parent_widget,
                    "Migration Completed with Errors",
                    f"Some layers failed to migrate:\n\n" + "\n".join(failed_layers)
                )
            else:
                summary = f"Successfully migrated {len(layers_dict)} layer(s) to SpatiaLite:\n\n"
                summary += f"Total features inserted: {total_stats['inserted']}\n"
                if total_stats['errors'] > 0:
                    summary += f"Total errors: {total_stats['errors']}"

                QMessageBox.information(
                    parent_widget,
                    "Migration Successful",
                    summary
                )

            pm.disconnect()
            return True

        except Exception as e:
            if 'cancelled by user' in str(e).lower():
                QMessageBox.information(
                    parent_widget,
                    "Migration Cancelled",
                    "Migration cancelled by user."
                )
            else:
                QMessageBox.critical(
                    parent_widget,
                    "Migration Error",
                    f"An error occurred during migration:\n{str(e)}"
                )
            return False
