# Server API Reference

Complete HTTP and SSE endpoint documentation for the LabDaemon server.

For Python client examples, see [Core API Reference - ServerAPI](core_api.md#serverapi) and [Core API Reference - SSEClient](core_api.md#sseclient).

## HTTP Endpoints

```http
# Server Info
GET /health
# Quick health check
# Returns: {"status": "healthy", "timestamp": "..."}

GET /
# Server information and available endpoints
# Returns: {"name": "LabDaemon Server", "version": "...", "endpoints": {...}}

# Device Management
GET /devices
# List all devices
# Returns: {"devices": [{"device_id": "laser1", "device_type": "MyLaser", "connected": true, ...}]}

GET /devices/{device_id}
# Get device details
# Returns: {"device_id": "laser1", "connected": true, "streaming": false, "owned_by": "sweep1", ...}
# 404: Device does not exist

GET /devices/{device_id}/methods
# List device methods with introspection data
# Returns: {"methods": [{"name": "set_wavelength", "parameters": [...], "doc": "..."}]}

POST /devices
# Add new device
# Body: {"device_id": "laser2", "device_type": "SantecLaser", "params": {"address": "GPIB0::2"}}
# Returns: device info
# 409: Device already exists

POST /devices/{device_id}/connect
# Connect device
# Returns: updated device info
# 409: Device owned by running task

POST /devices/{device_id}/disconnect
# Disconnect device
# Returns: updated device info
# 409: Device owned by running task

POST /devices/{device_id}/call
# Call device method
# Body: {"method": "set_wavelength", "args": [1550.5], "kwargs": {"wait_for_stabilization": true}}
# Returns: {"result": ..., "success": true}
# 409: Device owned by running task (POST only - GET always allowed)

GET /devices/{device_id}/error
# Get last device error
# Returns: {"error": {"type": "DeviceOperationError", "message": "...", "timestamp": "...", ...}}
# 404: No error recorded

DELETE /devices/{device_id}/error
# Clear device error
# Returns: 204 No Content

# Task Management
GET /tasks
# List all tasks
# Returns: {"tasks": [{"task_id": "sweep1", "task_type": "SweepTask", "running": true}]}

GET /tasks/{task_id}
# Get task details
# Returns: {"task_id": "sweep1", "running": false, "result": {...}, "exception": null}
# 404: Task does not exist

POST /tasks
# Execute task
# Body: {"task_id": "sweep1", "task_type": "SweepTask", "params": {"laser_id": "laser1", ...}}
# Returns: {"task_id": "sweep1", "device_ids": ["laser1", "daq1"], "status": "started"}
# 409: Device conflict (already owned by another task)

GET /tasks/{task_id}/error
# Get last task error
# Returns: {"error": {"type": "TaskFailedError", "message": "...", ...}}
# 404: No error recorded

DELETE /tasks/{task_id}/error
# Clear task error
# Returns: 204 No Content

POST /tasks/{task_id}/cancel
# Cancel running task
# Returns: 200 OK

POST /tasks/{task_id}/pause
# Pause running task
# Returns: 200 OK

POST /tasks/{task_id}/resume
# Resume paused task
# Returns: 200 OK

POST /tasks/{task_id}/parameters
# Set task parameter
# Body: {"key": "sweep_speed", "value": 2.0}
# Returns: 200 OK
# Note: Requires task to implement set_parameter(key, value)
```

## Server-Sent Events (SSE)

```http
GET /stream/devices/{device_id}
# Subscribe to real-time device data stream
# Returns: text/event-stream with device_data events
# Format: {"event": "device_data", "device_id": "daq1", "timestamp": "...", "sequence": 42, "payload": [...]}
```

**Event Format:**
- `event`: Always "device_data"
- `device_id`: Device identifier  
- `timestamp`: ISO 8601 UTC timestamp
- `sequence`: Monotonic sequence number (per stream)
- `payload`: Raw device data (NumPy arrays → lists)

**Characteristics:**
- Best-effort delivery (messages may drop under load)
- Monitoring-grade (visualization, not guaranteed delivery)
- Auto-reconnect on disconnect
- Poll `GET /devices` after reconnection to resync state

**Python Example:**
```python
from labdaemon.server import SSEClient

def on_data(event):
    if event.get('event') == 'device_data':
        payload = event.get('payload')
        print(f"[{event['sequence']}] Received {len(payload)} samples")

client = SSEClient("http://localhost:5000", on_event=on_data)
client.start_device_stream("daq1")
# ... do work ...
client.stop_stream()
```

**JavaScript Example:**
```javascript
const stream = new EventSource('http://localhost:5000/stream/devices/daq1');

stream.addEventListener('device_data', (e) => {
    const data = JSON.parse(e.data);
    console.log(`[${data.sequence}] Received data:`, data.payload);
    updatePlot(data.payload);
});

stream.onerror = (e) => {
    console.error('Stream error:', e);
    stream.close();
};
```

## Error Handling

**Error Schema:**
```json
{
  "error": {
    "type": "DeviceOperationError",
    "message": "Timeout waiting for trigger", 
    "origin": "device",
    "timestamp": "2024-01-15T10:30:00+00:00",
    "traceback": "...",
    "context": {"device_id": "daq1", "method": "wait_for_acquisition"}
  }
}
```

**Origin Values:**
- `"framework"` - LabDaemon core error
- `"device"` - Device method error  
- `"callback"` - Streaming callback error

**Error Lifecycle:**
- Each device/task stores at most one error
- New errors overwrite old ones
- Persist until explicitly cleared or daemon shutdown
- No automatic clearing

**When Errors Are Recorded:**
- Device method calls via `POST /devices/{device_id}/call`
- Device connect/disconnect failures
- Streaming callback failures
- Task execution failures

**Python Client Error Handling:**
```python
from labdaemon.server import ServerAPI, ServerAPIError

api = ServerAPI("http://localhost:5000")

try:
    result = api.call_device_method("laser1", "set_wavelength", args=[1550])
except ServerAPIError as e:
    print(f"Server error: {e}")
    
    # Get stored error for debugging
    error = api.get_device_error("laser1")
    if error:
        print(f"Error details: {error['error']}")
```

## Complete Examples

**Monitoring Script:**
```python
from labdaemon.server import ServerAPI
import time

api = ServerAPI("http://lab-server:5000")

# Monitor device state
while True:
    device = api.get_device("laser1")
    print(f"Connected: {device['connected']}, Owned by: {device['owned_by']}")
    
    # Check for errors
    error = api.get_device_error("laser1")
    if error:
        print(f"Error: {error['error']['message']}")
        api.clear_device_error("laser1")
    
    time.sleep(1)
```

**Task Execution and Monitoring:**
```python
from labdaemon.server import ServerAPI
import time

api = ServerAPI("http://lab-server:5000")

# Execute task
response = api.execute_task(
    "sweep1", "SweepTask",
    params={"laser_id": "laser1", "daq_id": "daq1", "steps": 100}
)
print(f"Task started: {response['task_id']}")

# Monitor until complete
while True:
    task = api.get_task("sweep1")
    if not task['running']:
        break
    print("Task running...")
    time.sleep(1)

# Get result
if task['exception']:
    print(f"Task failed: {task['exception']['error']['message']}")
else:
    print(f"Task completed: {len(task['result']['results'])} points")
```

**Real-Time Streaming:**
```python
from labdaemon.server import ServerAPI, SSEClient
import time

api = ServerAPI("http://lab-server:5000")

# Configure streaming
api.call_device_method(
    "daq1", "configure_streaming",
    kwargs={"sample_rate": 100000, "voltage_range": 1.0}
)

# Start streaming
data_points = []

def on_data(event):
    if event.get('event') == 'device_data':
        data_points.extend(event.get('payload', []))

client = SSEClient("http://lab-server:5000", on_event=on_data)
client.start_device_stream("daq1")

# Stream for 10 seconds
time.sleep(10)

# Stop streaming
client.stop_stream()

print(f"Collected {len(data_points)} data points")
```
