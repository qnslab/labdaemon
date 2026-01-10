from __future__ import annotations

import threading
from typing import Any, Optional

from .exceptions import TaskCancelledError, TaskError, TaskFailedError


class TaskHandle:
    """A handle to a running task."""

    def __init__(
        self,
        task_id: str,
        thread: threading.Thread,
        cancel_event: threading.Event,
        resume_event: threading.Event,
        task_instance: Any,
    ):
        """Initialises the TaskHandle."""
        self.task_id = task_id
        self._thread = thread
        self._cancel_event = cancel_event
        self._resume_event = resume_event
        self._task_instance = task_instance
        self._result: Any = None
        self._exception: Optional[Exception] = None

    def wait(self, timeout: Optional[float] = None) -> Any:
        """
        Blocks until the task is complete and returns its result.

        If the task is paused when wait() is called, this method will continue
        to block until the task is resumed and completes.

        Raises
        ------
        TimeoutError
            If the task does not complete within the given timeout.
        TaskCancelledError
            If the task was cancelled.
        TaskFailedError
            If the task failed with an unhandled exception.
        """
        self._thread.join(timeout)

        if self._thread.is_alive():
            raise TimeoutError(f"Wait timed out for task '{self.task_id}'.")

        if self._exception is not None:
            # If the task itself raised a cancellation error, re-raise it directly.
            if isinstance(self._exception, TaskCancelledError):
                raise self._exception
            # Otherwise, wrap the exception in TaskFailedError.
            raise TaskFailedError(
                f"Task '{self.task_id}' failed during execution."
            ) from self._exception

        # If no exception, but it was cancelled, it means a graceful exit.
        if self._cancel_event.is_set():
            raise TaskCancelledError(f"Task '{self.task_id}' was cancelled.")

        return self._result

    def cancel(self) -> None:
        """
        Signals the task to cancel.

        If the task is currently paused, this will also resume it so that
        it can check the cancellation event and exit promptly.
        """
        self._cancel_event.set()
        # Unblock paused tasks so they can check cancel_event and exit
        self._resume_event.set()

    def is_running(self) -> bool:
        """Returns True if the task is currently running."""
        return self._thread.is_alive()

    def exception(self) -> Optional[Exception]:
        """Returns the captured exception if the task failed, else None."""
        return self._exception

    def pause(self) -> None:
        """
        Signals the task to pause execution.

        The task will pause at its next checkpoint where it calls
        context.resume_event.wait(). The task will remain paused until
        resume() is called.
        """
        self._resume_event.clear()

    def resume(self) -> None:
        """
        Signals the task to resume execution.

        If the task is currently paused (blocked on context.resume_event.wait()),
        this will unblock it and allow execution to continue.
        """
        self._resume_event.set()

    def is_paused(self) -> bool:
        """
        Returns True if the task is currently paused.

        Note that this reflects whether pause() has been called, not whether
        the task is actually blocked at a pause checkpoint.
        """
        return not self._resume_event.is_set()

    def set_parameter(self, key: str, value: Any) -> None:
        """
        Update a parameter on the running task.

        The task must implement a ``set_parameter(key, value)`` method to handle
        the update. If the task doesn't support parameter updates, this will
        raise a TaskError.

        Parameters
        ----------
        key : str
            The parameter name.
        value : Any
            The new parameter value.

        Raises
        ------
        TaskError
            If the task doesn't support parameter updates.

        Notes
        -----
        The task is responsible for validating the parameter and ensuring
        thread-safe access to its internal state.
        """
        if not hasattr(self._task_instance, "set_parameter"):
            raise TaskError(
                f"Task '{self.task_id}' does not support parameter updates. "
                f"The task must implement a set_parameter(key, value) method."
            )
        self._task_instance.set_parameter(key, value)

    def get_parameter(self, key: str) -> Any:
        """
        Query a parameter value from the running task.

        The task must implement a ``get_parameter(key)`` method to handle
        the query. If the task doesn't support parameter queries, this will
        raise a TaskError.

        Parameters
        ----------
        key : str
            The parameter name.

        Returns
        -------
        Any
            The current parameter value.

        Raises
        ------
        TaskError
            If the task doesn't support parameter queries.

        Notes
        -----
        "Parameter" in this context broadly refers to any named value the task
        exposes - this includes configuration inputs (e.g., 'sweep_speed'),
        state queries (e.g., 'progress'), and intermediate results
        (e.g., 'current_spectrum').
        """
        if not hasattr(self._task_instance, "get_parameter"):
            raise TaskError(
                f"Task '{self.task_id}' does not support parameter queries. "
                f"The task must implement a get_parameter(key) method."
            )
        return self._task_instance.get_parameter(key)
