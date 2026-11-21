# -*- coding: utf-8 -*-
"""
Naming rules for scenarios, versions, SpatiaLite tables and project files.

Pure Python — no QGIS, no database.

Versioned overlay tables are named ``{base}__v{n}`` where ``base`` is the
sanitized ``{project}__{assessment}``. The double underscore is significant:
it separates project, assessment and version, and is preserved by
:func:`sanitize_table_name`.
"""

import re

VERSION_SEPARATOR = "__v"
_VERSION_SUFFIX = re.compile(r'__v(\d+)$')


# ── Versions ───────────────────────────────────────────────────────────────

def version_of(table_name, default=None):
    """Version number encoded in a ``…__v{n}`` table name, or *default*."""
    match = _VERSION_SUFFIX.search(table_name or '')
    return int(match.group(1)) if match else default


def strip_version(table_name):
    """Scenario base name: the table name without its ``__v{n}`` suffix."""
    return _VERSION_SUFFIX.sub('', table_name or '')


def versioned_name(base, version):
    """Table name of version *version* of scenario *base*."""
    return f"{base}{VERSION_SEPARATOR}{version}"


def step_table_name(base, step):
    """Temporary table of intermediate cumulative-overlay step *step*."""
    return f"{base}__step_{step}_tmp"


# ── Sanitizing ─────────────────────────────────────────────────────────────

def sanitize_table_name(raw_name):
    """SpatiaLite-safe table name.

    Lower-case, non ``[a-z0-9_]`` characters become ``_``, runs of 3+
    underscores collapse to ``__`` (keeps the project/assessment separator),
    leading/trailing ``_`` are stripped, and a leading digit gets a
    ``layer_`` prefix. Empty results become ``unnamed_layer``.
    """
    name = re.sub(r'[^a-zA-Z0-9_]', '_', raw_name).lower()
    name = re.sub(r'_{3,}', '__', name)
    name = name.strip('_')
    if name and name[0].isdigit():
        name = 'layer_' + name
    return name if name else 'unnamed_layer'


def sanitize_file_name(raw_name):
    """Filesystem-safe base name for a project database file.

    Deliberately simpler than :func:`sanitize_table_name` (no underscore
    collapsing, no digit prefix): existing project files were named with this
    rule, so changing it would break the link to their ``projects/*.sqlite``.
    """
    name = re.sub(r'[^a-zA-Z0-9_]', '_', raw_name).lower().strip('_')
    return name if name else 'unnamed'
