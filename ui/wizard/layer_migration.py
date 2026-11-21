# -*- coding: utf-8 -*-
"""
LayerMigrationService — UI flow for copying the wizard's layers into the
project SpatiaLite database.

Owns the dialogs (overwrite confirmation, progress with Cancel, result
summary); the work itself goes through AssessmentExecutor → FindExistingLayers
/ MigrateLayers use cases.
"""

from qgis.PyQt.QtWidgets import QMessageBox, QProgressDialog
from qgis.PyQt.QtCore import Qt, QCoreApplication

from ...core.application import OperationCancelled
from ..i18n.translator import tr


class LayerMigrationService:
    """Interactive migration of selected layers to SpatiaLite."""

    def __init__(self, executor):
        """
        Args:
            executor: AssessmentExecutor of the target project.
        """
        self._executor = executor

    def migrate_selected_layers(self, layers_dict, parent_widget=None):
        """Migrate selected layers to the project SpatiaLite database.

        Args:
            layers_dict: dict mapping layer_name -> QgsVectorLayer
            parent_widget: QWidget for dialog parenting (optional)

        Returns:
            bool: True if migration succeeded or was skipped, False on failure
        """
        if not layers_dict:
            QMessageBox.information(parent_widget, tr('dialog.mig_info_title'),
                                    tr('dialog.mig_no_layers'))
            return True

        layers_dict = dict(layers_dict)
        try:
            existing = self._executor.existing_layers(layers_dict)
        except RuntimeError:
            QMessageBox.critical(parent_widget, tr('dialog.err_db_path_title'),
                                 tr('dialog.err_db_path_body'))
            return False
        except Exception as e:
            QMessageBox.critical(parent_widget, tr('dialog.err_db_title'),
                                 tr('dialog.err_db_body', error=str(e)))
            return False

        if existing:
            tables_list = "\n".join(f"• {name}" for name in existing)
            reply = QMessageBox.question(
                parent_widget,
                tr('dialog.mig_exists_title'),
                tr('dialog.mig_overwrite_body', tables=tables_list),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                for layer_name in existing:
                    del layers_dict[layer_name]
                if not layers_dict:
                    QMessageBox.information(parent_widget, tr('dialog.mig_cancelled_title'),
                                            tr('dialog.mig_no_new_layers'))
                    return True

        progress = QProgressDialog(tr('dialog.prog_migrating'), tr('dialog.btn_cancel'),
                                   0, len(layers_dict), parent_widget)
        progress.setWindowTitle(tr('dialog.prog_db_migration'))
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        def progress_callback(layer_index, total_layers, layer_name, message):
            progress.setLabelText(message)
            progress.setValue(layer_index)
            QCoreApplication.processEvents()
            if progress.wasCanceled():
                raise OperationCancelled()

        try:
            summary = self._executor.migrate_layers(layers_dict, progress_callback)
        except OperationCancelled:
            progress.close()
            QMessageBox.information(parent_widget, tr('dialog.mig_user_cancel_title'),
                                    tr('dialog.mig_user_cancel_body'))
            return False
        except Exception as e:
            progress.close()
            QMessageBox.critical(parent_widget, tr('dialog.mig_err_title'),
                                 tr('dialog.mig_err_body', error=str(e)))
            return False

        progress.setValue(len(layers_dict))

        if summary['failed']:
            QMessageBox.warning(parent_widget, tr('dialog.mig_error_title'),
                                tr('dialog.mig_error_body', errors="\n".join(summary['failed'])))
        else:
            text = tr('dialog.mig_success_short', count=len(layers_dict),
                      inserted=summary['inserted'])
            if summary['errors'] > 0:
                text += tr('dialog.mig_success_errors', errors=summary['errors'])
            QMessageBox.information(parent_widget, tr('dialog.mig_success_title'), text)
        return True
