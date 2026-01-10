# Core API Reference

Complete Python API for LabDaemon. For HTTP/SSE endpoints, see [Server API Reference](server_api.md).

## LabDaemon

```python
class LabDaemon:
    def __init__(self, completed_task_buffer: int = 20) -> None:
        """Create LabDaemon instance.
        
        Parameters:
        - completed_task_buffer (int, default 20): Number of completed tasks to retain 
          in memory. When this limit is exceeded, the oldest completed tasks are 
          automatically removed using LRU (Least Recently Used) eviction. The cleanup 
          is triggered each time a new task completes. Useful for long-running servers 
          to prevent memory accumulation.
        
        Examples:
        >>> import labdaemon as ld
        >>> daemon = ld.LabDaemon()  # Default configuration
        >>> daemon = ld.LabDaemon(completed_task_buffer=50)  # Custom buffer size
        """
    
    def register_plugins(self, devices: Dict[str, Type], tasks: Dict[str, Type]) -> None:
        """Register device and task classes with the framework.
        
        Parameters:
        - devices (Dict[str, Type]): Mapping of device type names to device classes
        - tasks (Dict[str, Type]): Mapping of task type names to task classes
        
        Examples:
        >>> daemon.register_plugins(
        ...     devices={"MyLaser": MyLaser, "MyDAQ": MyDAQ},
        ...     tasks={"SweepTask": SweepTask}
        ... )
        """
    
    def add_device(self, device_id: str, device_type: str, **kwargs) -> Any:
        """Create and register device instance with thread-safe method wrapping.
        
        Parameters:
        - device_id (str): Unique identifier for this device instance
        - device_type (str): Registered device type name (must be registered via register_plugins)
        - **kwargs: Passed to device __init__()
        
        Returns:
        - Device instance with injected _ld_lock for synchronisation
        
        Examples:
        >>> laser = daemon.add_device("laser1", "MyLaser", address="GPIB0::1")
        """
    
    def connect_device(self, device: Union[str, Any], timeout: Optional[float] = None) -> None:
        """Connect device by calling its connect() method.
        
        Parameters:
        - device (Union[str, Any]): Device instance or device_id string
        - timeout (float, optional): Timeout in seconds. If None, no timeout
        
        Examples:
        >>> daemon.connect_device(laser)
        >>> daemon.connect_device("laser1")  # Equivalent
        """
    
    def disconnect_device(self, device: Union[str, Any], timeout: Optional[float] = None) -> None:
        """Disconnect device by calling its disconnect() method. Idempotent.
        
        Parameters:
        - device (Union[str, Any]): Device instance or device_id string
        - timeout (float, optional): Timeout in seconds. If None, no timeout
        
        Examples:
        >>> daemon.disconnect_device(laser)
        """
    
    def get_device(self, device_id: str) -> Any:
        """Retrieve device instance by ID.
        
        Parameters:
        - device_id (str): Device identifier
        
        Returns:
        - Device instance
        
        Examples:
        >>> laser = daemon.get_device("laser1")
        """
    
    def device_context(self, device_id: str, device_type: str, **kwargs) -> ContextManager:
        """Context manager for automatic device lifecycle management.
        
        Parameters:
        - device_id (str): Unique identifier for this device instance
        - device_type (str): Registered device type name
        - **kwargs: Passed to device __init__()
        
        Returns:
        - Context manager that yields device instance
        
        Examples:
        >>> with daemon.device_context("laser1", "MyLaser", address="GPIB0::1") as laser:
        ...     laser.set_wavelength(1550)
        ... # Device automatically disconnected and shutdown
        """
    
    def execute_task(self, task_id: str, task_type: str, **kwargs) -> TaskHandle:
        """Execute task in background thread.
        
        Parameters:
        - task_id (str): Unique identifier for this task execution
        - task_type (str): Registered task type name
        - **kwargs: Passed to task __init__()
        
        Returns:
        - TaskHandle for monitoring and controlling the task
        
        Examples:
        >>> handle = daemon.execute_task(
        ...     "sweep1", "SweepTask",
        ...     laser_id="laser1", start_wl=1550, stop_wl=1560
        ... )
        >>> result = handle.wait()
        """
    
    def task_context(self, task_id: str, task_type: str, **kwargs) -> ContextManager:
        """Context manager for automatic task cancellation on exit.
        
        Parameters:
        - task_id (str): Unique identifier for this task execution
        - task_type (str): Registered task type name
        - **kwargs: Passed to task __init__()
        
        Returns:
        - Context manager that yields TaskHandle
        
        Examples:
        >>> with daemon.task_context("sweep1", "SweepTask", laser_id="laser1") as handle:
        ...     result = handle.wait()
        ... # Task automatically cancelled if still running
        """
    
    def start_streaming(self, device: Union[str, Any], callback: Callable) -> None:
        """Start streaming on device by calling its start_streaming(callback) method.
        
        Parameters:
        - device (Union[str, Any]): Device instance or device_id string
        - callback (Callable): Function called with data as it arrives: callback(data)
        
        Examples:
        >>> def on_data(data):
        ...     print(f"Received: {data}")
        >>> daemon.start_streaming(daq, callback=on_data)
        """
    
    def stop_streaming(self, device: Union[str, Any], timeout: Optional[float] = 1.0) -> None:
        """Stop streaming on device by calling its stop_streaming(timeout) method.
        
        Parameters:
        - device (Union[str, Any]): Device instance or device_id string
        - timeout (float, optional): Timeout in seconds for stopping. Default 1.0
        
        Examples:
        >>> daemon.stop_streaming(daq, timeout=2.0)
        """
    
    def shutdown(self, timeout: Optional[float] = 2.0) -> None:
        """Gracefully stop all streaming, cancel all tasks, disconnect all devices.
        
        Parameters:
        - timeout (float, optional): Timeout in seconds. Default 2.0
        
        Examples:
        >>> daemon.shutdown(timeout=5.0)
        """
```

