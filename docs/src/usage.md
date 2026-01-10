# Usage Examples

Practical examples and patterns for common LabDaemon use cases.

## Contents

- [Task Composition](#task-composition)
  - [Sequential Composition](#sequential-composition)
  - [Parallel Composition](#parallel-composition)
  - [Feedback Composition](#feedback-composition)
  - [Communication Between Tasks](#communication-between-tasks)
- [Streaming Patterns](#streaming-patterns)
  - [Device Streaming](#device-streaming)
  - [Client-Side Streaming](#client-side-streaming)
- [Client Connection Patterns](#client-connection-patterns)
  - [Robust Server Connection](#robust-server-connection)
  - [Multi-Server Coordination](#multi-server-coordination)
  - [Device Connection Management](#device-connection-management)
- [Error Handling Patterns](#error-handling-patterns)
  - [Task Error Handling](#task-error-handling)
  - [Device Error Handling](#device-error-handling)
- [Testing Patterns](#testing-patterns)
  - [Mock Devices for Testing](#mock-devices-for-testing)
  - [Test Fixtures](#test-fixtures)
  - [Integration Tests](#integration-tests)
- [Performance Optimization](#performance-optimization)
  - [Batch Operations](#batch-operations)
  - [Streaming with Rate Limiting](#streaming-with-rate-limiting)
- [Common Pitfalls and Solutions](#common-pitfalls-and-solutions)

## Task Composition

Tasks can be composed hierarchically to build complex experiments from simple components.

### Sequential Composition

Execute tasks one after another, passing results between them:

```python
class CalibratedMeasurement:
    def run(self, context):
        # Step 1: Calibration
        cal_handle = context.daemon.execute_task(
            "cal", "CalibrationTask", ...
        )
        cal_result = cal_handle.wait()
        
        # Step 2: Measurement with calibration result
        measure_handle = context.daemon.execute_task(
            "measure", "MeasurementTask",
            calibration=cal_result  # Pass result forward
        )
        return measure_handle.wait()
```

### Parallel Composition

Run multiple tasks simultaneously and collect results:

```python
import queue

class ParallelAcquisition:
    def run(self, context):
        result_queue = queue.Queue()
        handles = []
        
        # Start multiple acquisitions
        for det_id in self.detector_ids:
            h = context.daemon.execute_task(
                f"acquire_{det_id}", "AcquisitionTask",
                detector_id=det_id,
                result_queue=result_queue
            )
            handles.append(h)
        
        # Collect results
        results = {}
        for h in handles:
            det_id, data = result_queue.get()
            results[det_id] = data
            h.wait()
        
        return results
```

### Feedback Composition

Adapt execution based on intermediate results:

```python
class AdaptiveScan:
    def run(self, context):
        # Initial scan
        scan_handle = context.daemon.execute_task("scan", "ScanTask", ...)
        scan_result = scan_handle.wait()
        
        # Adapt based on results
        if scan_result['feature_found']:
            refine_handle = context.daemon.execute_task(
                "refine", "RefineTask",
                position=scan_result['feature_position']
            )
            return refine_handle.wait()
        
        return scan_result
```

### Communication Between Tasks

Tasks communicate via various mechanisms:

#### Return Values
Simple data passing between tasks:

```python
def run(self, context):
    # Task returns data
    handle = context.daemon.execute_task("task1", "DataProducer")
    result = handle.wait()  # Get return value
    
    # Use result in next task
    handle2 = context.daemon.execute_task("task2", "DataConsumer", data=result)
    return handle2.wait()
```

#### Queues
Streaming data collection between producer and consumer:

```python
import queue

# Producer task
class ProducerTask:
    def run(self, context):
        for i in range(100):
            data = self.acquire()
            context.result_queue.put(("producer", data))

# Consumer task
class ConsumerTask:
    def run(self, context):
        results = []
        for _ in range(100):
            source, data = context.result_queue.get()
            results.append(data)
        return results

# Orchestrator
class PipelineTask:
    def run(self, context):
        result_queue = queue.Queue()
        
        # Start producer
        prod = context.daemon.execute_task(
            "prod", "ProducerTask", result_queue=result_queue
        )
        
        # Start consumer
        cons = context.daemon.execute_task(
            "cons", "ConsumerTask", result_queue=result_queue
        )
        
        # Wait for completion
        prod.wait()
        return cons.wait()
```

#### Events
Synchronization triggers:

```python
import threading

class TriggeredAcquisition:
    def run(self, context):
        trigger_event = threading.Event()
        
        # Start waiting task
        wait_handle = context.daemon.execute_task(
            "wait", "WaitForTrigger",
            trigger_event=trigger_event
        )
        
        # Do other work...
        self.prepare_system()
        
        # Trigger the waiting task
        trigger_event.set()
        
        # Get result
        return wait_handle.wait()
```

## Streaming Patterns

### Device Streaming

Implement streaming in devices:

```python
class StreamingDevice:
    def start_streaming(self, callback: Callable, **kwargs):
        """Start streaming data to callback."""
        self._callback = callback
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._streaming_loop)
        self._thread.start()
    
    def stop_streaming(self):
        """Stop streaming (idempotent)."""
        self._stop_event.set()
        if self._thread:
            self._thread.join()
    
    def _streaming_loop(self):
        while not self._stop_event.is_set():
            data = self._acquire_data()
            
            # Protect shared state
            with self._ld_lock:  # Use injected lock
                self._latest_data = data
                self._timestamp = time.time()
            
            # Callback is called outside lock
            if self._callback:
                self._callback(data)
```

### Client-Side Streaming

Connect to streaming data:

```python
# Local streaming
def data_callback(data):
    print(f"Received: {data}")

device = daemon.get_device("daq1")
device.start_streaming(callback=data_callback)

# Server streaming via SSE
import requests

response = requests.get(
    "http://localhost:5000/stream/devices/daq1",
    stream=True
)

for line in response.iter_lines():
    if line:
        event, data = line.decode().split('\n', 1)
        if event == 'data:':
            import json
            payload = json.loads(data[5:])  # Remove 'data: ' prefix
            print(f"Stream data: {payload}")
```

## Client Connection Patterns

### Robust Server Connection

```python
import time
from labdaemon.server import ServerAPI
from labdaemon.patterns import ensure_server

class RobustClient:
    def __init__(self, server_url: str, max_retries=5):
        self.server_url = server_url
        self.max_retries = max_retries
        self.api = None
    
    def connect(self):
        """Connect with retry logic."""
        for attempt in range(self.max_retries):
            try:
                if ensure_server(self.server_url, timeout=2.0):
                    self.api = ServerAPI(self.server_url)
                    return True
            except Exception:
                pass
            
            if attempt < self.max_retries - 1:
                time.sleep(2 ** attempt)  # Exponential backoff
        
        return False
    
    def call_with_fallback(self, device_id, method, args=None):
        """Call method with fallback handling."""
        try:
            if not self.api:
                if not self.connect():
                    raise ConnectionError("Could not connect to server")
            
            return self.api.call_device_method(device_id, method, args or [])
        
        except Exception as e:
            # Handle errors gracefully
            print(f"Error calling {method}: {e}")
            return None
```

### Multi-Server Coordination

```python
class MultiServerClient:
    def __init__(self, servers):
        self.servers = [ServerAPI(url) for url in servers]
    
    def find_device(self, device_id):
        """Find which server has a device."""
        for api in self.servers:
            try:
                devices = api.list_devices()
                if device_id in devices:
                    return api
            except:
                continue
        return None
    
    def execute_on_device(self, device_id, method, args=None):
        """Execute method on device regardless of which server it's on."""
        api = self.find_device(device_id)
        if api:
            return api.call_device_method(device_id, method, args or [])
        raise ValueError(f"Device {device_id} not found on any server")
```

### Device Connection Management

The labdaemon server provides explicit API endpoints for managing device connections. This gives remote clients control over device lifecycle with proper error handling and ownership respect.

```python
from labdaemon.server import ServerAPI

api = ServerAPI("http://localhost:5000")

# Check connection status
device = api.get_device("laser1")
print(f"Connected: {device['connected']}")

# Connect/disconnect devices
if not device['connected']:
    api.connect_device("laser1")
    print("Device connected")

api.disconnect_device("laser1")
print("Device disconnected")

# Batch operations
def connect_required_devices(api, device_ids):
    connected = []
    for device_id in device_ids:
        try:
            device = api.get_device(device_id)
            if not device['connected']:
                api.connect_device(device_id)
            connected.append(device_id)
        except Exception as e:
            print(f"Failed to connect {device_id}: {e}")
    return connected

# Usage
devices = ["laser1", "daq1"]
connected = connect_required_devices(api, devices)
print(f"Connected: {connected}")
```

## Error Handling Patterns

### Task Error Handling

```python
class RobustTask:
    def run(self, context):
        try:
            # Do work
            result = self.do_work(context)
            
            # Validate result
            if not self.validate_result(result):
                raise ValueError("Invalid result")
            
            return result
            
        except Exception as e:
            # Log error with context
            context.log_error(f"Task failed: {e}")
            
            # Try recovery
            if self.attempt_recovery(context):
                # Retry once
                return self.do_work(context)
            
            # Re-raise if recovery fails
            raise
```

### Device Error Handling

```python
class ResilientDevice:
    def connect(self):
        """Connect with retry logic."""
        for attempt in range(3):
            try:
                self._instrument.connect(self.address)
                return True
            except Exception as e:
                if attempt == 2:
                    raise
                time.sleep(1)
        return False
    
    def safe_call(self, method, *args, **kwargs):
        """Call method with error handling."""
        try:
            return getattr(self._instrument, method)(*args, **kwargs)
        except Exception as e:
            # Try to reconnect
            try:
                self.connect()
                return getattr(self._instrument, method)(*args, **kwargs)
            except:
                raise  # Re-raise original error
```

## Testing Patterns

### Mock Devices for Testing

```python
class MockLaser:
    """Mock laser for testing without hardware."""
    
    def __init__(self, device_id: str, **kwargs):
        self.device_id = device_id
        self._wavelength = 1550.0
        self._power = 0.0
        self._connected = False
    
    def connect(self):
        self._connected = True
    
    def disconnect(self):
        self._connected = False
    
    def set_wavelength(self, wl: float):
        if not self._connected:
            raise RuntimeError("Not connected")
        self._wavelength = wl
    
    def get_wavelength(self) -> float:
        return self._wavelength
    
    def set_power(self, power: float):
        if not self._connected:
            raise RuntimeError("Not connected")
        self._power = max(0, min(power, 100))  # Clamp to 0-100
    
    def get_power(self) -> float:
        return self._power
```

### Test Fixtures

```python
import pytest
import labdaemon as ld

@pytest.fixture
def daemon():
    """Create a daemon with mock devices."""
    daemon = ld.LabDaemon()
    daemon.register_plugins(devices={"MockLaser": MockLaser})
    yield daemon
    daemon.shutdown()

@pytest.fixture
def device(daemon):
    """Add a mock laser device."""
    device = daemon.add_device("laser1", "MockLaser")
    daemon.connect_device(device)
    return device

def test_laser_operations(device):
    """Test basic laser operations."""
    # Set wavelength
    device.set_wavelength(1550.0)
    assert device.get_wavelength() == 1550.0
    
    # Set power
    device.set_power(50.0)
    assert device.get_power() == 50.0
    
    # Test power clamping
    device.set_power(150.0)
    assert device.get_power() == 100.0
```

### Integration Tests

```python
def test_task_workflow(daemon):
    """Test a complete task workflow."""
    
    class TestTask:
        def __init__(self, task_id: str, device_id: str):
            self.task_id = task_id
            self.device_id = device_id
        
        def run(self, context):
            device = context.daemon.get_device(self.device_id)
            device.set_wavelength(1550.0)
            device.set_power(10.0)
            return {"wavelength": 1550.0, "power": 10.0}
    
    # Register task
    daemon.register_plugins(tasks={"TestTask": TestTask})
    
    # Execute task
    handle = daemon.execute_task("test1", "TestTask", device_id="laser1")
    result = handle.wait()
    
    # Verify result
    assert result["wavelength"] == 1550.0
    assert result["power"] == 10.0
```

## Performance Optimization

### Batch Operations

```python
class BatchDevice:
    """Device that supports batch operations."""
    
    def set_multiple(self, **kwargs):
        """Set multiple parameters in one call."""
        commands = []
        for param, value in kwargs.items():
            commands.append(f"{param.upper()} {value}")
        
        # Send all commands at once
        self._instrument.write(";".join(commands))
    
    # Usage
    device.set_multiple(wavelength=1550.0, power=10.0, temperature=25.0)
```

### Streaming with Rate Limiting

```python
class RateLimitedStreamer:
    def __init__(self, max_rate=100):  # Hz
        self.max_rate = max_rate
        self.min_interval = 1.0 / max_rate
        self.last_time = 0
    
    def _streaming_loop(self):
        while not self._stop_event.is_set():
            current_time = time.time()
            
            # Rate limiting
            elapsed = current_time - self.last_time
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            
            # Acquire and send data
            data = self._acquire_data()
            if self._callback:
                self._callback(data)
            
            self.last_time = time.time()
```

## Common Pitfalls and Solutions

### Blocking in Callbacks

Don't perform long operations in streaming callbacks:

```python
# BAD - blocks streaming thread
def data_callback(data):
    result = slow_processing(data)  # Blocks!
    database.save(result)

# GOOD - offload to worker thread
import queue
import threading

def data_callback(data):
    work_queue.put(data)

def worker_thread():
    while True:
        data = work_queue.get()
        result = slow_processing(data)
        database.save(result)

# Start worker thread
work_queue = queue.Queue()
threading.Thread(target=worker_thread, daemon=True).start()
device.start_streaming(callback=data_callback)
```

### Forgetting Device Ownership

Remember to declare device ownership in server tasks:

```python
class MyTask:
    def __init__(self, task_id: str, laser_id: str, daq_id: str):
        self.task_id = task_id
        self.laser_id = laser_id
        self.daq_id = daq_id
        self.device_ids = [laser_id, daq_id]  # IMPORTANT: Declare ownership
```
