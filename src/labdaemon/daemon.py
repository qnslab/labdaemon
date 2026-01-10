from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from functools import wraps
from types import MethodType
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple, Type, Union

from loguru import logger

from .context import TaskContext
from .exceptions import DeviceError, DeviceTimeoutError, TaskError
from .handlers import TaskHandle


class LabDaemon:
    """The main entry point for the LabDaemon framework."""

    def __init__(self, completed_task_buffer: int = 20) -> None:
        """
        Initialises the LabDaemon instance.

        Parameters
        ----------
        completed_task_buffer : int, default 20
            Number of completed tasks to retain in memory. When exceeded,
            the oldest completed tasks are automatically cleaned up.
        """
        self._device_classes: Dict[str, Type] = {}
        self._task_classes: Dict[str, Type] = {}
        self._devices: Dict[str, Any] = {}
        self._tasks: Dict[str, TaskHandle] = {}
        
        # Phase 1: Task ID cleanup system
        self._completed_task_buffer = completed_task_buffer
        self._recent_task_ids = set()  # Track recent task IDs for uniqueness enforcement
        self._task_id_history_limit = completed_task_buffer * 100  # 100x buffer size for history
        self._task_completion_times: Dict[str, float] = {}  # Track completion times for LRU
        self._lock = threading.Lock()  # Protect task cleanup operations

    def register_plugins(self, devices: Dict[str, Type], tasks: Dict[str, Type]) -> None:
        """Registers device and task classes."""
        for device_type, device_class in devices.items():
            if device_type in self._device_classes:
                raise ValueError(f"Device type '{device_type}' is already registered.")
            self._device_classes[device_type] = device_class

        for task_type, task_class in tasks.items():
            if task_type in self._task_classes:
                raise ValueError(f"Task type '{task_type}' is already registered.")
            self._task_classes[task_type] = task_class

    def add_device(self, device_id: str, device_type: str, **kwargs) -> Any:
        """Creates a device instance with re-bound locked methods. Returns the instance."""
        if device_id in self._devices:
            raise ValueError(f"Device with ID '{device_id}' already exists.")

        try:
            device_class = self._device_classes[device_type]
        except KeyError:
            raise ValueError(
                f"Unknown device type: '{device_type}'. Is the plugin registered?"
            )

        device_instance = device_class(device_id, **kwargs)

        # Method rebinding for thread safety
        lock = threading.RLock()
        # Inject the lock for internal use (e.g., callbacks, device threads)
        device_instance._ld_lock = lock

        def wrap_method(method: Callable) -> Callable:
            @wraps(method)
            def wrapper(*args, **kwargs):
                with lock:
                    return method(*args, **kwargs)

            return wrapper

        for name in dir(device_instance):
            if name.startswith("_"):
                continue

            try:
                attr = getattr(device_instance, name)
            except AttributeError:
                continue

            if isinstance(attr, MethodType):
                setattr(device_instance, name, wrap_method(attr))

        self._devices[device_id] = device_instance
        return device_instance

    def connect_device(
        self, device: Union[str, Any], timeout: Optional[float] = None
    ) -> None:
        """
        Connects the specified device.

        Parameters
        ----------
        device : Union[str, Any]
            The device ID (string) or device instance to connect.
        timeout : Optional[float], default None
            Maximum time in seconds to wait for connection. If None, waits indefinitely.
            If the timeout is exceeded, raises DeviceTimeoutError and attempts cleanup.

        Raises
        ------
        DeviceTimeoutError
            If the connection does not complete within the specified timeout.
        """
        device_instance = self._get_device_instance(device)
        device_id = device_instance.device_id

        if timeout is None:
            # No timeout - call directly (backward compatible)
            logger.info(f"[DEVICE] Connecting '{device_id}' (no timeout)")
            device_instance.connect()
            logger.info(f"[DEVICE] Connected '{device_id}' successfully")
        else:
            # Use a thread with bounded join for timeout enforcement
            logger.info(f"[DEVICE] Connecting '{device_id}' (timeout={timeout}s)")
            exception_holder = []

            def connect_worker():
                try:
                    device_instance.connect()
                except Exception as e:
                    exception_holder.append(e)

            thread = threading.Thread(
                target=connect_worker,
                name=f"LabDaemon-Device-Connect-{device_id}",
                daemon=True,
            )
            thread.start()
            thread.join(timeout=timeout)

            if thread.is_alive():
                # Timeout occurred
                logger.error(
                    f"[DEVICE] Connection timed out for '{device_id}' after {timeout}s. "
                    "Attempting cleanup..."
                )
                # Attempt cleanup with a short timeout
                try:
                    self.disconnect_device(device_instance, timeout=2.0)
                except Exception:
                    logger.exception(
                        f"[DEVICE] Cleanup after connection timeout failed for '{device_id}'"
                    )
                
                raise DeviceTimeoutError(
                    f"Device '{device_id}' connection timed out after {timeout}s"
                )

            # Check if an exception occurred in the worker thread
            if exception_holder:
                logger.error(f"[DEVICE] Connection failed for '{device_id}': {exception_holder[0]}")
                raise exception_holder[0]

            logger.info(f"[DEVICE] Connected '{device_id}' successfully")

    def disconnect_device(
        self, device: Union[str, Any], timeout: Optional[float] = None
    ) -> None:
        """
        Disconnects the specified device.

        Parameters
        ----------
        device : Union[str, Any]
            The device ID (string) or device instance to disconnect.
        timeout : Optional[float], default None
            Maximum time in seconds to wait for disconnection. If None, waits indefinitely.
            If the timeout is exceeded, logs a warning and continues.

        Notes
        -----
        This method is idempotent - calling it multiple times is safe.
        Timeout expiry logs a warning but does not raise an exception.
        """
        device_instance = self._get_device_instance(device)
        device_id = device_instance.device_id

        if timeout is None:
            # No timeout - call directly (backward compatible)
            logger.info(f"[DEVICE] Disconnecting '{device_id}' (no timeout)")
            device_instance.disconnect()
            logger.info(f"[DEVICE] Disconnected '{device_id}' successfully")
        else:
            # Use a thread with bounded join for timeout enforcement
            logger.info(f"[DEVICE] Disconnecting '{device_id}' (timeout={timeout}s)")
            exception_holder = []

            def disconnect_worker():
                try:
                    device_instance.disconnect()
                except Exception as e:
                    exception_holder.append(e)

            thread = threading.Thread(
                target=disconnect_worker,
                name=f"LabDaemon-Device-Disconnect-{device_id}",
                daemon=True,
            )
            thread.start()
            thread.join(timeout=timeout)

            if thread.is_alive():
                # Timeout occurred - log warning but don't raise
                logger.warning(
                    f"[DEVICE] Disconnection timed out for '{device_id}' after {timeout}s. "
                    "Thread may still be running."
                )
            elif exception_holder:
                # Exception occurred in worker thread
                logger.error(
                    f"[DEVICE] Exception during disconnect for '{device_id}': {exception_holder[0]}"
                )
            else:
                logger.info(f"[DEVICE] Disconnected '{device_id}' successfully")

    def get_device(self, device_id: str) -> Any:
        """Returns the device instance."""
        try:
            return self._devices[device_id]
        except KeyError:
            raise ValueError(f"No device found with ID: '{device_id}'")

    def _get_device_instance(self, device: Union[str, Any]) -> Any:
        """Resolves a device ID or instance into an instance."""
        if isinstance(device, str):
            device_id = device
        elif hasattr(device, "device_id"):
            device_id = getattr(device, "device_id")
        else:
            raise TypeError(
                "Device must be specified by its string ID or be a device instance "
                "with a 'device_id' attribute."
            )

        try:
            return self._devices[device_id]
        except KeyError:
            raise ValueError(f"No device found with ID: '{device_id}'")

    @contextmanager
    def device_context(
        self, device_id: str, device_type: str, **kwargs
    ) -> Generator[Any, None, None]:
        """A context manager for safe device usage."""
        device_instance = self.add_device(
            device_id=device_id, device_type=device_type, **kwargs
        )
        try:
            self.connect_device(device_instance)
            yield device_instance
        finally:
            try:
                self.disconnect_device(device_instance)
            except Exception:
                logger.exception(
                    f"Failed to disconnect device '{device_id}' on context exit."
                )

    def execute_task(self, task_id: str, task_type: str, **kwargs) -> TaskHandle:
        """Executes a task in a background thread."""
        logger.info(f"[TASK] Executing task '{task_id}' of type '{task_type}'")
        
        # Phase 1: Check task ID uniqueness against active tasks AND recent history
        with self._lock:
            # Check if task is currently running
            if task_id in self._tasks and self._tasks[task_id].is_running():
                logger.error(f"[TASK] Task '{task_id}' is already running")
                raise ValueError(f"Task with ID '{task_id}' is already running.")
            
            # Check if task ID is in recent history (uniqueness enforcement)
            if task_id in self._recent_task_ids:
                logger.error(f"[TASK] Task '{task_id}' ID is in recent history - must be unique")
                raise ValueError(
                    f"Task ID '{task_id}' has been used recently. "
                    f"Task IDs must be unique across active and recently completed tasks."
                )
            
            # Add to recent task IDs tracking
            self._recent_task_ids.add(task_id)
            logger.debug(f"[TASK] Added '{task_id}' to recent task IDs tracking")
            
            # Clean up if history exceeds limit
            if len(self._recent_task_ids) > self._task_id_history_limit:
                # Convert to list and remove oldest entries to maintain limit
                recent_list = list(self._recent_task_ids)
                excess = len(recent_list) - self._task_id_history_limit
                for old_id in recent_list[:excess]:
                    self._recent_task_ids.discard(old_id)
                logger.debug(f"[TASK] Cleaned up {excess} old task IDs from history")

        try:
            task_class = self._task_classes[task_type]
        except KeyError:
            raise ValueError(
                f"Unknown task type: '{task_type}'. Is the plugin registered?"
            )

        # Pop server-specific arguments before passing to task constructor
        server_cleanup_func = kwargs.pop("_server_cleanup_func", None)

        task_instance = task_class(task_id=task_id, **kwargs)
        
        # Validate device_ids if present (Phase 1 requirement)
        device_ids = getattr(task_instance, 'device_ids', [])
        
        if device_ids and not isinstance(device_ids, list):
            raise TaskError(
                f"Task '{task_id}': self.device_ids must be a list of strings, "
                f"got {type(device_ids).__name__}"
            )
        
        if device_ids and not all(isinstance(dev_id, str) for dev_id in device_ids):
            raise TaskError(
                f"Task '{task_id}': self.device_ids must contain only strings"
            )
        
        if not device_ids:
            logger.debug(f"Task '{task_id}' declares no device ownership")
        else:
            logger.debug(f"Task '{task_id}' declares device ownership: {device_ids}")
        
        cancel_event = threading.Event()
        resume_event = threading.Event()
        resume_event.set()  # Start in running state (gate is open)

        # Create the context object
        context = TaskContext(
            daemon=self,
            cancel_event=cancel_event,
            resume_event=resume_event,
            task_id=task_id,
        )

        # The handle is defined late, but the closure for task_runner captures it.
        handle: TaskHandle

        def task_runner() -> None:
            """The target function for the task thread."""
            try:
                # Pass the context to the task's run method
                result = task_instance.run(context)
                handle._result = result
            except Exception as e:
                handle._exception = e
            finally:
                # Phase 1: Record task completion time for LRU eviction
                self._record_task_completion(task_id)
                
                # Guarantee cleanup even if task crashes (Phase 1 requirement)
                if hasattr(handle, '_server_cleanup'):
                    try:
                        handle._server_cleanup()
                    except Exception:
                        logger.exception(f"Error during task cleanup for '{task_id}'")
                
                # Phase 1: Trigger cleanup after task completes
                self._cleanup_completed_tasks(currently_completed_task=task_id)

        thread = threading.Thread(
            target=task_runner,
            name=f"LabDaemon-Task-{task_id}",
            daemon=True,  # Daemon threads do not block application exit
        )

        handle = TaskHandle(
            task_id=task_id,
            thread=thread,
            cancel_event=cancel_event,
            resume_event=resume_event,
            task_instance=task_instance,
        )

        # Attach server cleanup function to handle BEFORE starting thread
        if server_cleanup_func:
            handle._server_cleanup = server_cleanup_func

        self._tasks[task_id] = handle
        thread.start()

        return handle

    @contextmanager
    def task_context(
        self, task_id: str, task_type: str, **kwargs
    ) -> Generator[TaskHandle, None, None]:
        """A context manager for safe task execution."""
        handle = self.execute_task(task_id=task_id, task_type=task_type, **kwargs)
        try:
            yield handle
        finally:
            if handle.is_running():
                try:
                    handle.cancel()
                except Exception:
                    logger.exception(
                        f"Failed to cancel task '{task_id}' on context exit."
                    )

    def start_streaming(self, device: Union[str, Any], callback: Callable) -> None:
        """Starts streaming on a device."""
        device_instance = self._get_device_instance(device)
        if not hasattr(device_instance, "start_streaming"):
            raise DeviceError(f"Device '{device_instance.device_id}' does not support streaming.")
        # The callback is passed to the device's streaming method.
        device_instance.start_streaming(callback=callback)

    def stop_streaming(
        self, device: Union[str, Any], timeout: Optional[float] = 1.0
    ) -> None:
        """Stops streaming on a device."""
        device_instance = self._get_device_instance(device)
        if not hasattr(device_instance, "stop_streaming"):
            return  # Silently ignore if not streamable
        device_instance.stop_streaming(timeout=timeout)

    def shutdown(self, timeout: Optional[float] = 2.0) -> None:
        """
        Cancels all tasks and disconnects all devices.

        Parameters
        ----------
        timeout : Optional[float], default 2.0
            Per-step timeout budget in seconds. This timeout is applied to each
            individual operation (stopping streaming, joining tasks, disconnecting devices).
            If None, waits indefinitely for each step.

        Notes
        -----
        Shutdown proceeds through all steps even if individual operations timeout or fail.
        Timeouts and exceptions are logged but do not halt the shutdown process.

        Shutdown order:
        1. Stop all streaming (with per-device timeout)
        2. Cancel all running tasks (with per-task join timeout)
        3. Disconnect all devices (with per-device timeout)
        """
        logger.debug("LabDaemon shutdown initiated.")

        # 1. Stop all streaming (per-device timeout budget)
        for device_id in list(self._devices.keys()):
            try:
                logger.debug(f"[Shutdown] Stopping streaming on device '{device_id}'")
                self.stop_streaming(device_id, timeout=timeout)
            except Exception:
                logger.exception(
                    f"[Shutdown] Error stopping streaming on device '{device_id}'. "
                    "Continuing with shutdown."
                )

        # 2. Cancel all running tasks
        for task_id, handle in list(self._tasks.items()):
            if handle.is_running():
                try:
                    logger.debug(f"[Shutdown] Cancelling task '{task_id}'")
                    handle.cancel()
                except Exception:
                    logger.exception(
                        f"[Shutdown] Error cancelling task '{task_id}'. "
                        "Continuing with shutdown."
                    )

        # Wait for tasks to finish cancellation (per-task timeout budget)
        for task_id, handle in list(self._tasks.items()):
            if handle.is_running():
                try:
                    logger.debug(
                        f"[Shutdown] Waiting for task '{task_id}' to terminate "
                        f"(timeout={timeout}s)"
                    )
                    handle._thread.join(timeout=timeout)
                    if handle.is_running():
                        logger.warning(
                            f"[Shutdown] Task '{task_id}' did not terminate within "
                            f"{timeout}s. Thread may still be running. Continuing with shutdown."
                        )
                except Exception:
                    logger.exception(
                        f"[Shutdown] Error joining task thread '{task_id}'. "
                        "Continuing with shutdown."
                    )

        # 3. Disconnect all devices (per-device timeout budget)
        for device_id in list(self._devices.keys()):
            try:
                logger.debug(
                    f"[Shutdown] Disconnecting device '{device_id}' "
                    f"(timeout={timeout}s)"
                )
                self.disconnect_device(device_id, timeout=timeout)
            except Exception:
                logger.exception(
                    f"[Shutdown] Error disconnecting device '{device_id}'. "
                    "Continuing with shutdown."
                )

        logger.debug("LabDaemon shutdown complete.")
    
    def _cleanup_completed_tasks(self, currently_completed_task: Optional[str] = None) -> None:
        """
        Clean up completed tasks to prevent memory accumulation.
        
        Retains only the most recent completed_task_buffer tasks using true LRU
        (least recently used) eviction based on completion time.
        
        This method is called after each task completes to ensure timely cleanup.
        """
        with self._lock:
            # Separate running and completed tasks
            running_task_ids = set()
            completed_tasks: List[Tuple[str, float]] = []
            
            for task_id, handle in self._tasks.items():
                # A task is considered running if its thread is alive
                # Exception: the task that just completed (if provided)
                if handle.is_running() and task_id != currently_completed_task:
                    running_task_ids.add(task_id)
                else:
                    # Get completion time (most recent first)
                    # If no completion time is recorded yet, use current time
                    completion_time = self._task_completion_times.get(task_id, time.time())
                    completed_tasks.append((task_id, completion_time))
            
            # Check if we need to clean up - if we have more completed tasks than buffer
            if len(completed_tasks) <= self._completed_task_buffer:
                return
            
            # Sort by completion time (oldest first) for LRU eviction
            completed_tasks.sort(key=lambda x: x[1])
            
            # Remove oldest completed tasks - keep only the most recent N
            if self._completed_task_buffer == 0:
                # Special case: remove all completed tasks
                tasks_to_remove = [t[0] for t in completed_tasks]
            else:
                tasks_to_remove = [t[0] for t in completed_tasks[:-self._completed_task_buffer]]  # Remove oldest
            
            for task_id_to_remove in tasks_to_remove:
                del self._tasks[task_id_to_remove]
                self._task_completion_times.pop(task_id_to_remove, None)
    
    def _record_task_completion(self, task_id: str) -> None:
        """
        Record the completion time of a task for LRU eviction.
        
        Parameters
        ----------
        task_id : str
            The task ID that has completed.
        """
        with self._lock:
            self._task_completion_times[task_id] = time.time()
