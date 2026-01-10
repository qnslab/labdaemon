"""
Server managers for LabDaemon.

Provides ownership tracking, error management, connection management, and SSE streaming functionality.
These are server-only concerns - the core LabDaemon does not track these.
"""

from __future__ import annotations

import asyncio
import json
import threading
import traceback
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from loguru import logger
from sse_starlette.sse import ServerSentEvent # Import ServerSentEvent

from ..utils import LabDaemonJSONEncoder


class OwnershipManager:
    """
    Manages device ownership for tasks in the server layer.
    
    This is a server-only concern - the core LabDaemon does not track ownership.
    """
    
    def __init__(self) -> None:
        self._task_device_ownership: Dict[str, str] = {}
        self._lock = threading.Lock()
    
    def claim_devices(self, task_id: str, device_ids: List[str]) -> None:
        """
        Claim ownership of devices for a task.
        
        Parameters
        ----------
        task_id : str
            The task claiming the devices.
        device_ids : List[str]
            List of device IDs to claim.
        
        Raises
        ------
        TaskError
            If any device is already owned by another task.
        """
        from ..exceptions import TaskError
        
        logger.debug(f"[OWNERSHIP] Attempting to claim devices {device_ids} for task '{task_id}'")
        
        with self._lock:
            # Check current ownership state
            conflicts = []
            for device_id in device_ids:
                if device_id in self._task_device_ownership:
                    owner = self._task_device_ownership[device_id]
                    if owner != task_id:  # Task can re-claim its own devices
                        conflicts.append((device_id, owner))
            
            if conflicts:
                conflict_msg = ", ".join(
                    f"'{dev_id}' (owned by '{owner}')" for dev_id, owner in conflicts
                )
                logger.error(f"[OWNERSHIP] Cannot claim devices for task '{task_id}': {conflict_msg}")
                raise TaskError(
                    f"Cannot start task '{task_id}': devices already owned: {conflict_msg}"
                )
            
            # Claim all devices atomically
            for device_id in device_ids:
                self._task_device_ownership[device_id] = task_id
                logger.info(f"[OWNERSHIP] Task '{task_id}' claimed device '{device_id}'")
    
    def release_devices(self, task_id: str) -> None:
        """
        Release all devices owned by a task.
        
        Parameters
          ----------
        task_id : str
            The task releasing devices.
        """
        logger.debug(f"[OWNERSHIP] Releasing devices for task '{task_id}'")
        
        with self._lock:
            owned_devices = [
                device_id for device_id, owner in list(self._task_device_ownership.items())
                if owner == task_id
            ]
            
            if owned_devices:
                logger.info(f"[OWNERSHIP] Task '{task_id}' releasing devices: {owned_devices}")
            else:
                logger.debug(f"[OWNERSHIP] Task '{task_id}' had no devices to release")
            
            for device_id in owned_devices:
                del self._task_device_ownership[device_id]
                logger.info(f"[OWNERSHIP] Task '{task_id}' released device '{device_id}'")
    
    def get_owner(self, device_id: str) -> Optional[str]:
        """
        Get the task that owns a device.
        
        Parameters
        ----------
        device_id : str
            The device ID to check.
        
        Returns
        -------
        Optional[str]
            The task ID that owns the device, or None if unowned.
        """
        with self._lock:
            return self._task_device_ownership.get(device_id)
    
    def clear_all(self) -> None:
        """Clear all ownership tracking (for testing)."""
        with self._lock:
            self._task_device_ownership.clear()