## LabDaemonServer

```python
from labdaemon.server import LabDaemonServer

class LabDaemonServer:
    def __init__(self, daemon: LabDaemon, host: str = "0.0.0.0", port: int = 5000) -> None:
        """Create server instance.
        
        Parameters:
        - daemon (LabDaemon): LabDaemon instance to expose
        - host (str, default "0.0.0.0"): Bind address. Use "127.0.0.1" for localhost only
        - port (int, default 5000): Bind port
        
        Examples:
        >>> from labdaemon.server import LabDaemonServer
        >>> server = LabDaemonServer(daemon, host="0.0.0.0", port=5000)
        """
    
    def start(self, blocking: bool = False) -> None:
        """Start the server.
        
        Parameters:
        - blocking (bool, default False): If True, block until server stops. 
          If False, run in background
        
        Examples:
        >>> server.start(blocking=False)  # Run in background
        >>> server.start(blocking=True)   # Block until stopped
        """
    
    def stop(self, timeout: float = 5.0) -> None:
        """Stop the server gracefully.
        
        Parameters:
        - timeout (float, default 5.0): Timeout in seconds for graceful shutdown
        
        Examples:
        >>> server.stop(timeout=5.0)
        """
```

See [Server API Reference](server_api.md) for complete HTTP/SSE endpoint documentation.

## ServerAPI

