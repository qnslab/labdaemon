# Cheat Sheet

Quick reference for common LabDaemon tasks. For detailed explanations, see the full documentation.

## Local Script

### Basic Device Control

```python
import labdaemon as ld

daemon = ld.LabDaemon()
daemon.register_plugins(devices={"MyLaser": MyLaser})

# Context manager (auto-cleanup)
with daemon.device_context("laser1", "MyLaser", address="GPIB0::1") as laser:
    laser.set_wavelength(1550.0)

# Manual lifecycle
laser = daemon.add_device("laser1", "MyLaser", address="GPIB0::1")
daemon.connect_device(laser)
laser.set_wavelength(1550.0)
daemon.disconnect_device(laser)
daemon.shutdown()
```

### Background Tasks

```python
class MyTask:
    def __init__(self, task_id: str, device_id: str, **kwargs):
        self.task_id = task_id
        self.device_id = device_id
    
    def run(self, context: ld.TaskContext):
        device = context.daemon.get_device(self.device_id)
        
        # Check for cancellation
        if context.cancel_event.is_set():
            return {"status": "cancelled"}
        
        # Do work
        result = device.do_something()
        return {"status": "completed", "result": result}

daemon.register_plugins(tasks={"MyTask": MyTask})
handle = daemon.execute_task("task1", "MyTask", device_id="laser1")
result = handle.wait()
```

### Streaming

```python
def on_data(data):
    print(f"Received: {data}")

daemon.start_streaming(detector, callback=on_data)
# ... do work ...
daemon.stop_streaming(detector)
```

## Device Implementation

### Basic Device

```python
class MyDevice:
    def __init__(self, device_id: str, address: str, **kwargs):
        self.device_id = device_id
        self.address = address
        self._instrument = None
    
    def connect(self):
        # Connect to hardware
        pass
    
    def disconnect(self):
        # Clean up
        pass
    
    def my_method(self, param: float) -> float:
        # Public methods are automatically thread-safe
        return self._instrument.query(f"PARAM {param}")
```

### Streaming Device

```python
import threading

class StreamingDevice:
    def __init__(self, device_id: str, **kwargs):
        self.device_id = device_id
        self._streaming_thread = None
        self._stop_event = threading.Event()
        self._callback = None
    
    def connect(self):
        pass
    
    def disconnect(self):
        if self.is_streaming():
            self.stop_streaming()
    
    def start_streaming(self, callback, **kwargs):
        self._callback = callback
        self._stop_event.clear()
        self._streaming_thread = threading.Thread(
            target=self._streaming_loop, daemon=True
        )
        self._streaming_thread.start()
    
    def stop_streaming(self, timeout=None):
        self._stop_event.set()
        if self._streaming_thread:
            self._streaming_thread.join(timeout=timeout)
    
    def is_streaming(self) -> bool:
        return (self._streaming_thread is not None and 
                self._streaming_thread.is_alive())
    
    def _streaming_loop(self):
        while not self._stop_event.is_set():
            data = self._acquire_data()
            
            # Protect shared state
            with self._ld_lock:
                self._latest_data = data
            
            # Callback runs outside lock
            if self._callback:
                self._callback(data)
```

## Server

### Start Server

```python
from labdaemon.server import LabDaemonServer

daemon = ld.LabDaemon()
server = LabDaemonServer(daemon, host="0.0.0.0", port=5000)
server.start(blocking=False)

# ... do work ...

server.stop()
daemon.shutdown()
```

### Task with Device Ownership

```python
class MyTask:
    def __init__(self, task_id: str, laser_id: str, daq_id: str, **kwargs):
        self.task_id = task_id
        self.laser_id = laser_id
        self.daq_id = daq_id
        self.device_ids = [laser_id, daq_id]  # Declare ownership
    
    def run(self, context):
        # Devices are locked for this task
        laser = context.daemon.get_device(self.laser_id)
        daq = context.daemon.get_device(self.daq_id)
        # ... do work ...
```

