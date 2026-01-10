"""
LabDaemon: A Python framework for instrument control and experiment automation.

LabDaemon provides a simple, synchronous API for controlling laboratory instruments
and executing automated tasks. It handles device lifecycle management, thread-safe
access, and background task execution.

Core Components
---------------
LabDaemon : The main framework class
    Manages devices and tasks, provides lifecycle management.

TaskContext : Context provided to tasks during execution
    Gives tasks access to devices and cancellation/pause events.

TaskHandle : Handle to a running task
    Allows monitoring, cancellation, and result retrieval.

Exceptions
----------
LabDaemonException : Base exception for all LabDaemon errors
DeviceError : Device-related errors
TaskError : Task-related errors

Examples
--------
Basic device usage:

>>> import labdaemon as ld
>>> 
>>> daemon = ld.LabDaemon()
>>> daemon.register_plugins(devices={"MyLaser": MyLaser}, tasks={})
>>> 
>>> with daemon.device_context("laser1", "MyLaser", address="GPIB0::1") as laser:
...     laser.set_wavelength(1550.0)
...     power = laser.get_power()

Task execution:

>>> daemon.register_plugins(devices={}, tasks={"MySweep": MySweepTask})
>>> handle = daemon.execute_task("sweep1", "MySweep", start_wl=1500, stop_wl=1600)
>>> result = handle.wait()

Server usage (optional):

>>> from labdaemon.server import LabDaemonServer
>>> 
>>> daemon = ld.LabDaemon()
>>> server = LabDaemonServer(daemon, host="0.0.0.0", port=5000)
>>> server.start(blocking=False)
>>> # ... server is now running, clients can connect via HTTP/SSE
>>> server.stop()
>>> daemon.shutdown()
"""

from .context import TaskContext
from .daemon import LabDaemon
from .exceptions import (
    DeviceConfigurationError,
    DeviceConnectionError,
    DeviceError,
    DeviceNotConnectedError,
    DeviceOperationError,
    DeviceTimeoutError,
    LabDaemonException,
    TaskCancelledError,
    TaskError,
    TaskFailedError,
)
from .handlers import TaskHandle

# Optional patterns module (imported lazily to avoid circular imports)
try:
    from .patterns import ensure_server, ensure_device
    _patterns_available = True
except ImportError:
    _patterns_available = False

# Optional server module (imported lazily to avoid circular imports)
try:
    from .server import ServerAPI, SSEClient
    _server_available = True
except ImportError:
    _server_available = False

from ._version import __version__

__all__ = [
    "LabDaemon",
    "TaskContext",
    "TaskHandle",
    "LabDaemonException",
    "DeviceError",
    "DeviceConnectionError",
    "DeviceNotConnectedError",
    "DeviceTimeoutError",
    "DeviceConfigurationError",
    "DeviceOperationError",
    "TaskError",
    "TaskCancelledError",
    "TaskFailedError",
]

# Add patterns to public API if available
if _patterns_available:
    __all__.extend([
        "ensure_server",
        "ensure_device",
    ])

# Add server to public API if available
if _server_available:
    __all__.extend([
        "ServerAPI",
        "SSEClient",
    ])