```python
from labdaemon.server import ServerAPI

class ServerAPI:
    def __init__(self, base_url: str = "http://localhost:5000") -> None:
        """Create API client.
        
        Parameters:
        - base_url (str, default "http://localhost:5000"): Base URL of the LabDaemon server
        
        Examples:
        >>> api = ServerAPI("http://localhost:5000")
        """
    
    # Device Methods
    def list_devices(self) -> Dict[str, Any]:
        """List all devices.
        
        Returns:
        - Dict with 'devices' key containing list of device info dicts
        
        Examples:
        >>> response = api.list_devices()
        >>> for device in response['devices']:
        ...     print(f"{device['device_id']}: {device['device_type']}")
        """
    
    def get_device(self, device_id: str) -> Dict[str, Any]:
        """Get device details.
        
        Parameters:
        - device_id (str): Device identifier
        
        Returns:
        - Device info including connection status and ownership
        
        Examples:
        >>> device = api.get_device("laser1")
        >>> print(f"Connected: {device['connected']}")
        """
    
    def get_device_methods(self, device_id: str) -> Dict[str, Any]:
        """Get introspection data for device methods.
        
        Parameters:
        - device_id (str): Device identifier
        
        Returns:
        - Dict with 'methods' key containing method signatures and docstrings
        
        Examples:
        >>> methods = api.get_device_methods("laser1")
        >>> for method in methods['methods']:
        ...     print(f"{method['name']}: {method['parameters']}")
        """
    
    def add_device(self, device_id: str, device_type: str, **params) -> Dict[str, Any]:
        """Add a new device to the daemon.
        
        Parameters:
        - device_id (str): Unique identifier for the device
        - device_type (str): Registered device type name
        - **params: Device-specific parameters passed to __init__()
        
        Returns:
        - Device info for the newly added device
        
        Examples:
        >>> device = api.add_device("laser2", "SantecLaser", address="GPIB0::2")
        """
    
    def connect_device(self, device_id: str) -> Dict[str, Any]:
        """Connect a device.
        
        Parameters:
        - device_id (str): Device identifier
        
        Returns:
        - Updated device info
        
        Examples:
        >>> device = api.connect_device("laser2")
        """
    
    def disconnect_device(self, device_id: str) -> Dict[str, Any]:
        """Disconnect a device.
        
        Parameters:
        - device_id (str): Device identifier
        
        Returns:
        - Updated device info
        
        Examples:
        >>> device = api.disconnect_device("laser2")
        """
    
    def call_device_method(self, device_id: str, method: str, 
                          args: Optional[list] = None, 
                          kwargs: Optional[dict] = None) -> Dict[str, Any]:
        """Call a device method.
        
        Parameters:
        - device_id (str): Device identifier
        - method (str): Method name
        - args (list, optional): Positional arguments
        - kwargs (dict, optional): Keyword arguments
        
        Returns:
        - Dict with 'result' key containing return value
        
        Examples:
        >>> result = api.call_device_method("laser1", "set_wavelength", args=[1550.0])
        >>> result = api.call_device_method(
        ...     "laser1", "set_wavelength",
        ...     kwargs={"wavelength_nm": 1550.0, "wait_for_stabilization": True}
        ... )
        """
    
    def get_device_error(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Get last error for a device.
        
        Parameters:
        - device_id (str): Device identifier
        
        Returns:
        - Error info dict, or None if no error recorded
        
        Examples:
        >>> error = api.get_device_error("laser1")
        >>> if error:
        ...     print(f"Error: {error['error']['message']}")
        """
    
    def clear_device_error(self, device_id: str) -> None:
        """Clear stored error for a device.
        
        Parameters:
        - device_id (str): Device identifier
        
        Examples:
        >>> api.clear_device_error("laser1")
        """
    
    # Task Methods
    def list_tasks(self) -> Dict[str, Any]:
        """List all tasks.
        
        Returns:
        - Dict with 'tasks' key containing list of task info dicts
        
        Examples:
        >>> response = api.list_tasks()
        >>> for task in response['tasks']:
        ...     print(f"{task['task_id']}: {task['task_type']}")
        """
    
    def get_task(self, task_id: str) -> Dict[str, Any]:
        """Get task details.
        
        Parameters:
        - task_id (str): Task identifier
        
        Returns:
        - Task info including running status and result
        
        Examples:
        >>> task = api.get_task("sweep1")
        >>> if not task['running']:
        ...     print(f"Result: {task['result']}")
        """
    
    def execute_task(self, task_id: str, task_type: str, 
                    params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute a task.
        
        Parameters:
        - task_id (str): Unique identifier for this task execution
        - task_type (str): Registered task type name
        - params (dict, optional): Task parameters passed to __init__()
        
        Returns:
        - Dict with task info and status
        
        Examples:
        >>> response = api.execute_task(
        ...     "sweep1", "SweepTask",
        ...     params={
        ...         "laser_id": "laser1", "daq_id": "daq1",
        ...         "start_wl": 1550, "stop_wl": 1560, "steps": 11
        ...     }
        ... )
        """
    
    def get_task_error(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get last error for a task.
        
        Parameters:
        - task_id (str): Task identifier
        
        Returns:
        - Error info dict, or None if no error recorded
        
        Examples:
        >>> error = api.get_task_error("sweep1")
        >>> if error:
        ...     print(f"Error: {error['error']['message']}")
        """
    
    def clear_task_error(self, task_id: str) -> None:
        """Clear stored error for a task.
        
        Parameters:
        - task_id (str): Task identifier
        
        Examples:
        >>> api.clear_task_error("sweep1")
        """
    
    def cancel_task(self, task_id: str) -> Dict[str, Any]:
        """Cancel a running task.
        
        Parameters:
        - task_id (str): Task identifier
        
        Returns:
        - Updated task info
        
        Examples:
        >>> api.cancel_task("sweep1")
        """
    
    def pause_task(self, task_id: str) -> Dict[str, Any]:
        """Pause a running task.
        
        Parameters:
        - task_id (str): Task identifier
        
        Returns:
        - Updated task info
        
        Examples:
        >>> api.pause_task("sweep1")
        """
    
    def resume_task(self, task_id: str) -> Dict[str, Any]:
        """Resume a paused task.
        
        Parameters:
        - task_id (str): Task identifier
        
        Returns:
        - Updated task info
        
        Examples:
        >>> api.resume_task("sweep1")
        """
    
    def set_task_parameter(self, task_id: str, key: str, value: Any) -> Dict[str, Any]:
        """Set a parameter on a running task.
        
        Parameters:
        - task_id (str): Task identifier
        - key (str): Parameter name
        - value (Any): Parameter value
        
        Returns:
        - Dict confirming parameter update
        
        Examples:
        >>> api.set_task_parameter("sweep1", "sweep_speed", 2.0)
        """
    
    def close(self) -> None:
        """Close the session.
        
        Examples:
        >>> api.close()
        """
```

