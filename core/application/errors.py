# -*- coding: utf-8 -*-
"""Application-level exceptions shared by use cases and adapters."""


class OperationCancelled(Exception):
    """The user cancelled a long-running operation (e.g. layer migration).

    Raised from a progress callback; adapters must let it propagate instead
    of recording it as a per-item error.
    """
