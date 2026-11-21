# -*- coding: utf-8 -*-
"""Wizard page 1 — name, duplicate/new-version check and validation
(target count, geometry compatibility) + layer migration on Next."""

from qgis.PyQt import QtWidgets
from qgis.core import QgsProject, QgsVectorLayer, QgsWkbTypes
from .layer_migration import LayerMigrationService
from ..i18n.translator import tr


class ConfigurationPageMixin:
    """Behaviour of page 1 (assessment configuration)."""

    def initialize_page_1(self):
        """Initialize the first wizard page."""
        self.populate_layers()
        self.lineEdit_name.editingFinished.connect(self._on_name_editing_finished)
        self.page_1.validatePage = self.validate_page_1

    def _on_name_editing_finished(self):
        """Check for duplicate assessment name as soon as the user leaves the name field.

        If the name already exists, immediately ask whether to create a new version.
        On confirmation, repopulate the layer table to include Output Layers (blue)
        so the user can configure everything with full context before clicking Next.
        """
        if self._creating_new_version or self.executor is None:
            return

        assessment_name = self.lineEdit_name.text().strip().replace(' ', '_')
        if not assessment_name:
            return

        if self.executor.validate_assessment_name(assessment_name):
            return  # Name is available — nothing to do

        reply = QtWidgets.QMessageBox.question(
            self,
            tr('dialog.exists_title'),
            tr('dialog.exists_body', name=assessment_name),
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No
        )
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            self._creating_new_version = True
            self._existing_assessment_id = self.executor.find_assessment_id(assessment_name)
            # Repopulate table from scratch so Output Layers appear immediately
            self.populate_layers()
            self._add_output_layers_to_table()
        else:
            # Clear the name field so the user picks a different one
            self.lineEdit_name.clear()
            self.lineEdit_name.setFocus()

    def validate_page_1(self):
        """Validate page 1 before allowing user to proceed."""
        if not self.lineEdit_name.text().strip():
            QtWidgets.QMessageBox.warning(
                self,
                tr('dialog.val_title'),
                tr('dialog.val_name_required')
            )
            return False

        # Check if exactly one layer is set as Target
        target_count = 0
        for row in range(self.tableWidget_layers.rowCount()):
            combo = self.tableWidget_layers.cellWidget(row, 2)
            if combo and self._status_of(combo) == self.STATUS_TARGET:
                target_count += 1

        if target_count == 0:
            QtWidgets.QMessageBox.warning(
                self,
                tr('dialog.val_title'),
                tr('dialog.val_no_target')
            )
            return False
        elif target_count > 1:
            QtWidgets.QMessageBox.warning(
                self,
                tr('dialog.val_title'),
                tr('dialog.val_multi_target')
            )
            return False

        # Validate geometry types match
        target_layer = None
        target_layer_name = None
        assessment_layers = []

        for row in range(self.tableWidget_layers.rowCount()):
            layer_name_item = self.tableWidget_layers.item(row, 0)
            combo = self.tableWidget_layers.cellWidget(row, 2)

            if layer_name_item and combo:
                layer_name = layer_name_item.text()
                status = self._status_of(combo)

                layers = QgsProject.instance().mapLayersByName(layer_name)
                if layers:
                    layer = layers[0]
                    if status == self.STATUS_TARGET:
                        target_layer = layer
                        target_layer_name = layer_name
                    elif status == self.STATUS_INCLUDE:
                        assessment_layers.append((layer_name, layer))

        if target_layer and assessment_layers:
            if isinstance(target_layer, QgsVectorLayer):
                target_geom_type = target_layer.geometryType()

                for assessment_name, assessment_layer in assessment_layers:
                    if isinstance(assessment_layer, QgsVectorLayer):
                        if assessment_layer.geometryType() != target_geom_type:
                            target_type_name = QgsWkbTypes.displayString(target_layer.wkbType())
                            assessment_type_name = QgsWkbTypes.displayString(assessment_layer.wkbType())

                            QtWidgets.QMessageBox.warning(
                                self,
                                tr('dialog.val_title'),
                                tr('dialog.val_geom_mismatch',
                                   assess=assessment_name, assess_type=assessment_type_name,
                                   target=target_layer_name, target_type=target_type_name)
                            )
                            return False
                    else:
                        QtWidgets.QMessageBox.warning(
                            self,
                            tr('dialog.val_title'),
                            tr('dialog.val_not_vector', assess=assessment_name)
                        )
                        return False

        # Migrate selected layers to SpatiaLite
        migration_service = LayerMigrationService(self.executor)
        layers_dict = self._collect_selected_layers()
        if not migration_service.migrate_selected_layers(layers_dict, parent_widget=self):
            pass  # Migration failed, but allow user to continue

        return True