## SSEClient

```python
from labdaemon.server import SSEClient

class SSEClient:
    def __init__(self, base_url: str = "http://localhost:5000", 
                 on_event: Optional[Callable[[Dict[str, Any]], None]] = None) -> None:
        """Create SSE client.
        
        Parameters:
        - base_url (str, default "http://localhost:5000"): Base URL of the LabDaemon server
        - on_event (Callable, optional): Callback function called with each event: on_event(event_dict).
          The callback runs in a background thread, so it should be thread-safe.
        
        Examples:
        >>> def on_data(event):
        ...     print(f"Received: {event['payload']}")
        >>> client = SSEClient("http://localhost:5000", on_event=on_data)
        """
    
    def start_device_stream(self, device_id: str) -> None:
        """Start streaming data from a device.
        
        Parameters:
        - device_id (str): Device identifier
        
        Examples:
        >>> client.start_device_stream("daq1")
        """
    
    def stop_stream(self, timeout: float = 5.0) -> None:
        """Stop the stream.
        
        Parameters:
        - timeout (float, default 5.0): Timeout in seconds for graceful shutdown
        
        Examples:
        >>> client.stop_stream(timeout=5.0)
        """
```

## TaskHandle

```python
class TaskHandle:
    def wait(self, timeout: Optional[float] = None) -> Any:
        """Block until task completes.
        
        Parameters:
        - timeout (float, optional): Timeout in seconds. If None, wait indefinitely
        
        Returns:
        - Task result
        
        Raises:
        - TaskFailedError: If task raised an exception
        - TaskCancelledError: If task was cancelled
        - TimeoutError: If timeout exceeded
        
        Examples:
        >>> result = handle.wait()
        >>> result = handle.wait(timeout=30.0)
        """
    
    def cancel(self) -> None:
        """Signal task to stop gracefully. Idempotent.
        
        Examples:
        >>> handle.cancel()
        """
    
    def is_running(self) -> bool:
        """Check if task thread is active.
        
        Returns:
        - True if task is running
        
        Examples:
        >>> if handle.is_running():
        ...     print("Task still running")
        """
    
    def exception(self) -> Optional[Exception]:
        """Get exception if task failed.
        
        Returns:
        - Exception raised by task, or None if task succeeded
        
        Examples:
        >>> if handle.exception():
        ...     print(f"Task failed: {handle.exception()}")
        """
    
    def pause(self) -> None:
        """Signal task to pause at next checkpoint.
        
        Note: Requires the task to implement pause/resume support by checking
        context.resume_event.wait() at appropriate checkpoints.
        
        Examples:
        >>> handle.pause()
        """
    
    def resume(self) -> None:
        """Signal task to resume execution.
        
        Note: Only works if the task implements pause/resume support.
        
        Examples:
        >>> handle.resume()
        """
    
    def is_paused(self) -> bool:
        """Check if pause signal sent.
        
        Returns:
        - True if pause signal is active
        
        Examples:
        >>> if handle.is_paused():
        ...     print("Task paused")
        """
    
    def set_parameter(self, key: str, value: Any) -> None:
        """Update task parameter.
        
        Note: Requires the task to implement set_parameter(key, value) method.
        
        Parameters:
        - key (str): Parameter name
        - value (Any): Parameter value
        
        Examples:
        >>> handle.set_parameter('sweep_speed', 2.0)
        """
    
    def get_parameter(self, key: str) -> Any:
        """Query task parameter or state.
        
        Note: Requires the task to implement get_parameter(key) method.
        
        Parameters:
        - key (str): Parameter name
        
        Returns:
        - Parameter value or state
        
        Examples:
        >>> progress = handle.get_parameter('progress')
        """
```

