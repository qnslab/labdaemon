"""
Common patterns for LabDaemon usage.

This module provides simple utilities for common use cases without
adding complexity to the core framework.
"""

from .setup import ensure_server
from .gui import ensure_device

__all__ = [
    "ensure_server",
    "ensure_device",
]
