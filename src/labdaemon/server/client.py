"""
HTTP and SSE client for LabDaemon server API.

Provides high-level abstractions for communicating with a LabDaemon server,
including device control, task execution, and real-time data streaming.
"""
import json
import threading
from typing import Any, Callable, Dict, Optional

import requests
from loguru import logger

from .errors import ServerAPIError, ServerConnectionError


class ServerAPI:
    """
    HTTP client for LabDaemon server API.
    
    Provides methods for device control, task execution, and state queries.
    
    Parameters
    ----------
    base_url : str, default "http://localhost:5000"
        Base URL of the LabDaemon server.
    
    Examples
    --------
    >>> from labdaemon.server import ServerAPI
    >>> 
    >>> api = ServerAPI("http://localhost:5000")
    >>> devices = api.list_devices()
    >>> result = api.call_device_method("laser1", "set_wavelength", args=[1550])
    >>> handle = api.execute_task("sweep1", "SweepTask", params={"start_wl": 1550})
    """
    
    def __init__(self, base_url: str = "http://localhost:5000"):
        """
        Initialise the server API client.
        
        Parameters
        ----------
        base_url : str, default "http://localhost:5000"
            Base URL of the LabDaemon server.
        """
        self.base_url = base_url.rstrip('/')
        self._session = requests.Session()
        self._session.timeout = 30.0  # Reduced default timeout to prevent long waits
    
    def _request(
        self,
        method: str,
        endpoint: str,
        json_data: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Make an HTTP request to the server.
        
        Parameters
        ----------
        method : str
            HTTP method ('GET', 'POST', 'DELETE').
        endpoint : str
            API endpoint (e.g., '/devices').
        json_data : dict, optional
            JSON body for POST requests.
        timeout : float, optional
            Request timeout in seconds.
        
        Returns
        -------
        dict
            Parsed JSON response.
        
        Raises
        ------
        ServerConnectionError
            If connection fails.
        ServerAPIError
            If server returns an error.
        """
        url = f"{self.base_url}{endpoint}"
        timeout = timeout or self._session.timeout
        
        try:
            response = self._session.request(
                method,
                url,
                json=json_data,
                timeout=timeout
            )
            response.raise_for_status()
            return response.json()
        except requests.ConnectionError as e:
            raise ServerConnectionError(f"Failed to connect to {self.base_url}: {e}")
        except requests.Timeout as e:
            raise ServerConnectionError(f"Request timeout: {e}")
        except requests.HTTPError as e:
            try:
                error_data = e.response.json()
                # Handle both wrapped and unwrapped error formats
                if 'error' in error_data:
                    error_msg = error_data['error'].get('message', str(e))
                    error_type = error_data['error'].get('type', 'ServerError')
                    raise ServerAPIError(f"{error_type}: {error_msg}")
                elif 'message' in error_data: # Legacy format or simpler errors
                    raise ServerAPIError(error_data['message'])
                else:
                    raise ServerAPIError(f"HTTP {e.response.status_code}: {e}")
            except (ValueError, KeyError):
                # If response is not JSON or 'error'/'message' keys are missing
                raise ServerAPIError(f"HTTP {e.response.status_code}: {e}")
        except Exception as e:
            raise ServerAPIError(f"Request failed: {e}")
    
    def list_devices(self) -> Dict[str, Any]:
        """
        List all devices.
        
        Returns
        -------
        dict
            Response with 'devices' key containing list of device info.
        
        Examples
        --------
        >>> devices = api.list_devices()
        >>> for device in devices['devices']:
        ...     print(f"{device['device_id']}: {device['device_type']}")
        """
        return self._request('GET', '/devices')
    
    def get_device(self, device_id: str) -> Dict[str, Any]:
        """
        Get device details.
        
        Parameters
        ----------
        device_id : str
            Device identifier.
        
        Returns
        -------
        dict
            Device information.
        
        Examples
        --------
        >>> device = api.get_device("laser1")
        >>> print(f"Connected: {device['connected']}")
        """
        return self._request('GET', f'/devices/{device_id}')
    
    def get_device_methods(self, device_id: str) -> Dict[str, Any]:
        """
        Get introspection data for device methods.
        
        Parameters
        ----------
        device_id : str
            Device identifier.
        
        Returns
        -------
        dict
            Response with 'methods' key containing method signatures.
        
        Examples
        --------
        >>> methods = api.get_device_methods("laser1")
        >>> for method in methods['methods']:
        ...     print(f"{method['name']}: {method['parameters']}")
        """
        return self._request('GET', f'/devices/{device_id}/methods')
    
    def call_device_method(
        self,
        device_id: str,
        method: str,
        args: Optional[list] = None,
        kwargs: Optional[dict] = None
    ) -> Dict[str, Any]:
        """
        Call a device method.
        
        Parameters
        ----------
        device_id : str
            Device identifier.
        method : str
            Method name.
        args : list, optional
            Positional arguments.
        kwargs : dict, optional
            Keyword arguments.
        
        Returns
        -------
        dict
            Response with 'result' key containing method return value.
        
        Raises
        ------
        ServerAPIError
            If device is owned by a task (409 Conflict).
        
        Examples
        --------
        >>> result = api.call_device_method("laser1", "set_wavelength", args=[1550])
        >>> result = api.call_device_method(
        ...     "laser1",
        ...     "set_wavelength",
        ...     kwargs={"wavelength_nm": 1550, "wait_for_stabilization": True}
        ... )
        """
        body = {
            'method': method,
            'args': args or [],
            'kwargs': kwargs or {}
        }
        return self._request('POST', f'/devices/{device_id}/call', json_data=body)
    
    def get_device_error(self, device_id: str) -> Optional[Dict[str, Any]]:
        """
        Get last error for a device.
        
        Parameters
        ----------
        device_id : str
            Device identifier.
        
        Returns
        -------
        dict or None
            Error information, or None if no error recorded.
        
        Examples
        --------
        >>> error = api.get_device_error("laser1")
        >>> if error:
        ...     print(f"Error: {error['error']['message']}")
        """
        try:
            return self._request('GET', f'/devices/{device_id}/error')
        except ServerAPIError as e:
            if '404' in str(e):
                return None
            raise
    
    def clear_device_error(self, device_id: str) -> None:
        """
        Clear stored error for a device.
        
        Parameters
        ----------
        device_id : str
            Device identifier.
        
        Examples
        --------
        >>> api.clear_device_error("laser1")
        """
        self._request('DELETE', f'/devices/{device_id}/error')
    
    def add_device(self, device_id: str, device_type: str, **params) -> Dict[str, Any]:
        """
        Add a new device to the daemon.
        
        Parameters
        ----------
        device_id : str
            Device identifier.
        device_type : str
            Registered device type name.
        **params : dict
            Device-specific parameters.
        
        Returns
        -------
        dict
            Device information.
        
        Examples
        --------
        >>> device = api.add_device("laser2", "SantecLaser", address="GPIB0::2")
        """
        body = {
            'device_id': device_id,
            'device_type': device_type,
            'params': params
        }
        return self._request('POST', '/devices', json_data=body)
    
    def connect_device(self, device_id: str) -> Dict[str, Any]:
        """
        Connect a device.
        
        Parameters
        ----------
        device_id : str
            Device identifier.
        
        Returns
        -------
        dict
            Updated device information.
        
        Examples
        --------
        >>> device = api.connect_device("laser1")
        """
        return self._request('POST', f'/devices/{device_id}/connect')
    
    def disconnect_device(self, device_id: str) -> Dict[str, Any]:
        """
        Disconnect a device.
        
        Parameters
        ----------
        device_id : str
            Device identifier.
        
        Returns
        -------
        dict
            Updated device information.
        
        Examples
        --------
        >>> device = api.disconnect_device("laser1")
        """
        return self._request('POST', f'/devices/{device_id}/disconnect')
    
    def stop_device_stream(self, device_id: str) -> Dict[str, Any]:
        """
        Stop streaming on a device and close any active SSE connections.
        
        This method provides explicit control over device streaming lifecycle.
        It stops the device's streaming immediately and closes any active SSE
        connections, ensuring a clean state for subsequent operations.
        
        This is the recommended way to stop streaming before starting a new stream,
        as it guarantees the device is in a clean state and prevents race conditions
        where a new stream might be rejected due to the old stream still being active.
        
        This method is idempotent - calling it multiple times is safe.
        It does not require the device to be currently streaming.
        
        Parameters
        ----------
        device_id : str
            Device identifier.
        
        Returns
        -------
        dict
            Response with stop status and timestamp.
        
        Raises
        ------
        ServerAPIError
            If device not found or server error occurs.
        
        Notes
        -----
        This method is idempotent - calling it multiple times is safe.
        It does not require the device to be currently streaming.
        
        Examples
        --------
        >>> # Stop streaming before starting a new stream
        >>> api.stop_device_stream("daq1")
        >>> api.call_device_method("daq1", "configure_streaming", kwargs={...})
        >>> # Now safe to start new SSE stream
        """
        return self._request('POST', f'/devices/{device_id}/stream/stop')
    
    def list_tasks(self) -> Dict[str, Any]:
        """
        List all tasks.
        
        Returns
        -------
        dict
            Response with 'tasks' key containing list of task info.
        
        Examples
        --------
        >>> tasks = api.list_tasks()
        >>> for task in tasks['tasks']:
        ...     print(f"{task['task_id']}: {task['task_type']}")
        """
        return self._request('GET', '/tasks')
    
    def get_task(self, task_id: str, timeout: Optional[float] = None) -> Dict[str, Any]:
        """
        Get task details.
        
        Parameters
        ----------
        task_id : str
            Task identifier.
        timeout : float, optional
            Request timeout in seconds. If None, uses default session timeout.
        
        Returns
        -------
        dict
            Task information including status and result.
        
        Examples
        --------
        >>> task = api.get_task("sweep1")
        >>> if not task['running']:
        ...     print(f"Result: {task['result']}")
        >>> 
        >>> # Use shorter timeout for frequent status checks
        >>> task = api.get_task("sweep1", timeout=5.0)
        """
        return self._request('GET', f'/tasks/{task_id}', timeout=timeout)
    
    def execute_task(
        self,
        task_id: str,
        task_type: str,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Execute a task.
        
        Parameters
        ----------
        task_id : str
            Task identifier.
        task_type : str
            Task class name.
        params : dict, optional
            Task parameters.
        
        Returns
        -------
        dict
            Response with task status and device_ids.
        
        Raises
        ------
        ServerAPIError
            If devices are already owned by another task (409 Conflict).
        
        Examples
        --------
        >>> response = api.execute_task(
        ...     "sweep1",
        ...     "SweepTask",
        ...     params={
        ...         "laser_id": "laser1",
        ...         "daq_id": "daq1",
        ...         "start_wl": 1550,
        ...         "stop_wl": 1560
        ...     }
        ... )
        >>> print(f"Task started: {response['task_id']}")
        """
        body = {
            'task_id': task_id,
            'task_type': task_type,
            'params': params or {}
        }
        return self._request('POST', '/tasks', json_data=body)
    
    def get_task_error(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Get last error for a task.
        
        Parameters
        ----------
        task_id : str
            Task identifier.
        
        Returns
        -------
        dict or None
            Error information, or None if no error recorded.
        
        Examples
        --------
        >>> error = api.get_task_error("sweep1")
        >>> if error:
        ...     print(f"Error: {error['error']['message']}")
        """
        try:
            return self._request('GET', f'/tasks/{task_id}/error')
        except ServerAPIError as e:
            if '404' in str(e):
                return None
            raise
    
    def clear_task_error(self, task_id: str) -> None:
        """
        Clear stored error for a task.
        
        Parameters
        ----------
        task_id : str
            Task identifier.
        
        Examples
        --------
        >>> api.clear_task_error("sweep1")
        """
        self._request('DELETE', f'/tasks/{task_id}/error')
    
    def cancel_task(self, task_id: str) -> Dict[str, Any]:
        """
        Cancel a running task.
        
        Parameters
        ----------
        task_id : str
            Task identifier.
        
        Returns
        -------
        dict
            Response with cancellation status.
        
        Examples
        --------
        >>> api.cancel_task("sweep1")
        """
        return self._request('POST', f'/tasks/{task_id}/cancel')
    
    def pause_task(self, task_id: str) -> Dict[str, Any]:
        """
        Pause a running task.
        
        Parameters
        ----------
        task_id : str
            Task identifier.
        
        Returns
        -------
        dict
            Response with pause status.
        
        Examples
        --------
        >>> api.pause_task("sweep1")
        """
        return self._request('POST', f'/tasks/{task_id}/pause')
    
    def resume_task(self, task_id: str) -> Dict[str, Any]:
        """
        Resume a paused task.
        
        Parameters
        ----------
        task_id : str
            Task identifier.
        
        Returns
        -------
        dict
            Response with resume status.
        
        Examples
        --------
        >>> api.resume_task("sweep1")
        """
        return self._request('POST', f'/tasks/{task_id}/resume')
    
    def set_task_parameter(self, task_id: str, key: str, value: Any) -> Dict[str, Any]:
        """
        Set a parameter on a running task.
        
        Parameters
        ----------
        task_id : str
            Task identifier.
        key : str
            Parameter name.
        value : Any
            Parameter value.
        
        Returns
        -------
        dict
            Response with parameter update status.
        
        Examples
        --------
        >>> api.set_task_parameter("sweep1", "sweep_speed", 2.0)
        """
        body = {"key": key, "value": value}
        return self._request('POST', f'/tasks/{task_id}/parameters', json_data=body)
    
    def close(self) -> None:
        """Close the session."""
        self._session.close()


class SSEClient:
    """
    Server-Sent Events client for real-time device data streaming.
    
    Manages SSE connection to a LabDaemon server and dispatches events
    to a callback function in a background thread. This client correctly
    parses SSE messages according to the W3C specification, handling
    multi-line data fields and event IDs.
    
    Parameters
    ----------
    base_url : str, default "http://localhost:5000"
        Base URL of the LabDaemon server.
    on_event : callable, optional
        Callback function called with each event dict.
        Called from background thread - must be thread-safe.
        The event dict will contain 'event', 'data', and optionally 'id'.
    
    Examples
    --------
    >>> from labdaemon.server import SSEClient
    >>> 
    >>> def on_data(event):
    ...     print(f"Received event '{event.get('event')}': ID={event.get('id')}, Data={event.get('data')}")
    >>> 
    >>> client = SSEClient("http://localhost:5000", on_event=on_data)
    >>> client.start_device_stream("daq1")
    >>> 
    >>> # ... do work ...
    >>> 
    >>> client.stop_stream()
    """
    
    def __init__(
        self,
        base_url: str = "http://localhost:5000",
        on_event: Optional[Callable[[Dict[str, Any]], None]] = None
    ):
        """
        Initialise the SSE client.
        
        Parameters
        ----------
        base_url : str, default "http://localhost:5000"
            Base URL of the LabDaemon server.
        on_event : callable, optional
            Callback function called with each event dict.
            Called from background thread - must be thread-safe.
        """
        self.base_url = base_url.rstrip('/')
        self.on_event = on_event
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._device_id: Optional[str] = None
        self._session = requests.Session()
    
    def start_device_stream(self, device_id: str) -> None:
        """
        Start streaming data from a device.
        
        Parameters
        ----------
        device_id : str
            Device identifier.
        
        Raises
        ------
        RuntimeError
            If stream is already running.
        
        Examples
        --------
        >>> client.start_device_stream("daq1")
        """
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("Stream already running")
        
        self._device_id = device_id
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._stream_loop,
            daemon=True,
            name=f"SSEClient-{device_id}"
        )
        self._thread.start()
        logger.info(f"Started SSE stream for device '{device_id}'")
    
    def stop_stream(self, timeout: float = 5.0) -> None:
        """
        Stop the stream.
        
        Parameters
        ----------
        timeout : float, default 5.0
            Maximum time to wait for thread to stop.
        
        Examples
        --------
        >>> client.stop_stream(timeout=5.0)
        """
        if self._thread is None or not self._thread.is_alive():
            return
        
        self._stop_event.set()
        self._thread.join(timeout=timeout)
        
        if self._thread.is_alive():
            logger.warning(f"SSE stream thread did not stop within {timeout}s")
        else:
            logger.info(f"Stopped SSE stream for device '{self._device_id}'")
    
    def _ensure_str(self, value: Any) -> str:
        """
        Ensure a value is a string, decoding bytes if necessary.
        
        Parameters
        ----------
        value : Any
            Value to convert to string.
        
        Returns
        -------
        str
            String representation of the value.
        """
        if isinstance(value, bytes):
            return value.decode('utf-8', errors='replace')
        elif value is None:
            return ""
        else:
            return str(value)
    
    def _stream_loop(self) -> None:
        """
        Internal: Main loop for SSE streaming.
        
        This method connects to the SSE endpoint and continuously reads the stream,
        parsing events according to the W3C Server-Sent Events specification.
        It handles multi-line data fields and dispatches complete events to the
        `on_event` callback.
        """
        url = f"{self.base_url}/stream/devices/{self._device_id}"
        
        try:
            logger.info(f"[SSEClient] Connecting to {url}")
            
            headers = {
                "Accept": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            }
            
            with self._session.get(url, stream=True, headers=headers) as resp:
                resp.raise_for_status()
                logger.info(f"[SSEClient] Connected to SSE stream for '{self._device_id}'")
                
                buffer = b''
                # Iterate over raw content chunks to build up the buffer
                for chunk in resp.iter_content(chunk_size=1024):
                    if self._stop_event.is_set():
                        logger.info(f"[SSEClient] Stop event set, breaking from SSE loop for '{self._device_id}'")
                        break
                    
                    if not chunk:
                        continue
                    
                    buffer += chunk
                
                    # Process all complete messages in the buffer
                    # SSE messages are delimited by a double newline (\n\n or \r\n\r\n)
                    while True:
                        # Look for message delimiter (handle both \n\n and \r\n\r\n)
                        delimiter_pos = -1
                        delimiter_len = 0
                    
                        # Check for \r\n\r\n first (Windows-style)
                        if b'\r\n\r\n' in buffer:
                            delimiter_pos = buffer.find(b'\r\n\r\n')
                            delimiter_len = 4
                        # Then check for \n\n (Unix-style)
                        elif b'\n\n' in buffer:
                            delimiter_pos = buffer.find(b'\n\n')
                            delimiter_len = 2
                    
                        # No complete message found
                        if delimiter_pos == -1:
                            break
                    
                        # Extract the complete message
                        message_bytes = buffer[:delimiter_pos]
                        buffer = buffer[delimiter_pos + delimiter_len:]
                    
                        # Skip empty messages
                        if not message_bytes.strip():
                            continue
                    
                        event_name = "message"  # Default event type
                        data_lines = []
                        event_id = None
                    
                        # Decode the message and split into lines
                        try:
                            decoded_message = message_bytes.decode('utf-8', errors='replace')
                            # Split on both \r\n and \n to handle mixed line endings
                            lines = decoded_message.replace('\r\n', '\n').split('\n')
                        except Exception as e:
                            logger.error(f"[SSEClient] Failed to decode message: {e}")
                            continue
                    
                        for line in lines:
                            # Ignore empty lines and comment lines
                            if not line or line.startswith(':'):
                                continue
                        
                            # Parse field and value per SSE spec
                            if ":" in line:
                                field, value = line.split(":", 1)
                                if value.startswith(" "): # Remove leading space if present
                                    value = value[1:]
                            else:
                                # If no colon, the entire line is the field name, value is empty
                                field, value = line, ""
                        
                            if field == "event":
                                event_name = value
                            elif field == "data":
                                data_lines.append(value)
                            elif field == "id":
                                event_id = value
                            elif field == "retry":
                                # The client doesn't currently implement retry logic, so ignore
                                pass
                    
                        # Dispatch the event if any data or event type was found
                        if data_lines or event_name != "message" or event_id is not None:
                            data_str = "\n".join(data_lines)
                        
                            # Attempt to parse data as JSON, otherwise keep as string
                            try:
                                payload = json.loads(data_str) if data_str else {}
                            except json.JSONDecodeError:
                                payload = data_str
                        
                            event_dict = {
                                "event": event_name,
                                "data": payload,
                            }
                            if event_id:
                                event_dict['id'] = event_id
                        
                            if self.on_event:
                                try:
                                    self.on_event(event_dict)
                                except Exception as e:
                                    logger.exception("Error in SSE event callback")
                            else:
                                logger.warning(f"[SSEClient] No on_event callback registered for '{self._device_id}'")

        except Exception as e:
            # Catch all exceptions to prevent thread crashes
            if not self._stop_event.is_set():
                logger.exception(f"SSE stream for '{self._device_id}' ended unexpectedly: {self._ensure_str(e)}")
            else:
                logger.info(f"SSE stream for '{self._device_id}' ended (stop requested)")
        finally:
            logger.info(f"SSE stream loop ended for device '{self._device_id}'")