## TaskContext

```python
class TaskContext:
    daemon: LabDaemon
    """Access to LabDaemon instance for device control.
    
    Examples:
    >>> laser = context.daemon.get_device("laser1")
    """
    
    cancel_event: threading.Event
    """Cancellation signal. Check is_set() periodically to detect cancellation requests.
    
    Examples:
    >>> if context.cancel_event.is_set():
    ...     return {"status": "cancelled"}
    """
    
    resume_event: threading.Event
    """Pause/resume signal (gate semantics). Call wait() at pause checkpoints to block when paused.
    
    Examples:
    >>> context.resume_event.wait()  # Blocks if paused
    """
```

## Utility Functions

```python
import labdaemon as ld

def load_json(filepath: Path) -> Dict[str, Any]:
    """Load dictionary from JSON file.
    
    Parameters:
    - filepath (Path): Path to JSON file
    
    Returns:
    - Loaded data dict
    
    Examples:
    >>> from pathlib import Path
    >>> data = ld.load_json(Path("data.json"))
    """

def save_json(data: Dict[str, Any], filepath: Path, indent: int = 4, **kwargs) -> None:
    """Save dictionary to JSON file with NumPy array support.
    
    Parameters:
    - data (Dict[str, Any]): Data to save
    - filepath (Path): Path to JSON file
    - indent (int, default 4): JSON indentation level
    - **kwargs: Additional arguments passed to json.dump()
    
    Examples:
    >>> ld.save_json({"results": numpy_array}, Path("data.json"))
    """

class LabDaemonJSONEncoder(json.JSONEncoder):
    """JSON encoder that handles NumPy arrays by converting to lists.
    
    Examples:
    >>> import json
    >>> json.dumps(data, cls=ld.LabDaemonJSONEncoder)
    """

def save_hdf5(data: Dict[str, Any], filepath: Path, 
              metadata: Optional[Dict[str, Any]] = None, 
              overwrite: bool = False) -> None:
    """Save nested dictionary to HDF5 file.
    
    Parameters:
    - data (Dict[str, Any]): Data to save (nested dicts and arrays)
    - filepath (Path): Path to HDF5 file
    - metadata (dict, optional): Metadata to store in file attributes
    - overwrite (bool, default False): If True, overwrite existing file
    
    Examples:
    >>> ld.save_hdf5(
    ...     {"wavelengths": wl_array, "spectrum": spec_array},
    ...     Path("data.h5"),
    ...     metadata={"sample": "Si wafer", "temperature": 300}
    ... )
    """

def load_hdf5(filepath: Path, return_metadata: bool = False) -> Union[Dict[str, Any], Tuple[Dict[str, Any], Dict[str, Any]]]:
    """Load data from HDF5 file.
    
    Parameters:
    - filepath (Path): Path to HDF5 file
    - return_metadata (bool, default False): If True, also return metadata dict
    
    Returns:
    - Data dict, or (data, metadata) tuple if return_metadata=True
    
    Examples:
    >>> data = ld.load_hdf5(Path("data.h5"))
    >>> data, metadata = ld.load_hdf5(Path("data.h5"), return_metadata=True)
    """

def capture_metadata(**extra_metadata: Any) -> Dict[str, Any]:
    """Capture system metadata (timestamp, hostname, Python version, etc.).
    
    Parameters:
    - **extra_metadata: Additional metadata to include
    
    Returns:
    - Metadata dict with system info and extra fields
    
    Examples:
    >>> metadata = ld.capture_metadata(sample="Si wafer", temperature=300)
    """
```