### Task with Streaming

```python
from typing import Any, Callable, Optional

class VirtStreamDevice:
    def __init__(self, device_id: str, **kwargs):
        self.device_id = device_id
        self._callback: Optional[Callable[[Any], None]] = None
        self._streaming = False
        # Note: LabDaemon will inject _ld_lock and wrap public methods
    
    def connect(self): pass
    def disconnect(self): pass
    
    def start_streaming(self, callback: Callable[[Any], None]):
        self._callback = callback
        self._streaming = True
    
    def stop_streaming(self): 
        self._callback = None
        self._streaming = False
    
    def is_streaming(self):
        return self._streaming
    
    def send_data(self, data: Any):
        """Send data to all subscribed SSE clients."""
        if self._streaming and self._callback:
            self._callback(data)

class TaskWithStream:
    def __init__(self, task_id: str, enable_streaming: bool = False):
        self.task_id = task_id
        self.enable_streaming = enable_streaming
    
    def run(self, context):
        stream = None
        if self.enable_streaming:
            stream = context.daemon.add_device(
                f"stream-{self.task_id}", VirtStreamDevice
            )
            context.daemon.connect_device(stream)
            context.daemon.start_streaming(stream)
        
        # Send updates
        if stream:
            stream.send_data({"progress": 50, "status": "running"})
```

## Python Client API

### ServerAPI

```python
from labdaemon.server import ServerAPI

api = ServerAPI("http://localhost:5000")

# Devices
devices = api.list_devices()
device = api.get_device("laser1")
methods = api.get_device_methods("laser1")
result = api.call_device_method("laser1", "set_wavelength", args=[1550.0])
api.connect_device("laser1")
api.disconnect_device("laser1")

# Tasks
tasks = api.list_tasks()
task = api.get_task("sweep1")
api.execute_task("sweep1", "SweepTask", params={"laser_id": "laser1"})
api.cancel_task("sweep1")
api.set_task_parameter("sweep1", "speed", 2.0)

# Errors
error = api.get_device_error("laser1")
api.clear_device_error("laser1")
```

### SSEClient

```python
from labdaemon.server import SSEClient

def on_event(event):
    if event.get('event') == 'device_data':
        print(f"Data: {event['payload']}")

client = SSEClient("http://localhost:5000", on_event=on_event)
client.start_device_stream("daq1")
# ... stream runs in background ...
client.stop_stream()
```

## HTTP API Quick Reference

### Devices

```bash
GET /devices                           # List all
GET /devices/{device_id}               # Get details
GET /devices/{device_id}/methods       # List methods
POST /devices                          # Add device
POST /devices/{device_id}/connect      # Connect
POST /devices/{device_id}/disconnect   # Disconnect
POST /devices/{device_id}/call         # Call method
GET /devices/{device_id}/error         # Get error
DELETE /devices/{device_id}/error      # Clear error
```

### Tasks

```bash
GET /tasks                             # List all
GET /tasks/{task_id}                   # Get details
POST /tasks                            # Execute task
POST /tasks/{task_id}/cancel           # Cancel
POST /tasks/{task_id}/pause            # Pause
POST /tasks/{task_id}/resume           # Resume
POST /tasks/{task_id}/parameters       # Set parameter
GET /tasks/{task_id}/error             # Get error
DELETE /tasks/{task_id}/error          # Clear error
```

### Streaming

```bash
GET /stream/devices/{device_id}        # Stream device data (SSE)
```

## Patterns

### Ensure Server is Running

```python
from labdaemon.patterns import ensure_server

if ensure_server("http://localhost:5000", timeout=2.0):
    print("Server is healthy")
else:
    print("Server not responding")
```

### Ensure Device Exists

```python
from labdaemon.patterns import ensure_device
from labdaemon.server import ServerAPI

api = ServerAPI("http://localhost:5000")
device = ensure_device(
    api,
    device_id="laser2",
    device_type="SantecLaser",
    connect=True,
    address="GPIB0::2"
)
```

