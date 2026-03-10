# -*- coding: utf-8 -*-
"""
MetadataRepositoryPort — abstraction over AdminManager.

Use cases depend on this Protocol, not on the concrete AdminManager class.
AdminManager satisfies this Protocol via structural (duck-type) typing —
no changes to AdminManager are needed.
"""

from typing import Protocol, runtime_checkable, List, Optional


@runtime_checkable
class MetadataRepositoryPort(Protocol):
    """Port: read/write metadata in the admin store (admin.sqlite)."""

    # ------------------------------------------------------------------ #
    #  Project queries
    # ------------------------------------------------------------------ #

    def get_project_db_path(self, project_db_id: int) -> Optional[str]: ...

    def get_assessments_for_project(self, project_db_id: int) -> List[dict]: ...

    def get_assessment_count(self, project_db_id: int) -> int: ...

    # ------------------------------------------------------------------ #
    #  Assessment queries
    # ------------------------------------------------------------------ #

    def get_assessment(self, assessment_id: int) -> Optional[dict]: ...

    def assessment_name_exists(self, project_db_id: int, name: str) -> bool: ...

    def get_assessment_layers(self, assessment_id: int,
                              layer_type: str = '') -> List[dict]: ...

    # ------------------------------------------------------------------ #
    #  Assessment writes
    # ------------------------------------------------------------------ #

    def create_assessment(self, project_id: int, name: str, description: str,
                          target_layer: str, assessment_layers: List[str],
                          output_tables: List[str]) -> int: ...

    def add_assessment_layer(self, assessment_id: int, layer_name: str,
                             layer_type: str): ...

    def set_layer_visibility(self, assessment_id: int, layer_name: str,
                             visible: bool): ...

    # ------------------------------------------------------------------ #
    #  Provenance writes
    # ------------------------------------------------------------------ #

    def create_provenance(self, assessment_id: int, name: str,
                          description: str) -> int: ...

    def add_task(self, provenance_id: int, step_order: int, operation: str,
                 category: str, engine_type: str, input_tables: List[str],
                 output_tables: List[str], added_to_map: bool): ...

    # ------------------------------------------------------------------ #
    #  Analysis / MCDA config
    # ------------------------------------------------------------------ #

    def get_analysis_config(self, assessment_id: int) -> Optional[dict]: ...

    def create_analysis_config(self, assessment_id: int, **kwargs): ...

    def update_analysis_config(self, assessment_id: int, **kwargs): ...

    def get_analysis_for_output_table(self, table_name: str) -> Optional[dict]: ...

    def snapshot_analysis_for_version(self, assessment_id: int,
                                      output_table: str,
                                      version_num: int): ...