## Device Injection

```python
# The framework injects helpers into device instances at add_device() time

class MyDevice:
    _ld_lock: threading.RLock
    """Per-device re-entrant lock for explicit synchronisation in device-owned threads.
    
    Examples:
    >>> class MyDevice:
    ...     def _background_thread(self):
    ...         with self._ld_lock:
    ...             self._shared_state = new_value
    """
```

## Exceptions

```python
import labdaemon as ld
from labdaemon.server import ServerAPIError, ServerConnectionError

# All exceptions inherit from LabDaemonException or Exception

class LabDaemonException(Exception):
    """Base exception for all framework errors."""

# Device Exceptions
class DeviceError(LabDaemonException):
    """Base device exception."""

class DeviceConnectionError(DeviceError):
    """Connection failed."""

class DeviceNotConnectedError(DeviceError):
    """Operation requires connection."""

class DeviceTimeoutError(DeviceError):
    """Operation timed out."""

class DeviceConfigurationError(DeviceError):
    """Invalid configuration."""

class DeviceOperationError(DeviceError):
    """Operation failed."""

# Task Exceptions
class TaskError(LabDaemonException):
    """Base task exception."""

class TaskCancelledError(TaskError):
    """Task was cancelled."""

class TaskFailedError(TaskError):
    """Task raised exception."""

# Server Exceptions (available in labdaemon.server)
class ServerAPIError(Exception):
    """Base server API error."""

class ServerConnectionError(ServerAPIError):
    """Failed to connect to server."""

# Usage Examples:
try:
    result = handle.wait()
except ld.TaskCancelledError:
    print("Task cancelled")
except ld.TaskFailedError as e:
    print(f"Task failed: {e}")

try:
    api = ServerAPI("http://localhost:5000")
    devices = api.list_devices()
except ServerConnectionError:
    print("Cannot connect to server")
except ServerAPIError as e:
    print(f"Server error: {e}")
```