## Common Patterns

### Sequential Task Composition

```python
def run(self, context):
    # Task 1
    h1 = context.daemon.execute_task("task1", "Task1Type")
    r1 = h1.wait()
    
    # Task 2 (uses result from Task 1)
    h2 = context.daemon.execute_task("task2", "Task2Type", data=r1)
    return h2.wait()
```

### Parallel Task Composition

```python
import queue

def run(self, context):
    result_queue = queue.Queue()
    handles = []
    
    # Start multiple tasks
    for i in range(3):
        h = context.daemon.execute_task(
            f"task{i}", "TaskType",
            result_queue=result_queue
        )
        handles.append(h)
    
    # Collect results
    results = []
    for h in handles:
        results.append(result_queue.get())
        h.wait()
    
    return results
```

### Robust Server Connection

```python
import time
from labdaemon.patterns import ensure_server
from labdaemon.server import ServerAPI

def connect_with_retry(url, max_retries=5):
    for attempt in range(max_retries):
        if ensure_server(url, timeout=2.0):
            return ServerAPI(url)
        if attempt < max_retries - 1:
            time.sleep(2 ** attempt)  # Exponential backoff
    return None
```

### Mock Device for Testing

```python
class MockLaser:
    def __init__(self, device_id: str, **kwargs):
        self.device_id = device_id
        self._wavelength = 1550.0
    
    def connect(self):
        pass
    
    def disconnect(self):
        pass
    
    def set_wavelength(self, wl: float):
        self._wavelength = wl
    
    def get_wavelength(self) -> float:
        return self._wavelength
```

## Error Handling

### Task Error Handling

```python
def run(self, context):
    try:
        result = self._do_work()
        return {"status": "completed", "result": result}
    except Exception as e:
        logger.exception(f"Task failed: {e}")
        return {"status": "failed", "error": str(e)}
```

### Device Error Handling

```python
try:
    result = api.call_device_method("laser1", "set_wavelength", args=[1550])
except ServerAPIError as e:
    error = api.get_device_error("laser1")
    if error:
        print(f"Error: {error['error']['message']}")
```

## Data Serialization

### JSON

```python
import labdaemon as ld
from pathlib import Path

# Save
ld.save_json({"data": [1, 2, 3]}, Path("data.json"))

# Load
data = ld.load_json(Path("data.json"))
```

### HDF5

```python
import labdaemon as ld
from pathlib import Path

# Save with metadata
ld.save_hdf5(
    {"spectrum": spectrum_array, "wavelengths": wl_array},
    Path("data.h5"),
    metadata={"sample": "Si", "temperature": 300}
)

# Load
data, metadata = ld.load_hdf5(Path("data.h5"), return_metadata=True)
```

## Logging

```python
from loguru import logger

# Configure file logging
logger.add("experiment.log", rotation="500 MB")

# Use in code
logger.info("Experiment started")
logger.debug(f"Wavelength: {wl}")
logger.exception("Error occurred")
```

## Useful Imports

```python
# Core
import labdaemon as ld
from labdaemon import LabDaemon, TaskContext

# Server
from labdaemon.server import LabDaemonServer, ServerAPI, SSEClient

# Patterns
from labdaemon.patterns import ensure_server, ensure_device

# Utilities
from labdaemon import save_json, load_json, save_hdf5, load_hdf5, capture_metadata

# Exceptions
from labdaemon import (
    DeviceError, DeviceConnectionError, DeviceTimeoutError,
    TaskError, TaskCancelledError, TaskFailedError
)
from labdaemon.server import ServerAPIError, ServerConnectionError

# Logging
from loguru import logger
```

## See Also

- [Concepts](concepts.md) - Architecture and design philosophy
- [Core API Reference](core_api.md) - Complete Python API
- [Server API Reference](server_api.md) - Complete HTTP/SSE API
