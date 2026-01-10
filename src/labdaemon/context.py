"""Task execution context."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .daemon import LabDaemon


class TaskContext:
    """
    Context provided to tasks during execution.

    This object provides tasks with everything they need to execute:
    - Access to the LabDaemon instance for device control
    - Events for cancellation and pause/resume

    Attributes
    ----------
    daemon : LabDaemon
        The LabDaemon instance, used to access devices via get_device().
    cancel_event : threading.Event
        Set when the user requests cancellation via handle.cancel().
        Tasks should check this periodically and exit gracefully.
    resume_event : threading.Event
        Cleared when the user requests pause via handle.pause().
        Set when running normally or when resumed via handle.resume().
        Tasks should call resume_event.wait() to block while paused.

    Notes
    -----
    The resume_event uses "gate" semantics:
    - When set (default): task is running normally
    - When cleared: task is paused, resume_event.wait() blocks
    - On cancel: resume_event is set to unblock paused tasks

    Examples
    --------
    >>> def run(self, context: TaskContext):
    ...     laser = context.daemon.get_device("laser1")
    ...
    ...     for step in range(100):
    ...         # Check for cancellation
    ...         if context.cancel_event.is_set():
    ...             return "Cancelled"
    ...
    ...         # Check for pause (blocks until resumed)
    ...         context.resume_event.wait()
    ...
    ...         laser.set_wavelength(1550 + step)
    """

    def __init__(
        self,
        daemon: LabDaemon,
        cancel_event: threading.Event,
        resume_event: threading.Event,
        task_id: str,
    ):
        """
        Initialise the TaskContext.

        Parameters
        ----------
        daemon : LabDaemon
            The LabDaemon instance.
        cancel_event : threading.Event
            Event for cancellation signalling.
        resume_event : threading.Event
            Event for pause/resume signalling (gate semantics).
        task_id : str
            The task ID for tracking and server integration.
        """
        self.daemon = daemon
        self.cancel_event = cancel_event
        self.resume_event = resume_event
        self.task_id = task_id