class ErrorManager:
    """
    Manages error storage for devices and tasks in the server layer.
    
    The core LabDaemon does not store errors - exceptions propagate normally.
    The server catches exceptions and stores them for client access.
    """
    
    def __init__(self, task_error_buffer: int = 20) -> None:
        """
        Initialise the ErrorManager.
        
        Parameters
        ----------
        task_error_buffer : int, default 20
            Number of task errors to retain. Matches the daemon's task buffer.
        """
        self._device_errors: Dict[str, dict] = {}
        self._task_errors: Dict[str, dict] = {}
        self._task_error_buffer = task_error_buffer
        self._lock = threading.Lock()
    
    def record_device_error(
        self,
        device_id: str,
        exc: Exception,
        origin: str = "device",
        context: Optional[dict] = None
    ) -> None:
        """
        Record an error for a device.
        
        Parameters
        ----------
        device_id : str
            The device ID.
        exc : Exception
            The exception that occurred.
        origin : str, default "device"
            Error origin: "framework", "device", or "callback".
        context : dict, optional
            Additional context information.
        """
        error = {
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
                "origin": origin,
                "timestamp": self._get_timestamp(),
                "traceback": traceback.format_exc(),
                "context": context or {"device_id": device_id},
            }
        }
        
        with self._lock:
            self._device_errors[device_id] = error
            logger.debug(f"[ErrorManager] Recorded error for device '{device_id}': {type(exc).__name__}")
    
    def get_device_error(self, device_id: str) -> Optional[dict]:
        """
        Get the last error for a device.
        
        Parameters
        ----------
        device_id : str
            The device ID to check.
        
        Returns
        -------
        Optional[dict]
            The error record wrapped in {"error": {...}}, or None if no error.
        """
        with self._lock:
            return self._device_errors.get(device_id)
    
    def clear_device_error(self, device_id: str) -> None:
        """
        Clear the error for a device.
        
        Parameters
        ----------
        device_id : str
            The device ID.
        """
        with self._lock:
            self._device_errors.pop(device_id, None)
            logger.debug(f"[ErrorManager] Cleared error for device '{device_id}'")
    
    def record_task_error(
        self,
        task_id: str,
        exc: Exception,
        origin: str = "framework",
        context: Optional[dict] = None
    ) -> None:
        """
        Record an error for a task.
        
        Parameters
        ----------
        task_id : str
            The task ID.
        exc : Exception
            The exception that occurred.
        origin : str, default "framework"
            Error origin: "framework", "device", or "callback".
        context : dict, optional
            Additional context information.
        """
        error = {
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
                "origin": origin,
                "timestamp": self._get_timestamp(),
                "traceback": traceback.format_exc(),
                "context": context or {"task_id": task_id},
            }
        }
        
        with self._lock:
            self._task_errors[task_id] = error
            logger.debug(f"[ErrorManager] Recorded error for task '{task_id}': {type(exc).__name__}")
            
            # Phase 1: Clean up old task errors to follow same retention policy
            self._cleanup_task_errors()
    
    def get_task_error(self, task_id: str) -> Optional[dict]:
        """
        Get the last error for a task.
        
        Parameters
        ----------
        task_id : str
            The task ID.
        
        Returns
        -------
        Optional[dict]
            The error record wrapped in {"error": {...}}, or None if no error.
        """
        with self._lock:
            return self._task_errors.get(task_id)
    
    def clear_task_error(self, task_id: str) -> None:
        """
        Clear the error for a task.
        
        Parameters
        ----------
        task_id : str
            The task ID.
        """
        with self._lock:
            self._task_errors.pop(task_id, None)
            logger.debug(f"[ErrorManager] Cleared error for task '{task_id}'")
    
    def _cleanup_task_errors(self) -> None:
        """
        Clean up old task errors to follow the same retention policy as task buffer.
        
        Retains only the most recent task_error_buffer task errors.
        Thread-safe implementation.
        """
        if len(self._task_errors) <= self._task_error_buffer:
            return
        
        # Create a snapshot of items to avoid modification during iteration
        error_items = list(self._task_errors.items())
        
        # Sort by timestamp (oldest first)
        sorted_errors = sorted(
            error_items,
            key=lambda x: x[1]["error"]["timestamp"]
        )
        
        # Remove oldest errors
        excess = len(sorted_errors) - self._task_error_buffer
        for i in range(excess):
            task_id_to_remove = sorted_errors[i][0]
            # Double-check it still exists before removing (thread safety)
            if task_id_to_remove in self._task_errors:
                del self._task_errors[task_id_to_remove]
                logger.debug(
                    f"[ErrorManager][Cleanup] Removed error for task '{task_id_to_remove}'. "
                    f"Buffer size: {self._task_error_buffer}"
                )
    
    def _get_timestamp(self) -> str:
        """Generate ISO 8601 UTC timestamp without microseconds."""
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class SSEManager:
    """
    Manages Server-Sent Events (SSE) streaming for device data.
    
    Provides per-device SSE streams as thin proxies over device streaming.
    Each client connection is independent with its own small buffer.
    
    Also broadcasts connection status events when devices connect/disconnect.
    """
    
    def __init__(self, daemon_ref=None) -> None:
        self._active_streams: Dict[str, threading.Event] = {}
        self._connection_listeners: Dict[str, Callable] = {}  # Callbacks for connection events
        self._lock = threading.Lock()
        self._daemon_ref = daemon_ref  # Reference to daemon for immediate device access
        self._shutdown = False # Flag to indicate manager is shutting down
    
    async def device_stream(
        self,
        device_id: str,
        device: Any
    ):
        """
        Generate SSE events for a device's data stream.
        
        Simple SSE proxy - no server-side buffering. Each client connection
        gets its own small buffer and drops events if it can't keep up.
        
        Parameters
        ----------
        device_id : str
            The device ID.
        device : Any
            The device instance.
        
        Yields
        ------
        ServerSentEvent
            SSE event objects for EventSourceResponse.
        """
        logger.info(f"[SSEManager] Starting device stream for '{device_id}'")
        
        # Check if device supports streaming
        if not hasattr(device, 'start_streaming'):
            logger.error(f"[SSEManager] Device '{device_id}' does not have start_streaming method")
            error_event_data = {
                "device_id": device_id,
                "timestamp": self._get_timestamp(),
                "error": {
                    "type": "DeviceError",
                    "message": f"Device '{device_id}' does not support streaming"
                }
            }
            yield ServerSentEvent(event="stream_error", data=json.dumps(error_event_data, cls=LabDaemonJSONEncoder))
            return
        
        # Check for existing stream
        with self._lock:
            if device_id in self._active_streams:
                logger.warning(f"[SSEManager] Device '{device_id}' already has an active stream")
                error_event_data = {
                    "device_id": device_id,
                    "timestamp": self._get_timestamp(),
                    "error": {
                        "type": "DeviceError",
                        "message": f"Device '{device_id}' is already streaming"
                    }
                }
                yield ServerSentEvent(event="stream_error", data=json.dumps(error_event_data, cls=LabDaemonJSONEncoder))
                return
            
            # Register this stream
            stop_event = threading.Event()
            self._active_streams[device_id] = stop_event
        
        # Create async queue for this client connection only
        client_queue = asyncio.Queue(maxsize=10)  # Small buffer per client
        sequence_counter = 0
        
        def device_callback(data: Any) -> None:
            """Device streaming callback - runs in device thread."""
            nonlocal sequence_counter
            
            if stop_event.is_set() or self._shutdown:
                logger.debug(f"[SSEManager] Callback returning early due to stop/shutdown for '{device_id}'")
                return
            
            # Create event payload
            event_payload = data
            
            # Non-blocking put, drop if client can't keep up (monitoring-grade)
            try:
                client_queue.put_nowait({
                    "event": "device_data",
                    "data": event_payload,
                    "id": str(sequence_counter)
                })
                sequence_counter += 1 # Increment only after successful queueing
            except asyncio.QueueFull:
                logger.warning(f"[SSEManager] Client queue full for '{device_id}', dropping event {sequence_counter}")
        
        # Start device streaming
        try:
            logger.info(f"[SSEManager] Starting streaming for device '{device_id}'")
            device.start_streaming(callback=device_callback)
            logger.info(f"[SSEManager] Device '{device_id}' streaming started successfully")
            
            # Verify streaming state after start
            if hasattr(device, 'is_streaming'):
                streaming_state = device.is_streaming()
                logger.debug(f"[SSEManager] Device '{device_id}' streaming state after start: {streaming_state}")
            
        except Exception as e:
            logger.exception(f"[SSEManager] Failed to start streaming for device '{device_id}'")
            error_event_data = {
                "device_id": device_id,
                "timestamp": self._get_timestamp(),
                "error": {
                    "type": type(e).__name__,
                    "message": str(e)
                }
            }
            yield ServerSentEvent(event="stream_error", data=json.dumps(error_event_data, cls=LabDaemonJSONEncoder))
            
            # Cleanup
            with self._lock:
                self._active_streams.pop(device_id, None)
            return
        
        try:
            # Stream events to client
            logger.debug(f"[SSEManager] Entering event streaming loop for device '{device_id}'")
            
            while not stop_event.is_set() and not self._shutdown:
                try:
                    # Wait for data or send keepalive
                    event_dict = await asyncio.wait_for(client_queue.get(), timeout=1.0)
                    
                    # Prepare the SSE event data
                    payload_data = event_dict.get('data', [])
                    event_data_json = json.dumps(payload_data, cls=LabDaemonJSONEncoder)
                    
                    # Yield ServerSentEvent object
                    yield ServerSentEvent(
                        event=event_dict['event'],
                        data=event_data_json,
                        id=event_dict['id']
                    )
                    
                except asyncio.TimeoutError:
                    # Send keepalive ping
                    logger.debug(f"[SSEManager] Sending keepalive ping for '{device_id}'")
                    yield ServerSentEvent(event="ping", data="{}") # Empty JSON object for ping data
                    
        except asyncio.CancelledError:
            # Client disconnected
            logger.debug(f"[SSEManager] Client disconnected from device '{device_id}' stream")
            
        except Exception as e:
            # Unexpected error in streaming loop
            logger.exception(f"[SSEManager] Error in streaming loop for device '{device_id}'")
            error_event_data = {
                "device_id": device_id,
                "timestamp": self._get_timestamp(),
                "error": {
                    "type": type(e).__name__,
                    "message": str(e)
                }
            }
            yield ServerSentEvent(event="stream_error", data=json.dumps(error_event_data, cls=LabDaemonJSONEncoder))
            
        finally:
            # Stop device streaming and cleanup
            logger.info(f"[SSEManager] Cleaning up stream for device '{device_id}'")
            
            try:
                if hasattr(device, 'stop_streaming'):
                    if hasattr(device, 'is_streaming') and device.is_streaming():
                        logger.info(f"[SSEManager] Stopping device streaming for '{device_id}'")
                        device.stop_streaming(timeout=2.0)
                        logger.info(f"[SSEManager] Device '{device_id}' streaming stopped")
                    else:
                        logger.debug(f"[SSEManager] Device '{device_id}' not streaming, skipping stop")
            except Exception as e:
                logger.exception(f"[SSEManager] Error stopping streaming for device '{device_id}'")
            
            # Remove from active streams
            with self._lock:
                self._active_streams.pop(device_id, None)
            
            logger.info(f"[SSEManager] Stream cleanup complete for device '{device_id}'")
    
    def stop_stream(self, device_id: str) -> None:
        """
        Stop an active stream for a device.
        
        Parameters
        ----------
        device_id : str
            The device ID.
        """
        with self._lock:
            stop_event = self._active_streams.get(device_id)
            if stop_event:
                # Signal the generator to stop
                stop_event.set()
                
                # IMMEDIATELY remove from active streams to allow new streams
                # Don't wait for the generator's finally block
                del self._active_streams[device_id]
                logger.debug(f"[SSEManager] Removed '{device_id}' from active streams.")
                
                # IMMEDIATELY stop device streaming to prevent orphaned streams
                try:
                    # We need access to the daemon to get the device
                    # This is a bit of a hack, but necessary for immediate cleanup
                    if hasattr(self, '_daemon_ref') and self._daemon_ref:
                        device = self._daemon_ref.get_device(device_id)
                        if hasattr(device, 'stop_streaming') and hasattr(device, 'is_streaming'):
                            if device.is_streaming():
                                logger.info(f"[SSEManager] Immediately stopping device streaming for '{device_id}' on client disconnect")
                                device.stop_streaming(timeout=1.0)
                except Exception as e:
                    logger.warning(f"[SSEManager] Failed to immediately stop device streaming for '{device_id}': {e}")
    
    def stop_all_streams(self) -> None:
        """Stop all active streams."""
        with self._lock:
            # Iterate over a copy of keys to allow modification during iteration
            for device_id in list(self._active_streams.keys()):
                self.stop_stream(device_id) # Use the per-stream stop logic
            self._active_streams.clear() # Ensure it's empty
    
    def shutdown(self) -> None:
        """Clean shutdown of all streams and manager resources."""
        logger.info("[SSEManager] Initiating shutdown of all active streams.")
        self._shutdown = True
        self.stop_all_streams()
        logger.info("[SSEManager] All streams stopped and manager shut down.")

    def _get_timestamp(self) -> str:
        """Generate ISO 8601 UTC timestamp without microseconds."""
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
